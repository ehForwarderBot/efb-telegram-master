# coding=utf-8

import html
import itertools
import logging
import os
import pickle
import tempfile
import traceback
import urllib.parse
from typing import Tuple, Optional, TYPE_CHECKING, List

import pydub
import telegram
import telegram.constants
import telegram.error
import telegram.ext
from PIL import Image

from ehforwarderbot import EFBMsg, EFBStatus, coordinator
from ehforwarderbot.constants import MsgType, ChatType
from ehforwarderbot.message import EFBMsgLinkAttribute, EFBMsgLocationAttribute, EFBMsgCommand
from ehforwarderbot.status import EFBChatUpdates, EFBMemberUpdates, EFBMessageRemoval
from . import utils, ETMChat
from .commands import ETMCommandMsgStorage
from .constants import Emoji
from .locale_mixin import LocaleMixin
from .message import ETMMsg
from .msg_type import get_msg_type

if TYPE_CHECKING:
    from . import TelegramChannel
    from .bot_manager import TelegramBotManager
    from .db import DatabaseManager


class SlaveMessageProcessor(LocaleMixin):
    """Process messages as EFBMsg objects from slave channels."""

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        self.bot: 'TelegramBotManager' = self.channel.bot_manager
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.flag: utils.ExperimentalFlagsManager = self.channel.flag
        self.db: 'DatabaseManager' = channel.db

    def send_message(self, msg: EFBMsg) -> EFBMsg:
        """
        Process a message from slave channel and deliver it to the user.

        Args:
            msg (EFBMsg): The message.
        """
        try:
            xid = msg.uid
            self.logger.debug("[%s] Slave message delivered to ETM.\n%s", xid, msg)

            chat_uid = utils.chat_id_to_str(chat=msg.chat)
            tg_chat = self.db.get_chat_assoc(slave_uid=chat_uid)
            if tg_chat:
                tg_chat = tg_chat[0]

            self.logger.debug("[%s] The message should deliver to %s", xid, tg_chat)

            if tg_chat == ETMChat.MUTE_CHAT_ID:
                self.logger.debug("[%s] Sender of the message is muted.", xid)
                return msg

            multi_slaves = False

            if tg_chat:
                slaves = self.db.get_chat_assoc(master_uid=tg_chat)
                if slaves and len(slaves) > 1:
                    multi_slaves = True
                    self.logger.debug("[%s] Sender is linked with other chats in a Telegram group.", xid)

            self.logger.debug("[%s] Message is in chat %s", xid, msg.chat)

            # Generate chat text template & Decide type target
            tg_dest = self.channel.config['admins'][0]
            if tg_chat:  # if this chat is linked
                tg_dest = int(utils.chat_id_str_to_id(tg_chat)[1])

            msg_template = self.generate_message_template(msg, tg_chat, multi_slaves)

            self.logger.debug("[%s] Message is sent to Telegram chat %s, with header \"%s\".",
                              xid, tg_dest, msg_template)

            # When editing message
            old_msg_id: Optional[Tuple[str, str]] = None
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

            # When targeting a message (reply to)
            target_msg_id: Optional[str] = None
            if isinstance(msg.target, EFBMsg):
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
                    if not target_msg or target_msg[0] != str(tg_dest):
                        self.logger.error('[%s] Trying to reply to a message not from this chat. '
                                          'Message destination: %s. Target message: %s.',
                                          msg.uid, tg_dest, target_msg)
                        target_msg_id = None
                    else:
                        target_msg_id = target_msg[1]

            commands: Optional[List[EFBMsgCommand]] = None
            reply_markup: Optional[telegram.InlineKeyboardMarkup] = None
            if msg.commands:
                commands = msg.commands.commands
                buttons = []
                for i, ival in enumerate(commands):
                    buttons.append([telegram.InlineKeyboardButton(ival.name, callback_data=str(i))])
                reply_markup = telegram.InlineKeyboardMarkup(buttons)

            msg.text = msg.text or ""

            # Type dispatching
            if msg.type == MsgType.Text:
                tg_msg = self.slave_message_text(msg, tg_dest, msg_template, old_msg_id, target_msg_id, reply_markup)
            elif msg.type == MsgType.Link:
                tg_msg = self.slave_message_link(msg, tg_dest, msg_template, old_msg_id, target_msg_id, reply_markup)
            elif msg.type == MsgType.Sticker:
                tg_msg = self.slave_message_image(msg, tg_dest, msg_template, old_msg_id, target_msg_id, reply_markup)
            elif msg.type == MsgType.Image:
                if self.flag("send_image_as_file"):
                    tg_msg = self.slave_message_file(msg, tg_dest, msg_template, old_msg_id, target_msg_id,
                                                     reply_markup)
                else:
                    tg_msg = self.slave_message_image(msg, tg_dest, msg_template, old_msg_id, target_msg_id,
                                                      reply_markup)
            elif msg.type == MsgType.File:
                tg_msg = self.slave_message_file(msg, tg_dest, msg_template, old_msg_id, target_msg_id, reply_markup)
            elif msg.type == MsgType.Audio:
                tg_msg = self.slave_message_audio(msg, tg_dest, msg_template, old_msg_id, target_msg_id, reply_markup)
            elif msg.type == MsgType.Location:
                tg_msg = self.slave_message_location(msg, tg_dest, msg_template, old_msg_id, target_msg_id,
                                                     reply_markup)
            elif msg.type == MsgType.Video:
                tg_msg = self.slave_message_video(msg, tg_dest, msg_template, old_msg_id, target_msg_id, reply_markup)
            elif msg.type == MsgType.Unsupported:
                tg_msg = self.slave_message_unsupported(msg, tg_dest, msg_template, old_msg_id, target_msg_id,
                                                        reply_markup)
            else:
                self.bot.send_chat_action(tg_dest, telegram.ChatAction.TYPING)
                tg_msg = self.bot.send_message(tg_dest, prefix=msg_template,
                                               text=self._("Unsupported type of message. (UT01)"))

            if tg_msg and msg.commands:
                self.channel.commands.register_command(tg_msg, ETMCommandMsgStorage(
                    commands, coordinator.get_module_by_id(msg.author.module_id), msg_template, msg.text
                ))

            self.logger.debug("[%s] Message is sent to the user with telegram message id %s.%s.",
                              xid, tg_msg.chat.id, tg_msg.message_id)

            etmmsg = ETMMsg.from_efbmsg(msg)
            etmmsg.put_telegram_file(tg_msg)

            msg_log = {"master_msg_id": utils.message_id_to_str(tg_msg.chat.id, tg_msg.message_id),
                       "text": msg.text or "Sent a %s." % msg.type,
                       "msg_type": msg.type,
                       "sent_to": "master" if msg.author.is_self else 'slave',
                       "slave_origin_uid": utils.chat_id_to_str(chat=msg.chat),
                       "slave_origin_display_name": msg.chat.chat_alias,
                       "slave_member_uid": msg.author.chat_uid if not msg.author.is_self else None,
                       "slave_member_display_name": msg.author.chat_alias if not msg.author.is_self else None,
                       "slave_message_id": msg.uid,
                       "update": msg.edit,
                       "media_type": etmmsg.type_telegram.value,
                       "file_id": etmmsg.file_id,
                       "mime": etmmsg.mime,
                       "pickle": pickle.dumps(etmmsg)
                       }

            if old_msg_id and old_msg_id != tg_msg.message_id:
                msg_log['master_msg_id'] = utils.message_id_to_str(*old_msg_id)
                msg_log['master_msg_id_alt'] = utils.message_id_to_str(tg_msg.chat.id, tg_msg.message_id)

            self.db.add_msg_log(**msg_log)
            self.logger.debug("[%s] Message inserted/updated to the database.", xid)
        except Exception as e:
            self.logger.error("[%s] Error occurred while processing message from slave channel.\nMessage: %s\n%s\n%s",
                              xid, repr(msg), repr(e), traceback.format_exc())

    def slave_message_text(self, msg: EFBMsg, tg_dest: str, msg_template: str,
                           old_msg_id: Optional[Tuple[str, str]] = None,
                           target_msg_id: Optional[str] = None,
                           reply_markup: Optional[telegram.ReplyMarkup] = None) -> telegram.Message:
        """
        Send message as text to Telegram.
        
        Args:
            msg (EFBMsg): Message
            tg_dest (str): Telegram Chat ID
            msg_template (str): Header of the message
            old_msg_id: Telegram message ID to edit
            target_msg_id: Telegram message ID to reply to
            reply_markup: Reply markup to be added to the message

        Returns:
            The telegram bot message object sent
        """
        self.logger.debug("[%s] Sending as a text message.", msg.uid)
        self.bot.send_chat_action(tg_dest, telegram.ChatAction.TYPING)

        text = msg.text
        msg_template = html.escape(msg_template)

        if msg.substitutions:
            ranges = sorted(msg.substitutions.keys())
            t = ""
            prev = 0
            for i in ranges:
                t += html.escape(text[prev:i[0]])
                if msg.substitutions[i].is_self:
                    t += '<a href="tg://user?id=%s">' % self.channel.config['admins'][0]
                    t += html.escape(text[i[0]:i[1]])
                    t += "</a>"
                else:
                    t += '<code>'
                    t += html.escape(text[i[0]:i[1]])
                    t += '</code>'
                prev = i[1]
            t += html.escape(text[prev:])
            text = t
        elif text:
            text = html.escape(text)

        if not old_msg_id:
            tg_msg = self.bot.send_message(tg_dest,
                                           text=text, prefix=msg_template,
                                           parse_mode='HTML',
                                           reply_to_message_id=target_msg_id,
                                           reply_markup=reply_markup)
        else:
            # Cannot change reply_to_message_id when editing a message
            tg_msg = self.bot.edit_message_text(chat_id=old_msg_id[0],
                                                message_id=old_msg_id[1],
                                                text=text, prefix=msg_template,
                                                parse_mode='HTML',
                                                reply_markup=reply_markup)

        self.logger.debug("[%s] Processed and sent as text message", msg.uid)
        return tg_msg

    def slave_message_link(self, msg: EFBMsg, tg_dest: str, msg_template: str,
                           old_msg_id: Optional[Tuple[str, str]] = None,
                           target_msg_id: Optional[str] = None,
                           reply_markup: Optional[telegram.ReplyMarkup] = None) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, telegram.ChatAction.TYPING)

        msg_template = html.escape(msg_template)

        assert (isinstance(msg.attributes, EFBMsgLinkAttribute))
        attributes: EFBMsgLinkAttribute = msg.attributes

        thumbnail = urllib.parse.quote(attributes.image or "", safe="?=&#:/")
        thumbnail = "<a href=\"%s\">🔗</a>" % thumbnail if thumbnail else "🔗"
        text = "%s <a href=\"%s\">%s</a>\n%s" % \
               (thumbnail,
                urllib.parse.quote(attributes.url, safe="?=&#:/"),
                html.escape(attributes.title or attributes.url),
                html.escape(attributes.description or ""))
        if msg.text:
            text += "\n\n" + msg.text
        if old_msg_id:
            return self.bot.edit_message_text(text, chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                              prefix=msg_template, parse_mode='HTML',
                                              reply_markup=reply_markup)
        else:
            return self.bot.send_message(chat_id=tg_dest,
                                         text=text,
                                         prefix=msg_template,
                                         parse_mode="HTML",
                                         reply_to_message_id=target_msg_id,
                                         reply_markup=reply_markup)

    # Parameters to decide when to pictures as files
    IMG_MIN_SIZE = 1600
    """Threshold of dimension of the shorter side to send as file."""
    IMG_MAX_SIZE = 1200
    """Threshold of dimension of the longer side to send as file, used along with IMG_SIZE_RATIO."""
    IMG_SIZE_RATIO = 3.5
    """Threshold of aspect ratio (longer side to shorter side) to send as file, used along with IMG_SIZE_RATIO."""
    IMG_SIZE_MAX_RATIO = 10
    """Threshold of aspect ratio (longer side to shorter side) to send as file, used alone."""

    def slave_message_image(self, msg: EFBMsg, tg_dest: str, msg_template: str,
                            old_msg_id: Optional[Tuple[str, str]] = None,
                            target_msg_id: Optional[str] = None,
                            reply_markup: Optional[telegram.ReplyMarkup] = None) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, telegram.ChatAction.UPLOAD_PHOTO)
        self.logger.debug("[%s] Message is of %s type; Path: %s; MIME: %s", msg.uid, msg.type, msg.path, msg.mime)
        if msg.path:
            self.logger.debug("[%s] Size of %s is %s.", msg.uid, msg.path, os.stat(msg.path).st_size)

        if not msg.text:
            if msg.type == MsgType.Image:
                msg.text = "sent a picture."
            elif msg.type == MsgType.Sticker:
                msg.text = "sent a sticker."
        try:
            if old_msg_id:
                if msg.edit_media:
                    self.bot.edit_message_media(chat_id=old_msg_id[0], message_id=old_msg_id[1], media=msg.file)
                return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                                     prefix=msg_template, caption=msg.text)
            else:
                # Send picture as file when the image file is a GIF.
                send_as_file = msg.mime == 'image/gif'

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

                if not send_as_file:
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
                    except IOError:  # Ignore when the image cannot be properly identified.
                        pass

                if send_as_file:
                    return self.bot.send_document(tg_dest, msg.file, prefix=msg_template, caption=msg.text,
                                                  reply_to_message_id=target_msg_id,
                                                  reply_markup=reply_markup)
                else:
                    try:
                        return self.bot.send_photo(tg_dest, msg.file, prefix=msg_template, caption=msg.text,
                                                   reply_to_message_id=target_msg_id,
                                                   reply_markup=reply_markup)
                    except telegram.error.BadRequest as e:
                        self.logger.error('[%s] Failed to send it as image, sending as document. Reason: %s', msg.uid,
                                          e)
                        return self.bot.send_document(tg_dest, msg.file, prefix=msg_template,
                                                      caption=msg.text, filename=msg.filename,
                                                      reply_to_message_id=target_msg_id,
                                                      reply_markup=reply_markup)
        finally:
            if msg.file:
                msg.file.close()

    def slave_message_file(self, msg: EFBMsg, tg_dest: str, msg_template: str,
                           old_msg_id: Optional[Tuple[str, str]] = None,
                           target_msg_id: Optional[str] = None,
                           reply_markup: Optional[telegram.ReplyMarkup] = None) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, telegram.ChatAction.UPLOAD_DOCUMENT)
        if not msg.filename:
            file_name = os.path.basename(msg.path)
            msg.text = "sent a file."
        else:
            file_name = msg.filename
        try:
            if old_msg_id:
                if msg.edit_media:
                    self.bot.edit_message_media(chat_id=old_msg_id[0], message_id=old_msg_id[1], media=msg.file)
                return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                                     prefix=msg_template, caption=msg.text)
            self.logger.debug("[%s] Uploading file %s (%s) as %s", msg.uid,
                              msg.file.name, msg.mime, file_name)
            return self.bot.send_document(tg_dest, msg.file,
                                          prefix=msg_template,
                                          caption=msg.text, filename=file_name,
                                          reply_to_message_id=target_msg_id,
                                          reply_markup=reply_markup)
        finally:
            msg.file.close()

    def slave_message_audio(self, msg: EFBMsg, tg_dest: str, msg_template: str,
                            old_msg_id: Optional[Tuple[str, str]] = None,
                            target_msg_id: Optional[str] = None,
                            reply_markup: Optional[telegram.ReplyMarkup] = None) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, telegram.ChatAction.RECORD_AUDIO)
        msg.text = msg.text or ''
        self.logger.debug("[%s] Message is an audio file.", msg.uid)
        no_conversion = self.flag("no_conversion")
        try:
            if old_msg_id:
                if msg.edit_media:
                    self.bot.edit_message_media(chat_id=old_msg_id[0], message_id=old_msg_id[1], media=msg.file)
                return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                                     prefix=msg_template, caption=msg.text)
            if no_conversion:
                self.logger.debug('[%s] This audio file is sent as a document without converting to OPUS.', msg.uid)
                self.logger.debug("[%s] MIME type reported by the message: %s", msg.uid, msg.mime)
                if msg.mime == "audio/mpeg":
                    tg_msg = self.bot.send_audio(tg_dest, msg.file, prefix=msg_template, caption=msg.text,
                                                 reply_to_message_id=target_msg_id, reply_markup=reply_markup)
                else:
                    tg_msg = self.bot.send_document(tg_dest, msg.file, prefix=msg_template, caption=msg.text,
                                                    reply_to_message_id=target_msg_id, reply_markup=reply_markup)
            else:
                with tempfile.NamedTemporaryFile() as f:
                    pydub.AudioSegment.from_file(msg.file).export(f, format="ogg", codec="libopus",
                                                                  parameters=['-vbr', 'on'])
                    tg_msg = self.bot.send_voice(tg_dest, f, prefix=msg_template, caption=msg.text,
                                                 reply_to_message_id=target_msg_id, reply_markup=reply_markup)
            return tg_msg
        finally:
            msg.file.close()

    def slave_message_location(self, msg: EFBMsg, tg_dest: str, msg_template: str,
                               old_msg_id: Optional[Tuple[str, str]] = None,
                               target_msg_id: Optional[str] = None,
                               reply_markup: Optional[telegram.ReplyMarkup] = None) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, telegram.ChatAction.FIND_LOCATION)
        assert (isinstance(msg.attributes, EFBMsgLocationAttribute))
        attributes: EFBMsgLocationAttribute = msg.attributes
        self.logger.info("[%s] Sending as a Telegram venue.\nlat: %s, long: %s\ntitle: %s\naddress: %s",
                         msg.uid,
                         attributes.latitude, attributes.longitude,
                         msg.text, msg_template)
        if old_msg_id and old_msg_id[0] == tg_dest:
            # TRANSLATORS: Flag for edited message, but cannot be edited on Telegram.
            msg_template += self._('[edited]')
            target_msg_id = target_msg_id or old_msg_id[1]
        return self.bot.send_venue(tg_dest, latitude=attributes.latitude,
                                   longitude=attributes.longitude, title=msg.text or self._("Sent a location."),
                                   address=msg_template, reply_to_message_id=target_msg_id,
                                   reply_markup=reply_markup)

    def slave_message_video(self, msg: EFBMsg, tg_dest: str, msg_template: str,
                            old_msg_id: Optional[Tuple[str, str]] = None,
                            target_msg_id: Optional[str] = None,
                            reply_markup: Optional[telegram.ReplyMarkup] = None) -> telegram.Message:
        self.bot.send_chat_action(tg_dest, telegram.ChatAction.UPLOAD_VIDEO)
        if not msg.text:
            msg.text = "sent a video."
        try:
            if old_msg_id:
                if msg.edit_media:
                    self.bot.edit_message_media(chat_id=old_msg_id[0], message_id=old_msg_id[1], media=msg.file)
                return self.bot.edit_message_caption(chat_id=old_msg_id[0], message_id=old_msg_id[1],
                                                     prefix=msg_template, caption=msg.text)
            return self.bot.send_video(tg_dest, msg.file, prefix=msg_template, caption=msg.text,
                                       reply_to_message_id=target_msg_id,
                                       reply_markup=reply_markup)
        finally:
            msg.file.close()

    def slave_message_unsupported(self, msg: EFBMsg, tg_dest: str, msg_template: str,
                                  old_msg_id: Optional[Tuple[str, str]] = None,
                                  target_msg_id: Optional[str] = None,
                                  reply_markup: Optional[telegram.ReplyMarkup] = None) -> telegram.Message:
        self.logger.debug("[%s] Sending as an unsupported message.", msg.uid)
        self.bot.send_chat_action(tg_dest, telegram.ChatAction.TYPING)

        if not old_msg_id:
            tg_msg = self.bot.send_message(tg_dest,
                                           text=msg.text, prefix=msg_template + " " + self._("(unsupported)"),
                                           reply_to_message_id=target_msg_id, reply_markup=reply_markup)
        else:
            # Cannot change reply_to_message_id when editing a message
            tg_msg = self.bot.edit_message_text(chat_id=old_msg_id[0],
                                                message_id=old_msg_id[1],
                                                text=msg.text, prefix=msg_template + " " + self._("(unsupported)"),
                                                reply_markup=reply_markup)

        self.logger.debug("[%s] Processed and sent as text message", msg.uid)
        return tg_msg

    def send_status(self, status: EFBStatus):
        if isinstance(status, EFBChatUpdates):
            self.logger.debug("Received chat updates from channel %s", status.channel)
            for i in status.removed_chats:
                self.db.delete_slave_chat_info(status.channel.channel_id, i)
            for i in itertools.chain(status.new_chats, status.modified_chats):
                chat = status.channel.get_chat(i)
                self.db.set_slave_chat_info(slave_channel_name=status.channel.channel_name,
                                            slave_channel_emoji=status.channel.channel_emoji,
                                            slave_channel_id=status.channel.channel_id,
                                            slave_chat_name=chat.chat_name,
                                            slave_chat_alias=chat.chat_alias,
                                            slave_chat_type=chat.chat_type,
                                            slave_chat_uid=chat.chat_uid,
                                            chat_object=chat)
        elif isinstance(status, EFBMemberUpdates):
            self.logger.debug("Received member updates from channel %s about group %s",
                              status.channel, status.chat_id)
            self.logger.info('Currently group member info update is ignored.')
        elif isinstance(status, EFBMessageRemoval):
            self.logger.debug("Received message removal request from channel %s on message %s",
                              status.source_channel, status.message)
            old_msg = self.db.get_msg_log(
                slave_msg_id=status.message.uid,
                slave_origin_uid=utils.chat_id_to_str(chat=status.message.chat))
            if old_msg:
                old_msg_id: Tuple[str, str] = utils.message_id_str_to_id(old_msg.master_msg_id)
                if old_msg_id[0] == ETMChat.MUTE_CHAT_ID:
                    return
                self.logger.debug("Found message to delete in Telegram: %s.%s",
                                  *old_msg_id)
                try:
                    if not self.channel.flag('prevent_message_removal'):
                        self.bot.delete_message(*old_msg_id)
                        return
                except telegram.TelegramError:
                    pass
                self.bot.send_message(chat_id=old_msg_id[0],
                                      text=self._("Message removed in remote chat."),
                                      reply_to_message_id=old_msg_id[1])
            else:
                self.logger.info('Was supposed to delete a message, '
                                 'but it does not exist in database: %s', status)

        else:
            self.logger.error('Received an unknown type of update: %s', status)

    def generate_message_template(self, msg: EFBMsg, tg_chat, multi_slaves: bool) -> str:
        msg_prefix = ""  # For group member name
        if msg.chat.chat_type == ChatType.Group:
            self.logger.debug("[%s] Message is from a group. Sender: %s", msg.uid, msg.author)
            msg_prefix = ETMChat(chat=msg.author, db=self.db).display_name

        if tg_chat and not multi_slaves:  # if singly linked
            if msg_prefix:  # if group message
                msg_template = "%s:" % msg_prefix
            else:
                if msg.chat != msg.author:
                    msg_template = "%s:" % ETMChat(chat=msg.author, db=self.db).display_name
                else:
                    msg_template = ""
        elif msg.chat.chat_type == ChatType.User:
            emoji_prefix = msg.chat.channel_emoji + Emoji.get_source_emoji(msg.chat.chat_type)
            name_prefix = ETMChat(chat=msg.chat, db=self.db).display_name
            if msg.chat != msg.author:
                name_prefix += ", %s" % ETMChat(chat=msg.author, db=self.db).display_name
            msg_template = "%s %s:" % (emoji_prefix, name_prefix)
        elif msg.chat.chat_type == ChatType.Group:
            emoji_prefix = msg.chat.channel_emoji + Emoji.get_source_emoji(msg.chat.chat_type)
            name_prefix = ETMChat(chat=msg.chat, db=self.db).display_name
            msg_template = "%s %s [%s]:" % (emoji_prefix, msg_prefix, name_prefix)
        elif msg.chat.chat_type == ChatType.System:
            emoji_prefix = msg.chat.channel_emoji + Emoji.get_source_emoji(msg.chat.chat_type)
            name_prefix = ETMChat(chat=msg.chat, db=self.db).display_name
            msg_template = "%s %s:" % (emoji_prefix, name_prefix)
        else:
            if msg.chat == msg.author:
                msg_template = "\u2753 {}:".format(msg.chat.long_name)
            else:
                msg_template = "\u2753 {0} ({1}):".format(msg.author.long_name, msg.chat.display_name)
        return msg_template
