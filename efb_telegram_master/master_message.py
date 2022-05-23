# coding=utf-8

import logging
from pickle import UnpicklingError
from queue import Queue
from threading import Thread
from typing import Optional, TYPE_CHECKING, Tuple, Any

import humanize
from telegram import Update, Message, Chat, TelegramError, Contact, File
from telegram.constants import MAX_FILESIZE_DOWNLOAD
from telegram.ext import MessageHandler, Filters, CallbackContext, CommandHandler
from telegram.utils.helpers import escape_markdown

from ehforwarderbot import coordinator
from ehforwarderbot.constants import MsgType
from ehforwarderbot.exceptions import EFBMessageTypeNotSupported, EFBChatNotFound, \
    EFBMessageError, EFBOperationNotSupported, EFBException
from ehforwarderbot.message import LocationAttribute
from ehforwarderbot.status import MessageRemoval
from ehforwarderbot.types import ModuleID, MessageID, ChatID
from . import utils
from .chat_destination_cache import ChatDestinationCache
from .locale_mixin import LocaleMixin
from .message import ETMMsg
from .msg_type import TGMsgType, get_msg_type
from .utils import EFBChannelChatIDStr, TelegramChatID, TelegramMessageID

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

    # Constants
    TYPE_DICT = {
        TGMsgType.Text: MsgType.Text,
        TGMsgType.Audio: MsgType.File,
        TGMsgType.Document: MsgType.File,
        TGMsgType.Photo: MsgType.Image,
        TGMsgType.Sticker: MsgType.Sticker,
        # TGMsgType.AnimatedSticker: MsgType.Animation,
        TGMsgType.VideoSticker: MsgType.Animation,
        TGMsgType.Video: MsgType.Video,
        TGMsgType.VideoNote: MsgType.Video,
        TGMsgType.Voice: MsgType.Voice,
        TGMsgType.Location: MsgType.Location,
        TGMsgType.Venue: MsgType.Location,
        TGMsgType.Animation: MsgType.Animation,
        TGMsgType.Contact: MsgType.Text,
        TGMsgType.Dice: MsgType.Text,
    }

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        self.bot: 'TelegramBotManager' = channel.bot_manager
        self.db: 'DatabaseManager' = channel.db
        self.chat_dest_cache: ChatDestinationCache = channel.chat_dest_cache
        self.chat_manager: 'ChatObjectCacheManager' = channel.chat_manager

        self.bot.dispatcher.add_handler(CommandHandler("rm", self.delete_message))

        self.bot.dispatcher.add_handler(MessageHandler(
            (Filters.text | Filters.photo | Filters.sticker | Filters.document |
             Filters.venue | Filters.location | Filters.audio | Filters.voice |
             Filters.video | Filters.contact | Filters.video_note | Filters.dice) &
            Filters.update,
            self.enqueue_message
        ))
        self.bot.dispatcher.add_handler(MessageHandler(
            (Filters.passport_data | Filters.invoice | Filters.game | Filters.successful_payment |
             Filters.poll) & Filters.update,
            self.unsupported_message
        ))
        self.logger: logging.Logger = logging.getLogger(__name__)

        self.channel_id: ModuleID = self.channel.channel_id

        if self.channel.flag("animated_stickers"):
            self.TYPE_DICT[TGMsgType.AnimatedSticker] = MsgType.Animation

        self.message_queue: 'Queue[Optional[Tuple[Update, CallbackContext]]]' = Queue()
        self.message_worker_thread = Thread(target=self.message_worker, name="ETM master messages worker thread")
        self.message_worker_thread.start()

    def message_worker(self):
        # TODO: Implement a per-chat queue to prevent one message blocking all others?
        while True:
            content = self.message_queue.get()
            if content is None:
                self.message_queue.task_done()
                return
            update, context = content
            try:
                self.msg(update, context)
            except Exception as e:
                self.logger.exception(
                    "Error [%r] occurred while processing update %s.", e, update)
                if update.effective_message:
                    update.effective_message.reply_text(
                        self._("Unknown error has occurred while "
                               "trying to process this message. See log for "
                               "details.\n\n{error!r}").format(error=e))
            finally:
                self.message_queue.task_done()

    def stop_worker(self):
        if not self.message_worker_thread.is_alive():
            return
        self.message_queue.put(None)
        self.message_worker_thread.join()

    def enqueue_message(self, update: Update, context: CallbackContext):
        assert isinstance(update, Update)

        self.message_queue.put((update, context))
        if not self.message_worker_thread.is_alive():
            if update.effective_message:
                update.effective_message.reply_text(
                    self._(
                        "ETM message worker is not running due to unforeseen reason. This might be a bug. Please see log for details."))

    def msg(self, update: Update, context: CallbackContext):
        """
        Process, wrap and dispatch messages from user.
        """
        assert isinstance(update, Update)
        assert update.effective_message
        assert update.effective_chat

        message: Message = update.effective_message
        mid = utils.message_id_to_str(update=update)

        self.logger.debug("[%s] Received message from Telegram: %s", mid, message.to_dict())

        destination = None
        edited = None
        quote = False

        if update.edited_message or update.edited_channel_post:
            self.logger.debug('[%s] Message is edited: %s', mid, message.edit_date)
            msg_log = self.db.get_msg_log(master_msg_id=utils.message_id_to_str(update=update))
            if not msg_log or msg_log.slave_message_id == self.db.FAIL_FLAG:
                message.reply_text(self._("Error: This message cannot be edited, and thus is not sent. (ME01)"), quote=True)
                return
            destination = msg_log.slave_origin_uid
            edited = msg_log
            quote = msg_log.build_etm_msg(self.chat_manager).target is not None

        if destination is None:
            destination = self.get_singly_linked_chat_id_str(update.effective_chat)
            if destination:
                # if the chat is singly-linked
                quote = message.reply_to_message is not None
                self.logger.debug("[%s] Chat %s is singly-linked to %s", mid, message.chat, destination)

        if destination is None:  # not singly linked
            quote = False
            self.logger.debug("[%s] Chat %s is not singly-linked", mid, update.effective_chat)
            reply_to = message.reply_to_message
            cached_dest = self.chat_dest_cache.get(str(message.chat.id))
            if reply_to:
                self.logger.debug("[%s] Message is quote-replying to %s", mid, reply_to)
                dest_msg = self.db.get_msg_log(
                    master_msg_id=utils.message_id_to_str(
                        TelegramChatID(reply_to.chat.id),
                        TelegramMessageID(reply_to.message_id)
                    )
                )
                if dest_msg:
                    destination = dest_msg.slave_origin_uid
                    self.chat_dest_cache.set(str(message.chat.id), destination)
                    self.logger.debug("[%s] Quoted message is found in database with destination: %s", mid, destination)
            elif cached_dest:
                self.logger.debug("[%s] Cached destination found: %s", mid, cached_dest)
                destination = cached_dest
                self._send_cached_chat_warning(update, TelegramChatID(message.chat.id), cached_dest)

        self.logger.debug("[%s] Destination chat = %s", mid, destination)

        if destination is None:
            self.logger.debug("[%s] Destination is not found for this message", mid)
            candidates = (
                 self.db.get_recent_slave_chats(TelegramChatID(message.chat.id), limit=5) or
                 self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(self.channel_id, ChatID(str(message.chat.id))))[:5]
            )
            if candidates:
                self.logger.debug("[%s] Candidate suggestions are found for this message: %s", mid, candidates)
                tg_err_msg = message.reply_text(self._("Error: No recipient specified.\n"
                                                       "Please reply to a previous message. (MS01)"), quote=True)
                self.channel.chat_binding.register_suggestions(update, candidates,
                                                               TelegramChatID(update.effective_chat.id),
                                                               TelegramMessageID(tg_err_msg.message_id))
            else:
                self.logger.debug("[%s] Candidate suggestions not found, give up.", mid)
                message.reply_text(self._("Error: No recipient specified.\n"
                                          "Please reply to a previous message. (MS02)"), quote=True)
        else:
            return self.process_telegram_message(update, context, destination, quote=quote, edited=edited)

    def get_singly_linked_chat_id_str(self, chat: Chat) -> Optional[EFBChannelChatIDStr]:
        """Return the singly-linked remote chat if available.
        Otherwise return None.
        """
        master_chat_uid = utils.chat_id_to_str(self.channel_id, ChatID(str(chat.id)))
        chats = self.db.get_chat_assoc(master_uid=master_chat_uid)
        if len(chats) == 1:
            return chats[0]
        return None

    def process_telegram_message(self, update: Update, context: CallbackContext,
                                 destination: EFBChannelChatIDStr, quote: bool = False,
                                 edited: Optional["MsgLog"] = None):
        """
        Process messages came from Telegram.

        Args:
            update: Telegram message update
            context: PTB update context
            destination: Destination of the message specified.
            quote: If the message shall quote another one
            edited: old message log entry if the message can be edited.
        """
        assert isinstance(update, Update)
        assert update.effective_message

        # Message ID for logging
        message_id = utils.message_id_to_str(update=update)

        message: Message = update.effective_message

        channel, uid, gid = utils.chat_id_str_to_id(destination)
        if channel not in coordinator.slaves:
            return self.bot.reply_error(update,
                                        self._("Internal error: Slave channel “{0}” not found.").format(channel))

        m = ETMMsg()
        log_message = True
        try:
            m.uid = MessageID(message_id)
            # Store Telegram message type
            m.type_telegram = mtype = get_msg_type(message)

            if self.TYPE_DICT.get(mtype, None):
                m.type = self.TYPE_DICT[mtype]
                self.logger.debug("[%s] EFB message type: %s", message_id, mtype)
            else:
                self.logger.info("[%s] Message type %s is not supported by ETM", message_id, mtype)
                log_message = False
                raise EFBMessageTypeNotSupported(
                    self._("{type_name} messages are not supported by EFB Telegram Master channel.")
                        .format(type_name=mtype.name))

            m.put_telegram_file(message)
            # Chat and author related stuff
            m.chat = self.chat_manager.get_chat(channel, uid, build_dummy=True)
            m.author = m.chat.self or m.chat.add_self()

            m.deliver_to = coordinator.slaves[channel]

            if quote:
                self.attach_target_message(message, m, channel)
            # Type specific stuff
            self.logger.debug("[%s] Message type from Telegram: %s", message_id, mtype)

            if m.type not in coordinator.slaves[channel].supported_message_types:
                self.logger.info("[%s] Message type %s is not supported by channel %s",
                                 message_id, m.type.name, channel)
                raise EFBMessageTypeNotSupported(
                    self._("{type_name} messages are not supported by slave channel {channel_name}.")
                        .format(type_name=m.type.name,
                                channel_name=coordinator.slaves[channel].channel_name))

            # Convert message text and caption to markdown
            # Keep original text if what *_markdown_2 did is just escaping the text.
            msg_md_text = message.text and message.text_markdown_v2 or ""
            if message.text and msg_md_text == escape_markdown(message.text, version=2):
                msg_md_text = message.text
            msg_md_text = msg_md_text or ""

            msg_md_caption = message.caption and message.caption_markdown_v2 or ""
            if message.caption and msg_md_caption == escape_markdown(message.caption, version=2):
                msg_md_caption = message.caption
            msg_md_caption = msg_md_caption or ""

            # Flag for edited message
            if edited:
                m.edit = True
                text = msg_md_text or msg_md_caption

                m.uid = edited.slave_message_id
                if text.startswith(self.DELETE_FLAG):
                    coordinator.send_status(MessageRemoval(
                        source_channel=self.channel,
                        destination_channel=coordinator.slaves[channel],
                        message=m
                    ))
                    if not self.channel.flag('prevent_message_removal'):
                        try:
                            message.delete()
                        except TelegramError:
                            message.reply_text(self._("Message is removed in remote chat."))
                    else:
                        message.reply_text(self._("Message is removed in remote chat."))
                    log_message = False
                    return
                self.logger.debug('[%s] Message is edited (%s)', m.uid, m.edit)
                if m.file_unique_id and m.file_unique_id != edited.file_unique_id:
                    self.logger.debug("[%s] Message media is edited (%s -> %s)", m.uid, edited.file_unique_id, m.file_unique_id)
                    m.edit_media = True

            # Enclose message as an Message object by message type.
            if mtype is TGMsgType.Text:
                m.text = msg_md_text
            elif mtype is TGMsgType.Photo:
                assert message.photo
                m.text = msg_md_caption
                m.mime = "image/jpeg"
                self._check_file_download(message.photo[-1])
            elif mtype in (TGMsgType.Sticker, TGMsgType.AnimatedSticker):
                assert message.sticker
                # Convert WebP to the more common PNG
                m.text = ""
                self._check_file_download(message.sticker)
            elif mtype is TGMsgType.Animation:
                assert message.animation
                m.text = msg_md_caption
                self.logger.debug("[%s] Telegram message is a \"Telegram GIF\".", message_id)
                m_filename = getattr(message.animation, "file_name", None) or None
                if m_filename and not m_filename.lower().endswith(".gif"):
                    m_filename += ".gif"
                m.filename = m_filename
                m.mime = message.animation.mime_type or m.mime
            elif mtype is TGMsgType.Document:
                assert message.document
                m.text = msg_md_caption
                self.logger.debug("[%s] Telegram message type is document.", message_id)
                m.filename = getattr(message.document, "file_name", None) or None
                m.mime = message.document.mime_type
                self._check_file_download(message.document)
            elif mtype is TGMsgType.Video:
                assert message.video
                m.text = msg_md_caption
                m.mime = message.video.mime_type
                self._check_file_download(message.video)
            elif mtype is TGMsgType.VideoNote:
                assert message.video_note
                m.text = msg_md_caption
                self._check_file_download(message.video_note)
            elif mtype is TGMsgType.Audio:
                assert message.audio
                m.text = "%s - %s\n%s" % (
                    message.audio.title, message.audio.performer, msg_md_caption)
                m.mime = message.audio.mime_type
                self._check_file_download(message.audio)
            elif mtype is TGMsgType.Voice:
                assert message.voice
                m.text = msg_md_caption
                m.mime = message.voice.mime_type
                self._check_file_download(message.voice)
            elif mtype is TGMsgType.Location:
                # TRANSLATORS: Message body text for location messages.
                assert message.location
                m.text = self._("Location")
                m.attributes = LocationAttribute(
                    message.location.latitude,
                    message.location.longitude
                )
            elif mtype is TGMsgType.Venue:
                assert message.venue
                m.text = f"📍 {message.venue.title}\n{message.venue.address}"
                m.attributes = LocationAttribute(
                    message.venue.location.latitude,
                    message.venue.location.longitude
                )
            elif mtype is TGMsgType.Contact:
                assert message.contact
                contact: Contact = message.contact
                m.text = self._("Shared a contact: {first_name} {last_name}\n{phone_number}").format(
                    first_name=contact.first_name, last_name=contact.last_name, phone_number=contact.phone_number
                )
            elif mtype is TGMsgType.Dice:
                assert message.dice
                m.text = f"{message.dice.emoji} = {message.dice.value}"
            else:
                raise EFBMessageTypeNotSupported(self._("Message type {0} is not supported.").format(mtype.name))

            slave_msg = coordinator.send_message(m)
            if slave_msg and slave_msg.uid:
                m.uid = slave_msg.uid
            else:
                m.uid = None
        except EFBChatNotFound as e:
            self.bot.reply_error(update, e.args[0] or self._("Chat is not found."))
        except EFBMessageTypeNotSupported as e:
            self.bot.reply_error(update, e.args[0] or self._("Message type is not supported."))
        except EFBOperationNotSupported as e:
            self.bot.reply_error(update,
                                 self._("Message editing is not supported.\n\n{exception!s}".format(exception=e)))
        except EFBException as e:
            self.bot.reply_error(update, self._("Message is not sent.\n\n{exception!s}".format(exception=e)))
            self.logger.exception("Message is not sent. (update: %s, exception: %s)", update, e)
        except Exception as e:
            self.bot.reply_error(update, self._("Message is not sent.\n\n{exception!r}".format(exception=e)))
            self.logger.exception("Message is not sent. (update: %s, exception: %s)", update, e)
        finally:
            if log_message:
                self.db.add_or_update_message_log(m, update.effective_message)
                if m.file:
                    m.file.close()

    def attach_target_message(self, tg_msg: Message, etm_msg: ETMMsg, channel: ModuleID) -> ETMMsg:
        """Attach target message to an ETM message if possible"""
        reply_to = tg_msg.reply_to_message
        assert reply_to

        target_log = self.db.get_msg_log(
            master_msg_id=utils.message_id_to_str(
                TelegramChatID(reply_to.chat.id), TelegramMessageID(reply_to.message_id)))
        if not target_log or not target_log.slave_origin_uid:
            self.logger.error("[%s] Quoted message not found in database, give up quoting.",
                              tg_msg.message_id)
            return etm_msg
        target_channel, _, _ = utils.chat_id_str_to_id(target_log.slave_origin_uid)
        if target_channel != channel:
            self.logger.error("[%s] Quoted message is sent to channel %s, but this message is sent to %s, give up quoting.",
                              tg_msg.message_id, target_channel, channel)
            return etm_msg
        target_msg: ETMMsg = target_log.build_etm_msg(self.chat_manager, recur=False)
        target_msg.target = None
        etm_msg.target = target_msg

        self.logger.debug("[%s] This message replies to another message of the same channel.\n"
                          "Chat ID: %s; Message ID: %s.",
                          tg_msg.message_id, target_msg.chat.uid, target_msg.uid)
        return etm_msg

    def _send_cached_chat_warning(self, update: Update,
                                  cache_key: TelegramChatID,
                                  cached_dest: EFBChannelChatIDStr):
        """Send warning about cached chat."""
        assert isinstance(update, Update)
        assert update.effective_message

        if self.channel.flag("send_to_last_chat") != "warn":
            return

        # Warn the user once every timeout threshold per Telegram group
        if not self.chat_dest_cache.is_warned(str(cache_key)):
            self.chat_dest_cache.set_warned(str(cache_key))

            dest_module, dest_chat_id, _ = utils.chat_id_str_to_id(cached_dest)
            dest_chat = self.chat_manager.get_chat(dest_module, dest_chat_id)
            if dest_chat:
                dest_name = dest_chat.full_name
            else:
                dest_name = cached_dest
            update.effective_message.reply_text(
                self._(
                    "This message is sent to “{dest}” with quick reply feature.\n"
                    "\n"
                    "Learn more about how this works, how to turn this feature off, "
                    "and how to stop this warning at {docs}."
                ).format(dest=dest_name,
                         docs="https://etm.1a23.studio/"),
                quote=True,
                disable_web_page_preview=True)

    def _check_file_download(self, file_obj: Any):
        """
        Check if the file is available for download.

        Args:
            file_obj (telegram.File): PTB file object

        Raises:
            EFBMessageError: When file exceeds the maximum download size.
        """
        size = getattr(file_obj, "file_size", None)
        if size and not self.channel.flag("local_tdlib_api")\
                and size > MAX_FILESIZE_DOWNLOAD:
            size_str = humanize.naturalsize(size)
            max_size_str = humanize.naturalsize(MAX_FILESIZE_DOWNLOAD)
            raise EFBMessageError(
                self._(
                    "Attachment is too large ({size}). Maximum allowed by Telegram Bot API is {max_size}. (AT01)").format(
                    size=size_str, max_size=max_size_str))

    def delete_message(self, update: Update, context: CallbackContext):
        """Remove an arbitrary message from its remote chat.
        Triggered by command ``/rm``.
        """
        assert isinstance(update, Update)
        assert update.message

        message: Message = update.message
        if message.reply_to_message is None:
            return self.bot.reply_error(update, self._(
                "Reply /rm to a message to remove it from its remote chat."
            ))
        reply: Message = message.reply_to_message
        msg_log = self.db.get_msg_log(
            master_msg_id=utils.message_id_to_str(
                chat_id=TelegramChatID(reply.chat_id),
                message_id=TelegramMessageID(reply.message_id)))
        if not msg_log or msg_log.slave_member_uid == self.db.FAIL_FLAG:
            return self.bot.reply_error(update, self._(
                "This message is not found in ETM database. You cannot remove it from its remote chat."
            ))
        try:
            etm_msg: ETMMsg = msg_log.build_etm_msg(self.chat_manager)
        except UnpicklingError:
            return self.bot.reply_error(update, self._(
                "This message is not found in ETM database. You cannot remove it from its remote chat."
            ))
        dest_channel = coordinator.slaves.get(etm_msg.chat.module_id, None)
        if dest_channel is None:
            return self.bot.reply_error(update, self._(
                "Module of this message ({module_id}) could not be found, or is not a slave channel."
            ).format(module_id=etm_msg.chat.module_id))
        # noinspection PyBroadException
        try:
            coordinator.send_status(MessageRemoval(
                source_channel=self.channel, destination_channel=dest_channel, message=etm_msg
            ))
        except EFBException as e:
            self.logger.exception("Failed to remove message from remote chat. Message: %s; Error: %s", etm_msg, e)
            return reply.reply_text(self._(
                "Failed to remove this message from remote chat.\n\n{error!s}"
            ).format(error=e))
        except Exception as e:
            self.logger.exception("Failed to remove message from remote chat. Message: %s; Error: %s", etm_msg, e)
            return reply.reply_text(self._(
                "Failed to remove this message from remote chat.\n\n{error!r}"
            ).format(error=e))
        if not self.channel.flag('prevent_message_removal'):
            try:
                reply.delete()
            except TelegramError:
                reply.reply_text(self._("Message is removed in remote chat."))
        else:
            reply.reply_text(self._("Message is removed in remote chat."))

    def unsupported_message(self, update: Update, context: CallbackContext):
        assert isinstance(update, Update)
        assert update.effective_message

        message_type = get_msg_type(update.effective_message)
        self.bot.reply_error(
            update,
            self._("{type_name} messages are not supported by "
                   "EFB Telegram Master channel.")
                .format(type_name=message_type.name))
