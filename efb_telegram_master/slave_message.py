# coding=utf-8

import html
import itertools
import logging
import os
import tempfile
import traceback
import urllib.parse
from pathlib import Path
from typing import Tuple, Optional, TYPE_CHECKING, List, IO, Union

import humanize
import pydub
import telegram  # lgtm [py/import-and-import-from]
import telegram.constants
import telegram.error
import telegram.ext
from PIL import Image
from telegram import InputFile, ChatAction, InputMediaPhoto, InputMediaDocument, InputMediaVideo, InputMediaAnimation, \
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyMarkup, TelegramError, InputMedia

from ehforwarderbot import Message, Status, coordinator
from ehforwarderbot.chat import ChatNotificationState, SelfChatMember, GroupChat, PrivateChat, SystemChat, Chat
from ehforwarderbot.constants import MsgType
from ehforwarderbot.message import LinkAttribute, LocationAttribute, MessageCommand, Reactions, \
    StatusAttribute
from ehforwarderbot.status import ChatUpdates, MemberUpdates, MessageRemoval, MessageReactionsUpdate
from . import utils
from .chat_destination_cache import ChatDestinationCache
from .chat_object_cache import ChatObjectCacheManager
from .commands import ETMCommandMsgStorage
from .constants import Emoji
from .locale_mixin import LocaleMixin
from .message import ETMMsg
from .msg_type import get_msg_type
from .utils import TelegramChatID, TelegramMessageID, OldMsgID

if TYPE_CHECKING:
    from . import TelegramChannel
    from .bot_manager import TelegramBotManager
    from .db import DatabaseManager


class SlaveMessageProcessor(LocaleMixin):
    """Process messages as Message objects from slave channels."""

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        self.bot: 'TelegramBotManager' = self.channel.bot_manager
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.flag: utils.ExperimentalFlagsManager = self.channel.flag
        self.db: 'DatabaseManager' = channel.db
        self.chat_dest_cache: ChatDestinationCache = channel.chat_dest_cache
        self.chat_manager: ChatObjectCacheManager = channel.chat_manager

    def is_silent(self, msg: Message) -> Optional[bool]:
        """Determine if a message shall be sent silently.
        Returns None if the message shall not be sent at all.
        """
        xid = msg.uid
        if isinstance(msg.author, SelfChatMember):
            # Message is send by admin not through EFB
            your_slave_msg = self.flag('your_message_on_slave')
            if your_slave_msg == 'silent':
                return True
            elif your_slave_msg == 'mute':
                self.logger.debug("[%s] Message is muted as it is from the admin.", xid)
                return None
        elif msg.chat.notification == ChatNotificationState.NONE or \
                (msg.chat.notification == ChatNotificationState.MENTIONS and
                 (not msg.substitutions or not msg.substitutions.is_mentioned)):
            # Shall not be notified in slave channel
            muted_on_slave = self.flag('message_muted_on_slave')
            if muted_on_slave == 'silent':
                return True
            elif muted_on_slave == 'mute':
                self.logger.debug("[%s] Message is muted due to slave channel settings.", xid)
                return None
        return False

    def send_message(self, msg: Message) -> Message:
        """
        Process a message from slave channel and deliver it to the user.

        Args:
            msg (Message): The message.
        """
        try:
            xid = msg.uid
            self.logger.debug("[%s] Slave message delivered to ETM.\n%s", xid, msg)

            msg_template, tg_dest = self.get_slave_msg_dest(msg)

            silent = self.is_silent(msg)
            if silent is None:
                self.logger.debug("[%s] Message is not delivered per silent settings.", xid)
                return msg

            if tg_dest is None:
                self.logger.debug("[%s] Sender of the message is muted.", xid)
                return msg

            # When editing message
            old_msg_id: Optional[OldMsgID] = None
            if msg.edit:
                old_msg = self.db.get_msg_log(slave_msg_id=msg.uid,
                                              slave_origin_uid=utils.chat_id_to_str(chat=msg.chat))
                if old_msg:

                    if old_msg.master_msg_id_alt:
                        old_msg_id = utils.message_id_str_to_id(old_msg.master_msg_id_alt)
                    else:
                        old_msg_id = utils.message_id_str_to_id(old_msg.master_msg_id)
                else:
                    self.logger.info('[%s] Was supposed to edit this message, '
                                     'but it does not exist in database. Sending new message instead.',
                                     msg.uid)

            self.dispatch_message(msg, msg_template, old_msg_id, tg_dest, silent)
        except Exception as e:
            self.logger.error("Error occurred while processing message from slave channel.\nMessage: %s\n%s\n%s",
                              repr(msg), repr(e), traceback.format_exc())
        return msg

    def dispatch_message(self, msg: Message, msg_template: str,
                         old_msg_id: Optional[OldMsgID], tg_dest: TelegramChatID,
                         silent: bool = False):
        """Dispatch with header, destination and Telegram message ID and destinations."""

        xid = msg.uid

        # When targeting a message (reply to)
        target_msg_id: Optional[TelegramMessageID] = None
        if isinstance(msg.target, Message):
            self.logger.debug("[%s] Message is replying to %s.", msg.uid, msg.target)
            log = self.db.get_msg_log(
                slave_msg_id=msg.target.uid,
                slave_origin_uid=utils.chat_id_to_str(chat=msg.target.chat)
            )
            if not log:
                self.logger.debug("[%s] Target message %s is not found in database.", msg.uid, msg.target)
            else:
                self.logger.debug("[%s] Target message has database entry: %s.", msg.uid, log)
                target_msg = utils.message_id_str_to_id(log.master_msg_id)
                if not target_msg or target_msg[0] != int(tg_dest):
                    self.logger.error('[%s] Trying to reply to a message not from this chat. '
                                      'Message destination: %s. Target message: %s.',
                                      msg.uid, tg_dest, target_msg)
                    target_msg_id = None
                else:
                    target_msg_id = target_msg[1]

        # Generate basic reply markup
        commands: Optional[List[MessageCommand]] = None
        reply_markup: Optional[InlineKeyboardMarkup] = None

        if msg.commands:
            commands = msg.commands
            buttons = []
            for idx, i in enumerate(commands):
                buttons.append([InlineKeyboardButton(i.name, callback_data=str(idx))])
            reply_markup = InlineKeyboardMarkup(buttons)

        reactions = self.build_reactions_footer(msg.reactions)

        msg.text = msg.text or ""

        # Type dispatching
        if msg.type == MsgType.Text:
            tg_msg = self.slave_message_text(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                             reply_markup, silent)
        elif msg.type == MsgType.Link:
            tg_msg = self.slave_message_link(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                             reply_markup, silent)
        elif msg.type == MsgType.Sticker:
            tg_msg = self.slave_message_sticker(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                                reply_markup, silent)
        elif msg.type == MsgType.Image:
            if self.flag("send_image_as_file"):
                tg_msg = self.slave_message_file(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                                 reply_markup, silent)
            else:
                tg_msg = self.slave_message_image(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                                  reply_markup, silent)
        elif msg.type == MsgType.Animation:
            tg_msg = self.slave_message_animation(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                                  reply_markup, silent)
        elif msg.type == MsgType.File:
            tg_msg = self.slave_message_file(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                             reply_markup, silent)
        elif msg.type == MsgType.Voice:
            tg_msg = self.slave_message_voice(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                              reply_markup, silent)
        elif msg.type == MsgType.Location:
            tg_msg = self.slave_message_location(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                                 reply_markup, silent)
        elif msg.type == MsgType.Video:
            tg_msg = self.slave_message_video(msg, tg_dest, msg_template, reactions, old_msg_id, target_msg_id,
                                              reply_markup, silent)
        elif msg.type == MsgType.Status:
            # Status messages are not to be recorded in databases
            return self.slave_message_status(msg, tg_dest)
        elif msg.type == MsgType.Unsupported:
            tg_msg = self.slave_message_unsupported(msg, tg_dest, msg_template, reactions, old_msg_id,
                                                    target_msg_id, reply_markup, silent)
        else:
            self.bot.send_chat_action(tg_dest, ChatAction.TYPING)
            tg_msg = self.bot.send_message(tg_dest, prefix=msg_template, suffix=reactions,
                                           disable_notification=silent,
                                           text=self._('Unknown type of message "{0}". (UT01)')
                                           .format(msg.type.name))

        if tg_msg and commands:
            self.channel.commands.register_command(tg_msg, ETMCommandMsgStorage(
                commands, coordinator.get_module_by_id(msg.author.module_id), msg_template, msg.text
            ))

        self.logger.debug("[%s] Message is sent to the user with telegram message id %s.%s.",
                          xid, tg_msg.chat.id, tg_msg.message_id)

        etm_msg = ETMMsg.from_efbmsg(msg, self.chat_manager)
        etm_msg.type_telegram = get_msg_type(tg_msg)
        etm_msg.put_telegram_file(tg_msg)
        self.db.add_or_update_message_log(etm_msg, tg_msg, old_msg_id)
        # self.logger.debug("[%s] Message inserted/updated to the database.", xid)

    def get_slave_msg_dest(self, msg: Message) -> Tuple[str, Optional[TelegramChatID]]:
        """Get the Telegram destination of a message with its header.

        Returns:
            msg_template (str): header of the message.
            tg_dest (Optional[str]): Telegram destination chat, None if muted.
        """
        xid = msg.uid
        msg.chat = self.chat_manager.update_chat_obj(msg.chat)
        msg.author = self.chat_manager.get_or_enrol_member(msg.chat, msg.author)

        chat_uid = utils.chat_id_to_str(chat=msg.chat)
        tg_chats = self.db.get_chat_assoc(slave_uid=chat_uid)
        tg_chat = None

        if tg_chats:
            tg_chat = tg_chats[0]
        self.logger.debug("[%s] The message should deliver to %s", xid, tg_chat)

        singly_linked = True
        if tg_chat:
            slaves = self.db.get_chat_assoc(master_uid=tg_chat)
            if slaves and len(slaves) > 1:
                singly_linked = False
                self.logger.debug("[%s] Sender is linked with other chats in a Telegram group.", xid)
        self.logger.debug("[%s] Message is in chat %s", xid, msg.chat)

        # Generate chat text template & Decide type target
        tg_dest = TelegramChatID(self.channel.config['admins'][0])

        if tg_chat:  # if this chat is linked
            tg_dest = TelegramChatID(int(utils.chat_id_str_to_id(tg_chat)[1]))
        else:
            singly_linked = False

        msg_template = self.generate_message_template(msg, singly_linked)
        self.logger.debug("[%s] Message is sent to Telegram chat %s, with header \"%s\".",
                          xid, tg_dest, msg_template)

        if self.chat_dest_cache.get(str(tg_dest)) != chat_uid:
            self.chat_dest_cache.remove(str(tg_dest))

        return msg_template, tg_dest

    def html_substitutions(self, msg: Message) -> str:
        """Build a Telegram-flavored HTML string for message text substitutions."""
        text = msg.text
        if msg.substitutions:
            ranges = sorted(msg.substitutions.keys())
            t = ""
            prev = 0
            for i in ranges:
                t += html.escape(text[prev:i[0]])
                sub_chat = msg.substitutions[i]
                if isinstance(sub_chat, SelfChatMember) or (isinstance(sub_chat, Chat) and sub_chat.has_self):
                    t += f'<a href="tg://user?id={self.channel.config["admins"][0]}">'
                    t += html.escape(text[i[0]:i[1]])
                    t += "</a>"
                else:
                    t += '<code>'
                    t += html.escape(text[i[0]:i[1]])
                    t += '</code>'
                prev = i[1]
            t += html.escape(text[prev:])
            return t
        elif text:
            return html.escape(text)
        return text

    def slave_message_text(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                           old_msg_id: OldMsgID = None,
                           target_msg_id: Optional[TelegramMessageID] = None,
                           reply_markup: Optional[ReplyMarkup] = None,
                           silent: bool = False) -> telegram.Message:
        """
        Send message as text to Telegram.

        Args:
            msg: Message
            tg_dest: Telegram Chat ID
            msg_template: Header of the message
            reactions: Footer of the message
            old_msg_id: Telegram message ID to edit
            target_msg_id: Telegram message ID to reply to
            reply_markup: Reply markup to be added to the message
            silent: Silent notification of the message when sending

        Returns:
            The telegram bot message object sent
        """
        self.logger.debug("[%s] Sending as a text message.", msg.uid)
        self.bot.send_chat_action(tg_dest, ChatAction.TYPING)

        text = self.html_substitutions(msg)

        if not old_msg_id:
            tg_msg = self.bot.send_message(tg_dest,
                                           text=text, prefix=msg_template, suffix=reactions,
                                           parse_mode='HTML',
                                           reply_to_message_id=target_msg_id,
                                           reply_markup=reply_markup,
                                           disable_notification=silent)
        else:
            # Cannot change reply_to_message_id when editing a message
            tg_msg = self.bot.edit_message_text(chat_id=old_msg_id[0],
                                                message_id=old_msg_id[1],
                                                text=text, prefix=msg_template, suffix=reactions,
                                                parse_mode='HTML',
                                                reply_markup=reply_markup)

        self.logger.debug("[%s] Processed and sent as text message", msg.uid)
        return tg_msg

    def slave_message_link(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                           old_msg_id: OldMsgID = None,
                           target_msg_id: Optional[TelegramMessageID] = None,
                           reply_markup: Optional[ReplyMarkup] = None,
                           silent: bool = False) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, ChatAction.TYPING)

        assert isinstance(msg.attributes, LinkAttribute)
        attributes: LinkAttribute = msg.attributes

        thumbnail = urllib.parse.quote(attributes.image or "", safe="?=&#:/")
        thumbnail = "<a href=\"%s\">🔗</a>" % thumbnail if thumbnail else "🔗"
        text = "%s <a href=\"%s\">%s</a>\n%s" % \
               (thumbnail,
                urllib.parse.quote(attributes.url, safe="?=&#:/"),
                html.escape(attributes.title or attributes.url),
                html.escape(attributes.description or ""))

        if msg.text:
            text += "\n\n" + self.html_substitutions(msg)
        if old_msg_id:
            return self.bot.edit_message_text(text=text, chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                              prefix=msg_template, suffix=reactions, parse_mode='HTML',
                                              reply_markup=reply_markup)
        else:
            return self.bot.send_message(chat_id=tg_dest,
                                         text=text,
                                         prefix=msg_template, suffix=reactions,
                                         parse_mode="HTML",
                                         reply_to_message_id=target_msg_id,
                                         reply_markup=reply_markup,
                                         disable_notification=silent)

    # Parameters to decide when to pictures as files
    IMG_MIN_SIZE = 1600
    """Threshold of dimension of the shorter side to send as file."""
    IMG_MAX_SIZE = 1200
    """Threshold of dimension of the longer side to send as file, used along with IMG_SIZE_RATIO."""
    IMG_SIZE_RATIO = 3.5
    """Threshold of aspect ratio (longer side to shorter side) to send as file, used along with IMG_SIZE_RATIO."""
    IMG_SIZE_MAX_RATIO = 10
    """Threshold of aspect ratio (longer side to shorter side) to send as file, used alone."""

    def slave_message_image(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                            old_msg_id: OldMsgID = None,
                            target_msg_id: Optional[TelegramMessageID] = None,
                            reply_markup: Optional[ReplyMarkup] = None,
                            silent: bool = False) -> telegram.Message:
        assert msg.file
        self.bot.send_chat_action(tg_dest, ChatAction.UPLOAD_PHOTO)
        self.logger.debug("[%s] Message is of %s type; Path: %s; MIME: %s", msg.uid, msg.type, msg.path, msg.mime)
        if msg.path:
            self.logger.debug("[%s] Size of %s is %s.", msg.uid, msg.path, os.stat(msg.path).st_size)

        if msg.text:
            text = self.html_substitutions(msg)
        elif msg_template:
            placeholder_flag = self.flag("default_media_prompt")
            if placeholder_flag == "emoji":
                text = "🖼️"
            elif placeholder_flag == "text":
                text = self._("Sent a picture.")
            else:
                text = ""
        else:
            text = ""
        try:
            # Avoid Telegram compression of pictures by sending high definition image messages as files
            # Code adopted from wolfsilver's fork:
            # https://github.com/wolfsilver/efb-telegram-master/blob/99668b60f7ff7b6363dfc87751a18281d9a74a09/efb_telegram_master/slave_message.py#L142-L163
            #
            # Rules:
            # 1. If the picture is too large -- shorter side is greater than IMG_MIN_SIZE, send as file.
            # 2. If the picture is large and thin --
            #        longer side is greater than IMG_MAX_SIZE, and
            #        aspect ratio (longer to shorter side ratio) is greater than IMG_SIZE_RATIO,
            #    send as file.
            # 3. If the picture is too thin -- aspect ratio grater than IMG_SIZE_MAX_RATIO, send as file.

            try:
                pic_img = Image.open(msg.path)
                max_size = max(pic_img.size)
                min_size = min(pic_img.size)
                img_ratio = max_size / min_size

                if min_size > self.IMG_MIN_SIZE:
                    send_as_file = True
                elif max_size > self.IMG_MAX_SIZE and img_ratio > self.IMG_SIZE_RATIO:
                    send_as_file = True
                elif img_ratio >= self.IMG_SIZE_MAX_RATIO:
                    send_as_file = True
                else:
                    send_as_file = False
            except IOError:  # Ignore when the image cannot be properly identified.
                send_as_file = False

            file_too_large = self.check_file_size(msg.file)
            edit_media = msg.edit_media
            if file_too_large:
                if old_msg_id:
                    if msg.edit_media:
                        edit_media = False
                    self.bot.send_message(chat_id=old_msg_id[0], reply_to_message_id=old_msg_id[1], text=file_too_large)
                else:
                    message = self.bot.send_message(chat_id=tg_dest, reply_to_message_id=target_msg_id, text=text,
                                                    parse_mode="HTML", reply_markup=reply_markup, disable_notification=silent,
                                                    prefix=msg_template, suffix=reactions)
                    message.reply_text(file_too_large)
                    return message

            if old_msg_id:
                try:
                    if edit_media:
                        assert msg.path
                        media: InputMedia
                        file = self.process_file_obj(msg.file, msg.path)
                        if send_as_file:
                            media = InputMediaDocument(file)
                        else:
                            media = InputMediaPhoto(file)
                        self.bot.edit_message_media(chat_id=old_msg_id[0], message_id=old_msg_id[1], media=media)
                    return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                                         reply_markup=reply_markup,
                                                         prefix=msg_template, suffix=reactions, caption=text, parse_mode="HTML")
                except telegram.error.BadRequest:
                    # Send as an reply if cannot edit previous message.
                    if old_msg_id[0] == str(target_msg_id):
                        target_msg_id = target_msg_id or old_msg_id[1]
                    msg.file.seek(0)

            if send_as_file:
                assert msg.path
                file = self.process_file_obj(msg.file, msg.path)
                return self.bot.send_document(tg_dest, file, prefix=msg_template, suffix=reactions,
                                              caption=text, parse_mode="HTML", filename=msg.filename,
                                              reply_to_message_id=target_msg_id,
                                              reply_markup=reply_markup,
                                              disable_notification=silent)
            else:
                try:
                    assert msg.path
                    file = self.process_file_obj(msg.file, msg.path)
                    return self.bot.send_photo(tg_dest, file, prefix=msg_template, suffix=reactions,
                                               caption=text, parse_mode="HTML",
                                               reply_to_message_id=target_msg_id,
                                               reply_markup=reply_markup,
                                               disable_notification=silent)
                except telegram.error.BadRequest as e:
                    self.logger.error('[%s] Failed to send it as image, sending as document. Reason: %s',
                                      msg.uid, e)
                    assert msg.path
                    file = self.process_file_obj(msg.file, msg.path)
                    return self.bot.send_document(tg_dest, file, prefix=msg_template, suffix=reactions,
                                                  caption=text, parse_mode="HTML", filename=msg.filename,
                                                  reply_to_message_id=target_msg_id,
                                                  reply_markup=reply_markup,
                                                  disable_notification=silent)
        finally:
            if msg.file:
                msg.file.close()

    def slave_message_animation(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                                old_msg_id: OldMsgID = None,
                                target_msg_id: Optional[TelegramMessageID] = None,
                                reply_markup: Optional[ReplyMarkup] = None,
                                silent: bool = None) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, ChatAction.UPLOAD_PHOTO)

        self.logger.debug("[%s] Message is an Animation; Path: %s; MIME: %s", msg.uid, msg.path, msg.mime)
        if msg.path:
            self.logger.debug("[%s] Size of %s is %s.", msg.uid, msg.path, os.stat(msg.path).st_size)

        if msg.text:
            text = self.html_substitutions(msg)
        else:
            text = ""

        try:
            file_too_large = self.check_file_size(msg.file)
            edit_media = msg.edit_media
            if file_too_large:
                if old_msg_id:
                    if msg.edit_media:
                        edit_media = False
                    self.bot.send_message(chat_id=old_msg_id[0], reply_to_message_id=old_msg_id[1], text=file_too_large)
                else:
                    message = self.bot.send_message(chat_id=tg_dest, reply_to_message_id=target_msg_id, text=text,
                                                    parse_mode="HTML", reply_markup=reply_markup,
                                                    disable_notification=silent,
                                                    prefix=msg_template, suffix=reactions)
                    message.reply_text(file_too_large)
                    return message

            if old_msg_id:
                if edit_media:
                    assert msg.file and msg.path
                    file = self.process_file_obj(msg.file, msg.path)
                    self.bot.edit_message_media(chat_id=old_msg_id[0], message_id=old_msg_id[1], media=InputMediaAnimation(file))
                return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                                     prefix=msg_template, suffix=reactions,
                                                     reply_markup=reply_markup,
                                                     caption=text, parse_mode="HTML")
            else:
                assert msg.file and msg.path
                file = self.process_file_obj(msg.file, msg.path)
                file_: Union[IO[bytes], bytes] = open(file, 'rb') if isinstance(file, str) else file
                return self.bot.send_animation(tg_dest, InputFile(file_, filename=msg.filename),
                                               prefix=msg_template, suffix=reactions,
                                               caption=text, parse_mode="HTML",
                                               reply_to_message_id=target_msg_id,
                                               reply_markup=reply_markup,
                                               disable_notification=silent)
        finally:
            if msg.file is not None:
                msg.file.close()

    def slave_message_sticker(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                              old_msg_id: OldMsgID = None,
                              target_msg_id: Optional[TelegramMessageID] = None,
                              reply_markup: Optional[InlineKeyboardMarkup] = None,
                              silent: bool = False) -> telegram.Message:

        self.bot.send_chat_action(tg_dest, ChatAction.UPLOAD_PHOTO)

        sticker_reply_markup = self.build_chat_info_inline_keyboard(msg, msg_template, reactions, reply_markup)

        self.logger.debug("[%s] Message is of %s type; Path: %s; MIME: %s", msg.uid, msg.type, msg.path, msg.mime)
        if msg.path:
            self.logger.debug("[%s] Size of %s is %s.", msg.uid, msg.path, os.stat(msg.path).st_size)

        try:
            if msg.edit_media and old_msg_id is not None:
                target_msg_id = old_msg_id[1]
                old_msg_id = None
            if old_msg_id and not msg.edit_media:
                try:
                    return self.bot.edit_message_reply_markup(chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                                              reply_markup=sticker_reply_markup)
                except TelegramError:
                    return self.bot.send_message(chat_id=old_msg_id[0], reply_to_message_id=old_msg_id[1],
                                                 prefix=msg_template, text=msg.text, suffix=reactions,
                                                 reply_markup=reply_markup,
                                                 disable_notification=silent)

            else:
                webp_img = None

                file_too_large = self.check_file_size(msg.file)
                if file_too_large:
                    if old_msg_id:
                        self.bot.send_message(chat_id=old_msg_id[0], reply_to_message_id=old_msg_id[1],
                                              text=file_too_large)
                    else:
                        message = self.bot.send_message(chat_id=tg_dest, reply_to_message_id=target_msg_id,
                                                        text=self.html_substitutions(msg),
                                                        parse_mode="HTML", reply_markup=reply_markup,
                                                        disable_notification=silent,
                                                        prefix=msg_template, suffix=reactions)
                        message.reply_text(file_too_large)
                        return message

                try:
                    pic_img: Image = Image.open(msg.file)
                    webp_img = tempfile.NamedTemporaryFile(suffix='.webp')
                    pic_img.convert("RGBA").save(webp_img, 'webp')
                    webp_img.seek(0)
                    file = self.process_file_obj(webp_img, webp_img.name)
                    return self.bot.send_sticker(tg_dest, file, reply_markup=sticker_reply_markup,
                                                 reply_to_message_id=target_msg_id,
                                                 disable_notification=silent)
                except IOError:
                    assert msg.file and msg.path
                    file = self.process_file_obj(msg.file, msg.path)
                    return self.bot.send_document(tg_dest, file, prefix=msg_template, suffix=reactions,
                                                  caption=msg.text, filename=msg.filename,
                                                  reply_to_message_id=target_msg_id,
                                                  reply_markup=reply_markup,
                                                  disable_notification=silent)
                finally:
                    if webp_img and not webp_img.closed:
                        webp_img.close()
        finally:
            if msg.file and not msg.file.closed:
                msg.file.close()

    @staticmethod
    def build_chat_info_inline_keyboard(msg: Message, msg_template: str, reactions: str,
                                        reply_markup: Optional[InlineKeyboardMarkup]
                                        ) -> InlineKeyboardMarkup:
        """
        Build inline keyboard markup with message header and footer (reactions). Buttons are attached
        before any other commands attached.
        """
        description = []
        if msg_template:
            description.append([InlineKeyboardButton(msg_template, callback_data="void")])
        if msg.text:
            description.append([InlineKeyboardButton(msg.text, callback_data="void")])
        if reactions:
            description.append([InlineKeyboardButton(reactions, callback_data="void")])
        sticker_reply_markup = reply_markup or InlineKeyboardMarkup([])
        sticker_reply_markup.inline_keyboard = description + sticker_reply_markup.inline_keyboard
        return sticker_reply_markup

    def slave_message_file(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                           old_msg_id: OldMsgID = None,
                           target_msg_id: Optional[TelegramMessageID] = None,
                           reply_markup: Optional[ReplyMarkup] = None,
                           silent: bool = False) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, ChatAction.UPLOAD_DOCUMENT)

        if msg.filename is None and msg.path is not None:
            file_name = os.path.basename(msg.path)
        else:
            assert msg.filename is not None  # mypy compliance
            file_name = msg.filename

        # Telegram Bot API drops everything after `;` in filenames
        # Replace it with a space
        # Note: it also seems to strip off a lot of unicode punctuations
        file_name = file_name.replace(';', ' ')

        if msg.text:
            text = self.html_substitutions(msg)
        elif msg_template:
            placeholder_flag = self.flag("default_media_prompt")
            if placeholder_flag == "emoji":
                text = "📄"
            elif placeholder_flag == "text":
                text = self._("Sent a file.")
            else:
                text = ""
        else:
            text = ""

        try:
            file_too_large = self.check_file_size(msg.file)
            edit_media = msg.edit_media
            if file_too_large:
                if old_msg_id:
                    if msg.edit_media:
                        edit_media = False
                    self.bot.send_message(chat_id=old_msg_id[0], reply_to_message_id=old_msg_id[1], text=file_too_large)
                else:
                    message = self.bot.send_message(chat_id=tg_dest, reply_to_message_id=target_msg_id, text=text,
                                                    parse_mode="HTML", reply_markup=reply_markup,
                                                    disable_notification=silent,
                                                    prefix=msg_template, suffix=reactions)
                    message.reply_text(file_too_large)
                    return message

            if old_msg_id:
                if edit_media:
                    assert msg.file is not None and msg.path is not None
                    file = self.process_file_obj(msg.file, msg.path)
                    self.bot.edit_message_media(chat_id=old_msg_id[0], message_id=old_msg_id[1], media=InputMediaDocument(file))
                return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1], reply_markup=reply_markup,
                                                     prefix=msg_template, suffix=reactions, caption=text, parse_mode="HTML")
            assert msg.file is not None and msg.path is not None
            self.logger.debug("[%s] Uploading file %s (%s) as %s", msg.uid,
                              msg.file.name, msg.mime, file_name)
            file = self.process_file_obj(msg.file, msg.path)
            return self.bot.send_document(tg_dest, file,
                                          prefix=msg_template, suffix=reactions,
                                          caption=text, parse_mode="HTML", filename=file_name,
                                          reply_to_message_id=target_msg_id,
                                          reply_markup=reply_markup,
                                          disable_notification=silent)
        finally:
            if msg.file is not None:
                msg.file.close()

    def slave_message_voice(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                            old_msg_id: OldMsgID = None,
                            target_msg_id: Optional[TelegramMessageID] = None,
                            reply_markup: Optional[ReplyMarkup] = None,
                            silent: bool = False) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, ChatAction.RECORD_AUDIO)
        if msg.text:
            text = self.html_substitutions(msg)
        else:
            text = ""
        self.logger.debug("[%s] Message is a voice file.", msg.uid)
        try:
            file_too_large = self.check_file_size(msg.file)
            edit_media = msg.edit_media
            if file_too_large:
                if old_msg_id:
                    if msg.edit_media:
                        edit_media = False
                    self.bot.send_message(chat_id=old_msg_id[0], reply_to_message_id=old_msg_id[1], text=file_too_large)
                else:
                    message = self.bot.send_message(chat_id=tg_dest, reply_to_message_id=target_msg_id, text=text,
                                                    parse_mode="HTML", reply_markup=reply_markup,
                                                    disable_notification=silent,
                                                    prefix=msg_template, suffix=reactions)
                    message.reply_text(file_too_large)
                    return message

            if old_msg_id:
                if edit_media:
                    # Cannot edit voice message content, send a new one instead
                    msg_template += " " + self._("[Edited]")
                    if str(tg_dest) == old_msg_id[0]:
                        target_msg_id = target_msg_id or old_msg_id[1]
                else:
                    return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                                         reply_markup=reply_markup, prefix=msg_template,
                                                         suffix=reactions, caption=text, parse_mode="HTML")
            assert msg.file is not None
            with tempfile.NamedTemporaryFile() as f:
                pydub.AudioSegment.from_file(msg.file).export(f, format="ogg", codec="libopus",
                                                              parameters=['-vbr', 'on'])
                file = self.process_file_obj(f, f.name)
                tg_msg = self.bot.send_voice(tg_dest, file, prefix=msg_template, suffix=reactions,
                                             caption=text, parse_mode="HTML",
                                             reply_to_message_id=target_msg_id, reply_markup=reply_markup,
                                             disable_notification=silent)
            return tg_msg
        finally:
            if msg.file is not None:
                msg.file.close()

    def slave_message_location(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                               old_msg_id: OldMsgID = None,
                               target_msg_id: Optional[TelegramMessageID] = None,
                               reply_markup: Optional[InlineKeyboardMarkup] = None,
                               silent: bool = False) -> telegram.Message:
        # TODO: Move msg_template to caption during MTProto migration (if we ever had a chance to do that).
        self.bot.send_chat_action(tg_dest, ChatAction.FIND_LOCATION)
        assert (isinstance(msg.attributes, LocationAttribute))
        attributes: LocationAttribute = msg.attributes
        self.logger.info("[%s] Sending as a Telegram venue.\nlat: %s, long: %s\ntitle: %s\naddress: %s",
                         msg.uid,
                         attributes.latitude, attributes.longitude,
                         msg.text, msg_template)

        self.logger.debug("[%s] Location message received with old_msg_id %s, compare it with tg_dest %s", msg.uid, old_msg_id, tg_dest)
        if old_msg_id and old_msg_id[0] == str(tg_dest):
            # TRANSLATORS: Flag for messages edited on slave channels, but cannot be edited on Telegram.
            msg_template += " " + self._('[edited]')
            target_msg_id = target_msg_id or old_msg_id[1]
            self.logger.debug("[%s] updated target_msg_id %s", msg.uid, target_msg_id)

        location_reply_markup = self.build_chat_info_inline_keyboard(msg, msg_template, reactions, reply_markup)

        # TODO: Use live location if possible? Lift live location messages to EFB Framework?
        return self.bot.send_location(tg_dest, latitude=attributes.latitude,
                                      longitude=attributes.longitude, reply_to_message_id=target_msg_id,
                                      reply_markup=location_reply_markup,
                                      disable_notification=silent)

    def slave_message_video(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                            old_msg_id: OldMsgID = None,
                            target_msg_id: Optional[TelegramMessageID] = None,
                            reply_markup: Optional[ReplyMarkup] = None,
                            silent: bool = False) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, ChatAction.UPLOAD_VIDEO)
        if msg.text:
            text = self.html_substitutions(msg)
        elif msg_template:
            placeholder_flag = self.flag("default_media_prompt")
            if placeholder_flag == "emoji":
                text = "🎥"
            elif placeholder_flag == "text":
                text = self._("Sent a file.")
            else:
                text = ""
        else:
            text = ""
        try:
            file_too_large = self.check_file_size(msg.file)
            edit_media = msg.edit_media
            if file_too_large:
                if old_msg_id:
                    if msg.edit_media:
                        edit_media = False
                    self.bot.send_message(chat_id=old_msg_id[0], reply_to_message_id=old_msg_id[1], text=file_too_large)
                else:
                    message = self.bot.send_message(chat_id=tg_dest, reply_to_message_id=target_msg_id, text=text,
                                                    parse_mode="HTML", reply_markup=reply_markup,
                                                    disable_notification=silent,
                                                    prefix=msg_template, suffix=reactions)
                    message.reply_text(file_too_large)
                    return message

            if old_msg_id:
                if edit_media:
                    assert msg.file is not None and msg.path is not None
                    file = self.process_file_obj(msg.file, msg.path)
                    self.bot.edit_message_media(chat_id=old_msg_id[0], message_id=old_msg_id[1], media=InputMediaVideo(file))
                return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1], reply_markup=reply_markup,
                                                     prefix=msg_template, suffix=reactions, caption=text, parse_mode="HTML")
            assert msg.file is not None and msg.path is not None
            file = self.process_file_obj(msg.file, msg.path)
            return self.bot.send_video(tg_dest, file, prefix=msg_template, suffix=reactions,
                                       caption=text, parse_mode="HTML",
                                       reply_to_message_id=target_msg_id,
                                       reply_markup=reply_markup,
                                       disable_notification=silent)
        finally:
            if msg.file is not None:
                msg.file.close()

    def slave_message_unsupported(self, msg: Message, tg_dest: TelegramChatID, msg_template: str, reactions: str,
                                  old_msg_id: OldMsgID = None,
                                  target_msg_id: Optional[TelegramMessageID] = None,
                                  reply_markup: Optional[ReplyMarkup] = None,
                                  silent: bool = False) -> telegram.Message:
        self.logger.debug("[%s] Sending as an unsupported message.", msg.uid)
        self.bot.send_chat_action(tg_dest, ChatAction.TYPING)

        if msg.text:
            text = self.html_substitutions(msg)
        else:
            text = ""

        if not old_msg_id:
            tg_msg = self.bot.send_message(tg_dest,
                                           text=text, parse_mode="HTML",
                                           prefix=msg_template + " " + self._("(unsupported)"),
                                           suffix=reactions,
                                           reply_to_message_id=target_msg_id, reply_markup=reply_markup,
                                           disable_notification=silent)
        else:
            # Cannot change reply_to_message_id when editing a message
            tg_msg = self.bot.edit_message_text(chat_id=old_msg_id[0],
                                                message_id=old_msg_id[1],
                                                text=text, parse_mode="HTML",
                                                prefix=msg_template + " " + self._("(unsupported)"),
                                                suffix=reactions,
                                                reply_markup=reply_markup)

        self.logger.debug("[%s] Processed and sent as text message", msg.uid)
        return tg_msg

    def slave_message_status(self, msg: Message, tg_dest: TelegramChatID):
        attributes = msg.attributes
        assert isinstance(attributes, StatusAttribute)
        if attributes.status_type is StatusAttribute.Types.TYPING:
            self.bot.send_chat_action(tg_dest, ChatAction.TYPING)
        elif attributes.status_type is StatusAttribute.Types.UPLOADING_VOICE:
            self.bot.send_chat_action(tg_dest, ChatAction.RECORD_AUDIO)
        elif attributes.status_type is StatusAttribute.Types.UPLOADING_IMAGE:
            self.bot.send_chat_action(tg_dest, ChatAction.UPLOAD_PHOTO)
        elif attributes.status_type is StatusAttribute.Types.UPLOADING_VIDEO:
            self.bot.send_chat_action(tg_dest, ChatAction.UPLOAD_VIDEO)
        elif attributes.status_type is StatusAttribute.Types.UPLOADING_FILE:
            self.bot.send_chat_action(tg_dest, ChatAction.UPLOAD_DOCUMENT)

    def send_status(self, status: Status):
        if isinstance(status, ChatUpdates):
            self.logger.debug("Received chat updates from channel %s", status.channel)
            for i in status.removed_chats:
                self.db.delete_slave_chat_info(status.channel.channel_id, i)
                self.chat_manager.delete_chat_object(status.channel.channel_id, i)
            for i in itertools.chain(status.new_chats, status.modified_chats):
                chat = status.channel.get_chat(i)
                self.chat_manager.update_chat_obj(chat, full_update=True)
        elif isinstance(status, MemberUpdates):
            self.logger.debug("Received member updates from channel %s about group %s",
                              status.channel, status.chat_id)
            for i in status.removed_members:
                self.db.delete_slave_chat_info(status.channel.channel_id, i, status.chat_id)
            self.chat_manager.delete_chat_members(status.channel.channel_id, status.chat_id, status.removed_members)
            chat = status.channel.get_chat(status.chat_id)
            self.chat_manager.update_chat_obj(chat, full_update=True)
        elif isinstance(status, MessageRemoval):
            self.logger.debug("Received message removal request from channel %s on message %s",
                              status.source_channel, status.message)
            old_msg = self.db.get_msg_log(
                slave_msg_id=status.message.uid,
                slave_origin_uid=utils.chat_id_to_str(chat=status.message.chat))
            if old_msg:
                old_msg_id: OldMsgID = utils.message_id_str_to_id(old_msg.master_msg_id)
                self.logger.debug("Found message to delete in Telegram: %s.%s",
                                  *old_msg_id)
                try:
                    if not self.channel.flag('prevent_message_removal'):
                        self.bot.delete_message(*old_msg_id)
                        return
                except TelegramError:
                    pass
                self.bot.send_message(chat_id=old_msg_id[0],
                                      text=self._("Message is removed in remote chat."),
                                      reply_to_message_id=old_msg_id[1])
            else:
                self.logger.info('Was supposed to delete a message, '
                                 'but it does not exist in database: %s', status)
        elif isinstance(status, MessageReactionsUpdate):
            self.update_reactions(status)
        else:
            self.logger.error('Received an unsupported type of status: %s', status)

    @staticmethod
    def build_reactions_footer(reactions: Reactions) -> str:
        """Generate a footer string for reactions in the format similar to [🙂×3, ❤️×1].
        Returns '' if no reaction is found.
        """
        result = "[" + ", ".join(f"{k}×{len(v)}" for k, v in reactions.items() if len(v)) + "]"
        if result == "[]":
            return ""
        return result

    def update_reactions(self, status: MessageReactionsUpdate):
        """Update reactions to a Telegram message."""
        old_msg_db = self.db.get_msg_log(slave_msg_id=status.msg_id,
                                         slave_origin_uid=utils.chat_id_to_str(chat=status.chat))
        if old_msg_db is None:
            self.logger.exception('Trying to update reactions of message, but message is not found in database. '
                                  'Message ID %s from %s, status: %s.', status.msg_id, status.chat, status.reactions)
            return

        old_msg: ETMMsg = old_msg_db.build_etm_msg(chat_manager=self.chat_manager)
        old_msg.reactions = status.reactions
        old_msg.edit = True

        msg_template, _ = self.get_slave_msg_dest(old_msg)
        effective_msg = old_msg_db.master_msg_id_alt or old_msg_db.master_msg_id
        chat_id, msg_id = utils.message_id_str_to_id(effective_msg)

        # Go through the ordinary update process
        self.dispatch_message(old_msg, msg_template, old_msg_id=(chat_id, msg_id), tg_dest=chat_id)

    def generate_message_template(self, msg: Message, singly_linked: bool) -> str:
        msg_prefix = ""  # For group member name
        if isinstance(msg.chat, GroupChat):
            self.logger.debug("[%s] Message is from a group. Sender: %s", msg.uid, msg.author)
            msg_prefix = msg.author.long_name

        if singly_linked:
            if msg_prefix:  # if group message
                msg_template = f"{msg_prefix}:"
            else:
                if msg.chat != msg.author:
                    msg_template = f"{msg.author.long_name}:"
                else:
                    msg_template = ""
        elif isinstance(msg.chat, PrivateChat):
            emoji_prefix = msg.chat.channel_emoji + Emoji.USER
            name_prefix = msg.chat.long_name
            if msg.chat.other != msg.author:
                name_prefix += f", {msg.author.long_name}"
            msg_template = f"{emoji_prefix} {name_prefix}:"
        elif isinstance(msg.chat, GroupChat):
            emoji_prefix = msg.chat.channel_emoji + Emoji.GROUP
            name_prefix = msg.chat.long_name
            msg_template = f"{emoji_prefix} {msg_prefix} [{name_prefix}]:"
        elif isinstance(msg.chat, SystemChat):
            emoji_prefix = msg.chat.channel_emoji + Emoji.SYSTEM
            name_prefix = msg.chat.long_name
            if msg.chat.other != msg.author:
                name_prefix += f", {msg.author.long_name}"
            msg_template = f"{emoji_prefix} {name_prefix}:"
        else:
            msg_template = f"{Emoji.UNKNOWN} {msg.author.long_name} ({msg.chat.display_name}):"
        return msg_template

    def check_file_size(self, file: Optional[IO[bytes]]) -> Optional[str]:
        """
        Return an error message if the file is too large to upload,
        None otherwise.
        """
        if not file or getattr(file, "closed", True):
            return None
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        if not self.channel.flag("local_tdlib_api") and file_size > telegram.constants.MAX_FILESIZE_UPLOAD:
            size_str = humanize.naturalsize(file_size)
            max_size_str = humanize.naturalsize(telegram.constants.MAX_FILESIZE_UPLOAD)
            return self._(
                "Attachment is too large ({size}). Maximum allowed by Telegram Bot API is {max_size}. (AT02)").format(
                size=size_str, max_size=max_size_str)
        return None

    def process_file_obj(self, file: IO[bytes], path: Union[str, Path]) -> Union[IO[bytes], str]:
        if self.channel.flag("local_tdlib_api"):
            return Path(path).absolute().as_uri()
        return file
