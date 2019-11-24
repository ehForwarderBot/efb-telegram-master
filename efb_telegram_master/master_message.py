# coding=utf-8

import logging
import time
from queue import Queue
from threading import Thread
from typing import Optional, TYPE_CHECKING, Tuple

import humanize
import telegram
from telegram import Update
from telegram.ext import MessageHandler, Filters, CallbackContext
from telegram.utils.helpers import escape_markdown

from efb_telegram_master import ETMChat
from ehforwarderbot import EFBMsg, coordinator
from ehforwarderbot.constants import MsgType, ChatType
from ehforwarderbot.exceptions import EFBMessageTypeNotSupported, EFBChatNotFound, \
    EFBMessageError, EFBMessageNotFound, EFBOperationNotSupported
from ehforwarderbot.message import EFBMsgLocationAttribute
from ehforwarderbot.status import EFBMessageRemoval
from ehforwarderbot.types import ModuleID, ChatID, MessageID
from . import utils
from .chat_destination_cache import ChatDestinationCache
from .locale_mixin import LocaleMixin
from .message import ETMMsg
from .msg_type import TGMsgType
from .utils import EFBChannelChatIDStr, TelegramChatID

if TYPE_CHECKING:
    from . import TelegramChannel
    from .bot_manager import TelegramBotManager
    from .db import DatabaseManager, MsgLog
    from .chat_object_cache import ChatObjectCacheManager


class MasterMessageProcessor(LocaleMixin):
    """
    Processes messages from Telegram user and delivers to the slave channels
    """

    DELETE_FLAG = 'rm`'
    FAIL_FLAG = '__fail__'

    # Constants
    TYPE_DICT = {
        TGMsgType.Text: MsgType.Text,
        TGMsgType.Audio: MsgType.Audio,
        TGMsgType.Document: MsgType.File,
        TGMsgType.Photo: MsgType.Image,
        TGMsgType.Sticker: MsgType.Sticker,
        # TGMsgType.AnimatedSticker: MsgType.Animation,
        TGMsgType.Video: MsgType.Video,
        TGMsgType.Voice: MsgType.Audio,
        TGMsgType.Location: MsgType.Location,
        TGMsgType.Venue: MsgType.Location,
        TGMsgType.Animation: MsgType.Animation,
        TGMsgType.Contact: MsgType.Text
    }

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        self.bot: 'TelegramBotManager' = channel.bot_manager
        self.db: 'DatabaseManager' = channel.db
        self.chat_dest_cache: ChatDestinationCache = channel.chat_dest_cache
        self.chat_manager: 'ChatObjectCacheManager' = channel.chat_manager
        self.bot.dispatcher.add_handler(MessageHandler(
            (Filters.text | Filters.photo | Filters.sticker | Filters.document |
             Filters.venue | Filters.location | Filters.audio | Filters.voice | Filters.video) &
            Filters.update,
            self.enqueue_message
        ))
        self.logger: logging.Logger = logging.getLogger(__name__)

        self.channel_id: ModuleID = self.channel.channel_id

        if self.channel.flag("animated_stickers"):
            self.TYPE_DICT[TGMsgType.AnimatedSticker] = MsgType.Animation

        self.message_queue: 'Queue[Optional[Tuple[Update, CallbackContext]]]' = Queue()
        self.message_worker_thread = Thread(target=self.message_worker, name="ETM master messages worker thraed")
        self.message_worker_thread.start()

    def message_worker(self):
        # TODO: Implement a per-chat queue to prevent one message blocking all others?
        while True:
            content = self.message_queue.get()
            if content is None:
                self.message_queue.task_done()
                return
            update, context = content
            self.msg(update, context)
            self.message_queue.task_done()

    def stop_worker(self):
        if not self.message_worker_thread.is_alive():
            return
        self.message_queue.put(None)
        self.message_worker_thread.join()

    def enqueue_message(self, update: Update, context: CallbackContext):
        self.message_queue.put((update, context))

    def msg(self, update: Update, context: CallbackContext):
        """
        Process, wrap and dispatch messages from user.
        """

        message: telegram.Message = update.effective_message

        self.logger.debug("Received message from Telegram: %s", message.to_dict())
        multi_slaves = False

        if message.chat.id != message.from_user.id:  # from group
            assocs = self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(self.channel_id, message.chat.id))
            if len(assocs) > 1:
                multi_slaves = True

        reply_to = bool(getattr(message, "reply_to_message", None))
        private_chat = message.chat.id == message.from_user.id

        if (private_chat or multi_slaves) and not reply_to and not self.chat_dest_cache.get(message.chat.id):
            # If
            # 1. the Telegram chat is multi-linked, and
            # 2. the message doesn't have a quoted reply, and
            # 3. there is not cached destination
            candidates = self.db.get_recent_slave_chats(message.chat.id, limit=5) or \
                         self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(self.channel_id, message.chat.id))[:5]
            if candidates:
                tg_err_msg = message.reply_text(self._("Error: No recipient specified.\n"
                                                       "Please reply to a previous message. (MS01)"), quote=True)
                self.channel.chat_binding.register_suggestions(update, candidates,
                                                               update.effective_chat.id, tg_err_msg.message_id)

            else:
                message.reply_text(self._("Error: No recipient specified.\n"
                                          "Please reply to a previous message. (MS02)"), quote=True)
        else:
            return self.process_telegram_message(update, context)

    def process_telegram_message(self, update: Update, context: CallbackContext,
                                 channel_id: Optional[ModuleID] = None,
                                 chat_id: Optional[ChatID] = None,
                                 target_msg: Optional[utils.TgChatMsgIDStr] = None):
        """
        Process messages came from Telegram.

        Args:
            update: Telegram message update
            context: PTB update context
            channel_id: Slave channel ID if specified
            chat_id: Slave chat ID if specified
            target_msg: Target slave message if specified
        """
        target: Optional[EFBChannelChatIDStr] = None
        target_channel: Optional[ModuleID] = None
        target_log: Optional['MsgLog'] = None
        # Message ID for logging
        message_id = utils.message_id_to_str(update=update)

        multi_slaves: bool = False
        destination: Optional[EFBChannelChatIDStr] = None
        slave_msg: Optional[EFBMsg] = None

        message: telegram.Message = update.effective_message

        edited = bool(update.edited_message or update.edited_channel_post)
        self.logger.debug('[%s] Message is edited: %s, %s',
                          message_id, edited, message.edit_date)

        private_chat = update.effective_chat.type == telegram.Chat.PRIVATE

        if not private_chat:  # from group
            linked_chats = self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(
                self.channel_id, update.effective_chat.id))
            if len(linked_chats) == 1:
                destination = linked_chats[0]
            elif len(linked_chats) > 1:
                multi_slaves = True

        reply_to = bool(getattr(message, "reply_to_message", None))

        # Process predefined target (slave) chat.
        cached_dest = self.chat_dest_cache.get(message.chat.id)
        if channel_id and chat_id:
            destination = utils.chat_id_to_str(channel_id, chat_id)
            if target_msg is not None:
                target_log = self.db.get_msg_log(master_msg_id=target_msg)
                if target_log:
                    target = target_log.slave_origin_uid
                    if target is not None:
                        target_channel, target_uid = utils.chat_id_str_to_id(target)
                else:
                    return self.bot.reply_error(update,
                                                self._("Message is not found in database. "
                                                       "Please try with another message. (UC07)"))
        elif private_chat:
            if reply_to:
                dest_msg = self.db.get_msg_log(master_msg_id=utils.message_id_to_str(
                    message.reply_to_message.chat.id,
                    message.reply_to_message.message_id))
                if dest_msg:
                    destination = dest_msg.slave_origin_uid
                    self.chat_dest_cache.set(message.chat.id, dest_msg.slave_origin_uid)
                else:
                    return self.bot.reply_error(update,
                                                self._("Message is not found in database. "
                                                       "Please try with another one. (UC03)"))
            elif cached_dest:
                destination = cached_dest
                self._send_cached_chat_warning(update, message.chat.id, cached_dest)
            else:
                return self.bot.reply_error(update,
                                            self._("Please reply to an incoming message. (UC04)"))
        else:  # group chat
            if multi_slaves:
                if reply_to:
                    dest_msg = self.db.get_msg_log(master_msg_id=utils.message_id_to_str(
                        message.reply_to_message.chat.id,
                        message.reply_to_message.message_id))
                    if dest_msg:
                        destination = dest_msg.slave_origin_uid
                        assert destination is not None
                        self.chat_dest_cache.set(message.chat.id, destination)
                    else:
                        return self.bot.reply_error(update,
                                                    self._("Message is not found in database. "
                                                           "Please try with another one. (UC05)"))
                elif cached_dest:
                    destination = cached_dest
                    self._send_cached_chat_warning(update, message.chat.id, cached_dest)
                else:
                    return self.bot.reply_error(update,
                                                self._("This group is linked to multiple remote chats. "
                                                       "Please reply to an incoming message. "
                                                       "To unlink all remote chats, please send /unlink_all . (UC06)"))
            elif destination:
                if reply_to:
                    target_log = \
                        self.db.get_msg_log(master_msg_id=utils.message_id_to_str(
                            message.reply_to_message.chat.id,
                            message.reply_to_message.message_id))
                    if target_log:
                        target = target_log.slave_origin_uid
                        if target is not None:
                            target_channel, target_uid = utils.chat_id_str_to_id(target)
                    else:
                        return self.bot.reply_error(update,
                                                    self._("Message is not found in database. "
                                                           "Please try with another message. (UC07)"))
            else:
                return self.bot.reply_error(update,
                                            self._("This group is not linked to any chat. (UC06)"))

        self.logger.debug("[%s] Telegram received. From private chat: %s; Group has multiple linked chats: %s; "
                          "Message replied to another message: %s", message_id, private_chat, multi_slaves, reply_to)
        self.logger.debug("[%s] Destination chat = %s", message_id, destination)
        assert destination is not None
        channel, uid = utils.chat_id_str_to_id(destination)
        if channel not in coordinator.slaves:
            return self.bot.reply_error(update, self._("Internal error: Slave channel “{0}” not found.").format(channel))

        m = ETMMsg()
        log_message = True
        try:
            m.uid = MessageID(message_id)
            m.put_telegram_file(message)
            mtype = m.type_telegram
            # Chat and author related stuff
            m.author = self.chat_manager.self
            m.chat = self.chat_manager.get_chat(channel, uid)
            if not m.chat:
                # Chat not found anyway, build a fake object
                m.chat = ETMChat(db=self.db, channel=coordinator.slaves[channel])
                m.chat.chat_uid = m.chat.chat_name = uid

            m.deliver_to = coordinator.slaves[channel]
            if target and target_log is not None and target_channel == channel:
                if target_log.pickle:
                    trgt_msg: ETMMsg = ETMMsg.unpickle(target_log.pickle, self.chat_manager)
                    trgt_msg.target = None
                else:
                    trgt_msg = ETMMsg()
                    trgt_msg.type = MsgType.Text
                    trgt_msg.text = target_log.text
                    trgt_msg.uid = target_log.slave_message_id

                    target_channel, trgt_chat = utils.chat_id_str_to_id(target_log.slave_origin_uid)
                    trgt_msg.chat = self.chat_manager.get_chat(target_channel, trgt_chat)
                    if not m.chat:
                        # Chat not found anyway, build a fake object
                        trgt_msg.chat = ETMChat(db=self.db, channel=coordinator.slaves[target_channel])
                        trgt_msg.chat.chat_name = target_log.slave_origin_display_name
                        trgt_msg.chat.chat_uid = trgt_chat
                    if target_log.slave_member_uid:
                        trgt_msg.author = self.chat_manager.get_chat(target_channel, target_log.slave_member_uid, trgt_chat)
                        if not trgt_msg.author:
                            # Chat not found anyway, build a fake object
                            trgt_msg.author = ETMChat(db=self.db, channel=coordinator.slaves[target_channel])
                            trgt_msg.author.chat_name = target_log.slave_member_display_name
                            trgt_msg.author.chat_uid = target_log.slave_member_uid
                    elif target_log.sent_to == 'master':
                        trgt_msg.author = trgt_msg.chat
                    else:
                        trgt_msg.author = self.chat_manager.self
                m.target = trgt_msg

                self.logger.debug("[%s] This message replies to another message of the same channel.\n"
                                  "Chat ID: %s; Message ID: %s.", message_id, trgt_msg.chat.chat_uid, trgt_msg.uid)
            # Type specific stuff
            self.logger.debug("[%s] Message type from Telegram: %s", message_id, mtype)

            if self.TYPE_DICT.get(mtype, None):
                m.type = self.TYPE_DICT[mtype]
                self.logger.debug("[%s] EFB message type: %s", message_id, mtype)
            else:
                self.logger.info("[%s] Message type %s is not supported by ETM", message_id, mtype)
                raise EFBMessageTypeNotSupported(self._("Message type {} is not supported by ETM.").format(mtype.name))

            if m.type not in coordinator.slaves[channel].supported_message_types:
                self.logger.info("[%s] Message type %s is not supported by channel %s",
                                 message_id, m.type.name, channel)
                raise EFBMessageTypeNotSupported(self._("Message type {0} is not supported by channel {1}.")
                                                 .format(m.type.name, coordinator.slaves[channel].channel_name))

            # Parse message text and caption to markdown
            msg_md_text = message.text and message.text_markdown
            if msg_md_text and msg_md_text == escape_markdown(message.text):
                msg_md_text = message.text
            msg_md_text = msg_md_text or ""

            msg_md_caption = message.caption and message.caption_markdown
            if msg_md_caption and msg_md_caption == escape_markdown(message.caption):
                msg_md_caption = message.caption
            msg_md_caption = msg_md_caption or ""

            # Flag for edited message
            if edited:
                m.edit = True
                text = msg_md_text or msg_md_caption
                msg_log = self.db.get_msg_log(master_msg_id=utils.message_id_to_str(update=update))
                if not msg_log or msg_log == self.FAIL_FLAG:
                    raise EFBMessageNotFound()
                m.uid = msg_log.slave_message_id
                if text.startswith(self.DELETE_FLAG):
                    coordinator.send_status(EFBMessageRemoval(
                        source_channel=self.channel,
                        destination_channel=coordinator.slaves[channel],
                        message=m
                    ))
                    self.db.delete_msg_log(master_msg_id=utils.message_id_to_str(update=update))
                    log_message = False
                    return
                self.logger.debug('[%s] Message is edited (%s)', m.uid, m.edit)

            # Enclose message as an EFBMsg object by message type.
            if mtype == TGMsgType.Text:
                m.text = msg_md_text
            elif mtype == TGMsgType.Photo:
                m.text = msg_md_caption
                m.mime = "image/jpeg"
                self._check_file_download(message.photo[-1])
            elif mtype in (TGMsgType.Sticker, TGMsgType.AnimatedSticker):
                # Convert WebP to the more common PNG
                m.text = ""
                self._check_file_download(message.sticker)
            elif mtype == TGMsgType.Animation:
                m.text = ""
                self.logger.debug("[%s] Telegram message is a \"Telegram GIF\".", message_id)
                m.filename = getattr(message.document, "file_name", None) or None
                m.mime = message.document.mime_type or m.mime
            elif mtype == TGMsgType.Document:
                m.text = msg_md_caption
                self.logger.debug("[%s] Telegram message type is document.", message_id)
                m.filename = getattr(message.document, "file_name", None) or None
                m.mime = message.document.mime_type
                self._check_file_download(message.document)
            elif mtype == TGMsgType.Video:
                m.text = msg_md_caption
                m.mime = message.video.mime_type
                self._check_file_download(message.video)
            elif mtype == TGMsgType.Audio:
                m.text = "%s - %s\n%s" % (
                    message.audio.title, message.audio.performer, msg_md_caption)
                m.mime = message.audio.mime_type
                self._check_file_download(message.audio)
            elif mtype == TGMsgType.Voice:
                m.text = msg_md_caption
                m.mime = message.voice.mime_type
                self._check_file_download(message.voice)
            elif mtype == TGMsgType.Location:
                # TRANSLATORS: Message body text for location messages.
                m.text = self._("Location")
                m.attributes = EFBMsgLocationAttribute(
                    message.location.latitude,
                    message.location.longitude
                )
            elif mtype == TGMsgType.Venue:
                m.text = message.location.title + "\n" + message.location.adderss
                m.attributes = EFBMsgLocationAttribute(
                    message.venue.location.latitude,
                    message.venue.location.longitude
                )
            elif mtype == TGMsgType.Contact:
                contact: telegram.Contact = message.contact
                m.text = self._("Shared a contact: {first_name} {last_name}\n{phone_number}").format(
                    first_name=contact.first_name, last_name=contact.last_name, phone_number=contact.phone_number
                )
            else:
                raise EFBMessageTypeNotSupported(self._("Message type {0} is not supported.").format(mtype))

            slave_msg = coordinator.send_message(m)
        except EFBChatNotFound as e:
            self.bot.reply_error(update, e.args[0] or self._("Chat is not found."))
        except EFBMessageTypeNotSupported as e:
            self.bot.reply_error(update, e.args[0] or self._("Message type is not supported."))
        except EFBOperationNotSupported as e:
            self.bot.reply_error(update, self._("Message editing is not supported.\n\n{!s}".format(e)))
        except Exception as e:
            self.bot.reply_error(update, self._("Message is not sent.\n\n{!r}".format(e)))
            self.logger.exception("Message is not sent. (update: %s)", update)
        finally:
            if log_message:
                pickled_msg = m.pickle(self.db)
                self.logger.debug("[%s] Pickle size: %s", message_id, len(pickled_msg))
                msg_log_d = {
                    "master_msg_id": utils.message_id_to_str(update=update),
                    "text": m.text or "Sent a %s" % m.type.name,
                    "slave_origin_uid": utils.chat_id_to_str(chat=m.chat),
                    "slave_origin_display_name": "__chat__",
                    "msg_type": m.type.name,
                    "sent_to": "slave",
                    "slave_message_id": None if m.edit else "%s.%s" % (self.FAIL_FLAG, int(time.time())),
                    # Overwritten later if slave message ID exists
                    "update": m.edit,
                    "media_type": m.type_telegram.value,
                    "file_id": m.file_id,
                    "mime": m.mime,
                    "pickle": pickled_msg
                }

                if slave_msg:
                    msg_log_d['slave_message_id'] = slave_msg.uid
                # self.db.add_msg_log(**msg_log_d)
                self.db.add_task(self.db.add_msg_log, tuple(), msg_log_d)
                if m.file:
                    m.file.close()

    def _send_cached_chat_warning(self, update: telegram.Update,
                                  cache_key: TelegramChatID,
                                  cached_dest: EFBChannelChatIDStr):
        """Send warning about cached chat."""
        if self.channel.flag("send_to_last_chat") != "warn":
            return

        # Warn the user once every timeout threshold per Telegram group
        if not self.chat_dest_cache.is_warned(cache_key):
            self.chat_dest_cache.set_warned(cache_key)

            dest_module, dest_chat_id = utils.chat_id_str_to_id(cached_dest)
            dest_chat = self.chat_manager.get_chat(dest_module, dest_chat_id)
            if dest_chat:
                dest_name = dest_chat.full_name
            else:
                dest_name = cached_dest
            update.message.reply_text(
                self._(
                    "This message is sent to “{dest}” with quick reply feature.\n"
                    "\n"
                    "Learn more about how this works, how to turn off this feature, "
                    "and how to stop this warning at {docs}."
                ).format(dest=dest_name,
                         docs="https://github.com/blueset/efb-telegram-master/"),
                quote=True,
                disable_web_page_preview=True)

    def _check_file_download(self, file_obj: telegram.File):
        """
        Check if the file is available for download..

        Args:
            file_obj (telegram.File): PTB file object

        Raises:
            EFBMessageError: When file exceeds the maximum download size.
        """
        size = getattr(file_obj, "file_size", None)
        if size and size > telegram.constants.MAX_FILESIZE_DOWNLOAD:
            size_str = humanize.naturalsize(size, binary=True)
            max_size_str = humanize.naturalsize(telegram.constants.MAX_FILESIZE_DOWNLOAD, binary=True)
            raise EFBMessageError(
                self._("Attachment is too large ({size}). Maximum allowed by Telegram is {max_size}. (AT01)").format(
                    size=size_str, max_size=max_size_str))
