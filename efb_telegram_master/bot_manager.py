# coding=utf-8
import collections
import html
import io
import logging
import os
from functools import wraps
from typing import List, TYPE_CHECKING, Callable

import telegram.constants
import telegram.error
from retrying import retry
from telegram import Update, InputFile, User, File
from telegram.ext import CallbackContext, Filters, MessageHandler, Updater, Dispatcher

from .locale_handler import LocaleHandler
from .locale_mixin import LocaleMixin

if TYPE_CHECKING:
    from . import TelegramChannel

MAX_CALLBACK_QUERY_ANSWER_LENGTH = 200


class TelegramBotManager(LocaleMixin):
    """
    This is a wrapper of Telegram's message sending and editing methods.
    Used to deal with text/caption length overflow, parse_mode, document fallback, etc.

    Attributes:
        me (telegram.User): Telegram User
        admins (List[int]): List of admin user IDs.
        updater (telegram.ext.Updater): Updater of the bot
        dispatcher (telegram.ext.Dispatcher): Dispatcher of the updater
    """

    webhook = False
    logger = logging.getLogger(__name__)

    class Decorators:
        logger = logging.getLogger(__name__)

        enable_retry = False

        @classmethod
        def exception_filter(cls, exception: Exception):
            cls.logger.exception("Exception: %s while sending request to Telegram server.", exception)
            return isinstance(exception, telegram.error.TimedOut)

        @classmethod
        def retry_on_timeout(cls, fn: Callable):
            """Infinitely retry for timed-out exceptions."""
            if not cls.enable_retry:
                return fn
            cls.logger.debug("Trying to call %s with infinite retry.", fn)
            return retry(wait_exponential_multiplier=1e3, wait_exponential_max=180e3,
                         retry_on_exception=cls.exception_filter)(fn)

        @classmethod
        def caption_strip_class_on_failure(cls, fn: Callable):
            @wraps(fn)
            def caption_strip_class_on_failure_wrapper(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except telegram.error.BadRequest as e:
                    if e.message.lower().startswith("can't parse entities") and 'parse_mode' in kwargs:
                        kwargs.pop("parse_mode")
                        for i in args:
                            if callable(getattr(i, 'seek', None)):
                                i.seek(0)
                        for i in kwargs.values():
                            if callable(getattr(i, 'seek', None)):
                                i.seek(0)
                        return fn(*args, **kwargs)
                    else:
                        raise e

            return caption_strip_class_on_failure_wrapper

        @classmethod
        def caption_affix_decorator(cls, fn: Callable):
            fn = cls.caption_strip_class_on_failure(fn)

            @wraps(fn)
            def caption_affix(self, *args, **kwargs):
                prefix = kwargs.pop('prefix', '')
                suffix = kwargs.pop('suffix', '')
                text = kwargs.pop('caption', '')

                file = args[1] if len(args) >= 2 else kwargs.get('file', None)
                chat = args[0] if len(args) >= 1 else kwargs.get('chat_id', None)

                if file:
                    is_empty = self._detect_empty_file(file, chat, text, prefix, suffix)

                    if is_empty:
                        return is_empty

                prefix = (prefix and (prefix + "\n")) or prefix
                suffix = (suffix and ("\n" + suffix)) or suffix

                if str(kwargs.get('parse_mode', '')).lower() == "html":
                    prefix = html.escape(prefix)
                    suffix = html.escape(suffix)

                if len(prefix + text + suffix) >= telegram.constants.MAX_CAPTION_LENGTH:
                    full_message = io.StringIO(prefix + text + suffix)
                    truncated = prefix + text[:100] + "\n…\n" + text[-100:] + suffix
                    kwargs['caption'] = truncated
                    msg = fn(self, *args, **kwargs)
                    chat_id = kwargs.get("chat_id", args[0] if len(args) > 0 else "")
                    filename = "%s_%s.txt" % (chat_id, msg.message_id)
                    self.updater.bot.send_document(chat_id, full_message,
                                                   filename=filename,
                                                   reply_to_message_id=msg.message_id,
                                                   caption=self._("Caption is truncated due to its length. "
                                                                  "Full message is sent as attachment."))
                    return msg
                else:
                    kwargs['caption'] = prefix + text + suffix
                    return fn(self, *args, **kwargs)

            return caption_affix

        @classmethod
        def retry_on_chat_migration(cls, fn: Callable):
            @wraps(fn)
            def retry_on_chat_migration_wrap(self: 'TelegramBotManager', *args, **kwargs):
                try:
                    return fn(self, *args, **kwargs)
                except telegram.error.ChatMigrated as e:
                    if 'chat_id' in kwargs:
                        chat_id = kwargs['chat_id']
                        self.channel.chat_binding.chat_migration_by_id(chat_id, e.new_chat_id)
                        kwargs['chat_id'] = e.new_chat_id
                        return fn(self, *args, **kwargs)
                    else:
                        args
                        chat_id = args[0]
                        self.channel.chat_binding.chat_migration_by_id(chat_id, e.new_chat_id)
                        args = (e.new_chat_id, *args[1:])
                        return fn(self, *args, **kwargs)

            return retry_on_chat_migration_wrap

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        config = self.channel.config

        req_kwargs = {'read_timeout': 15}
        conf_req_kwargs = config.get('request_kwargs')
        if isinstance(conf_req_kwargs, collections.abc.Mapping):
            req_kwargs.update(conf_req_kwargs)

        self.logger.debug("Setting up Telegram bot updater...")
        self.updater: Updater = Updater(config['token'],
                                        base_url=channel.flag('api_base_url'),
                                        base_file_url=channel.flag('api_base_file_url'),
                                        request_kwargs=req_kwargs,
                                        use_context=True)

        if isinstance(config.get('webhook'), dict):
            self.logger.debug("Setting up webhook...")
            self.webhook = True
            self.logger.debug("Webhook is set...")

        self.logger.debug("Checking connection to Telegram bot API...")
        me = self.updater.bot.get_me()
        assert me, "Invalid bot credential provided."
        self.me: User = me
        self.logger.debug("Connection to Telegram bot API is OK...")
        self.admins: List[int] = config['admins']
        self.dispatcher: Dispatcher = self.updater.dispatcher
        self.logger.debug("Adding base dispatchers...")
        # New whitelist handler
        whitelist_filter = ~Filters.user(user_id=self.admins)
        self.dispatcher.add_handler(
            MessageHandler(whitelist_filter, lambda update, context: ...))
        self.dispatcher.add_handler(LocaleHandler(channel))
        self.Decorators.enable_retry = channel.flag('retry_on_error')
        self.logger.debug("Base dispatchers added...")

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def send_message(self, *args, prefix: str = '', suffix: str = '', **kwargs):
        """
        Send text message.

        Takes exactly same parameters as telegram.bot.send_message,
        plus the following.

        Args:
            prefix (str, optional): Prefix of the message. Default: ""
            suffix (str, optional): Suffix of the message. Default: ""

        Returns:
            telegram.Message
        """
        prefix = (prefix and (prefix + "\n")) or prefix
        suffix = (suffix and ("\n" + suffix)) or suffix
        if str(kwargs.get('parse_mode', '')).lower() == "html":
            prefix = html.escape(prefix)
            suffix = html.escape(suffix)
        text: str
        if args[1:]:
            text = args[1]
        else:
            text = kwargs.pop('text')
        args = args[:1]
        if len(prefix + text + suffix) >= telegram.constants.MAX_MESSAGE_LENGTH:
            full_message = io.BytesIO((prefix + text + suffix).encode('utf-8'))
            full_message.seek(0)
            truncated = prefix + text[:100] + "\n...\n" + text[-100:] + suffix
            msg = self._bot_send_message_fallback(args[0], text=truncated, **kwargs)
            filename = "%s_%s" % (args[0], msg.message_id)
            if not kwargs.get('parse_mode'):
                filename += ".txt"
            elif kwargs.get('parse_mode', '').lower() == 'markdown':
                filename += ".md"
            elif kwargs.get('parse_mode', '').lower() == 'html':
                filename += ".html"
            else:
                filename += ".txt"
            self.updater.bot.send_document(args[0], full_message, filename=filename,
                                           reply_to_message_id=msg.message_id,
                                           caption=self._("Message is truncated due to its length. "
                                                          "Full message is sent as attachment."))
            return msg
        else:
            kwargs['text'] = prefix + text + suffix
            return self._bot_send_message_fallback(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def edit_message_text(self, prefix='', suffix='', **kwargs):
        """
        Edit text message.
        Takes exactly same parameters as telegram.bot.edit_message_text,
        plus the following.

        Args:
            prefix (str, optional): Prefix of the message. Default: ""
            suffix (str, optional): Suffix of the message. Default: ""

        Returns:
            telegram.Message
        """
        prefix = (prefix and (prefix + "\n")) or prefix
        suffix = (suffix and ("\n" + suffix)) or suffix
        if str(kwargs.get('parse_mode', '')).lower() == "html":
            prefix = html.escape(prefix)
            suffix = html.escape(suffix)
        text = kwargs.pop('text', '')
        if len(prefix + text + suffix) >= telegram.constants.MAX_MESSAGE_LENGTH:
            full_message = io.BytesIO((prefix + text + suffix).encode())
            truncated = prefix + text[:100] + "\n...\n" + text[-100:] + suffix
            msg = self._bot_edit_message_text_fallback(text=truncated, **kwargs)
            filename = "%s_%s" % (kwargs['chat_id'], msg.message_id)
            if kwargs.get('parse_mode', '').lower() == 'markdown':
                filename += ".md"
            elif kwargs.get('parse_mode', '').lower() == 'html':
                filename += ".html"
            else:
                filename += ".txt"
            self.updater.bot.send_document(kwargs['chat_id'], full_message,
                                           filename=filename,
                                           reply_to_message_id=msg.message_id,
                                           caption=self._("Message is truncated due to its length. "
                                                          "Full message is sent as attachment."))
            return msg
        else:
            kwargs['text'] = prefix + text + suffix
            return self._bot_edit_message_text_fallback(**kwargs)

    def _bot_send_message_fallback(self, *args, **kwargs):
        """
        Remove ``parse_mode`` if the server fails to parse.

        Returns:
            telegram.Message: The message sent
        """
        try:
            return self.updater.bot.send_message(*args, **kwargs)
        except telegram.error.BadRequest as e:
            if e.message.lower().startswith("can't parse entities") and 'parse_mode' in kwargs:
                kwargs.pop("parse_mode")
                return self.updater.bot.send_message(*args, **kwargs)
            else:
                raise e

    def _bot_edit_message_text_fallback(self, *args, **kwargs):
        """
        Remove ``parse_mode`` if the server fails to parse.

        Returns:
            telegram.Message: The message sent
        """
        try:
            return self.updater.bot.edit_message_text(*args, **kwargs)
        except telegram.error.BadRequest as e:
            if e.message == "Message can't be edited":
                kwargs['reply_to_message_id'] = kwargs.pop('message_id')
                return self.updater.bot.send_message(*args, **kwargs)
            elif e.message == "message to edit not found":
                kwargs.pop('message_id')
                return self.updater.bot.send_message(*args, **kwargs)
            elif e.message.lower().startswith("can't parse entities") and 'parse_mode' in kwargs:
                kwargs.pop("parse_mode")
                return self.updater.bot.edit_message_text(*args, **kwargs)
            else:
                raise e

    @Decorators.retry_on_timeout
    @Decorators.caption_affix_decorator
    @Decorators.retry_on_chat_migration
    def send_audio(self, *args, **kwargs):
        """
        Send an audio file.

        Takes exactly same parameters as telegram.bot.send_audio,
        plus the following.

        Fallback to document when failed to send.

        Args:
            prefix (str, optional): Prefix of the caption. Default: ""
            suffix (str, optional): Suffix of the caption. Default: ""

        Returns:
            telegram.Message
        """
        try:
            return self.updater.bot.send_audio(*args, **kwargs)
        except telegram.error.BadRequest:
            return self.updater.bot.send_document(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.caption_affix_decorator
    @Decorators.retry_on_chat_migration
    def send_voice(self, *args, **kwargs):
        """
        Send an voice message.

        Takes exactly same parameters as telegram.bot.send_voice,
        plus the following.

        Fallback to document when failed to send.

        Args:
            prefix (str, optional): Prefix of the caption. Default: ""
            suffix (str, optional): Suffix of the caption. Default: ""

        Returns:
            telegram.Message
        """
        try:
            return self.updater.bot.send_voice(*args, **kwargs)
        except telegram.error.BadRequest:
            return self.updater.bot.send_document(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.caption_affix_decorator
    @Decorators.retry_on_chat_migration
    def send_video(self, *args, **kwargs):
        """
        Send an voice message.

        Takes exactly same parameters as telegram.bot.send_voice,
        plus the following.

        Fallback to document when failed to send.

        Args:
            prefix (str, optional): Prefix of the caption. Default: ""
            suffix (str, optional): Suffix of the caption. Default: ""

        Returns:
            telegram.Message
        """
        try:
            return self.updater.bot.send_video(*args, **kwargs)
        except telegram.error.BadRequest:
            return self.updater.bot.send_document(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.caption_affix_decorator
    @Decorators.retry_on_chat_migration
    def send_document(self, *args, **kwargs):
        """
        Send a document.

        Takes exactly same parameters as telegram.bot.send_document,
        plus the following.

        Args:
            prefix (str, optional): Prefix of the caption. Default: ""
            suffix (str, optional): Suffix of the caption. Default: ""

        Returns:
            telegram.Message
        """
        return self.updater.bot.send_document(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.caption_affix_decorator
    @Decorators.retry_on_chat_migration
    def send_animation(self, *args, **kwargs):
        """
        Send a document.

        Takes exactly same parameters as telegram.bot.send_document,
        plus the following.

        Args:
            prefix (str, optional): Prefix of the caption. Default: ""
            suffix (str, optional): Suffix of the caption. Default: ""

        Returns:
            telegram.Message
        """
        return self.updater.bot.send_animation(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.caption_affix_decorator
    @Decorators.retry_on_chat_migration
    def send_photo(self, *args, **kwargs):
        """
        Send a document.

        Takes exactly same parameters as telegram.bot.send_document,
        plus the following.

        Args:
            prefix (str, optional): Prefix of the caption. Default: ""
            suffix (str, optional): Suffix of the caption. Default: ""

        Returns:
            telegram.Message
        """
        try:
            return self.updater.bot.send_photo(*args, **kwargs)
        except telegram.error.BadRequest:
            return self.updater.bot.send_document(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def send_chat_action(self, *args, **kwargs):
        return self.updater.bot.send_chat_action(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def edit_message_reply_markup(self, *args, **kwargs):
        return self.updater.bot.edit_message_reply_markup(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def send_location(self, *args, **kwargs):
        return self.updater.bot.send_location(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def send_venue(self, *args, **kwargs):
        return self.updater.bot.send_venue(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def send_sticker(self, *args, **kwargs):
        return self.updater.bot.send_sticker(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def get_me(self, *args, **kwargs):
        return self.updater.bot.get_me(*args, **kwargs)

    def session_expired(self, update: Update, context: CallbackContext):
        assert isinstance(update, Update)
        assert update.effective_message
        assert update.effective_chat
        if update.callback_query:
            update.callback_query.answer()
        self.edit_message_text(text=self._("Session expired. Please try again. (SE01)"),
                               chat_id=update.effective_chat.id,
                               message_id=update.effective_message.message_id)

    @Decorators.retry_on_timeout
    @Decorators.caption_affix_decorator
    @Decorators.retry_on_chat_migration
    def edit_message_caption(self, *args, **kwargs):
        return self.updater.bot.edit_message_caption(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def edit_message_media(self, *args, **kwargs):
        return self.updater.bot.edit_message_media(*args, **kwargs)

    def reply_error(self, update, errmsg):
        """
        A wrap that quote-reply a message with error details.

        Returns:
            telegram.Message: Message sent
        """
        return self.send_message(update.effective_chat.id, errmsg,
                                 reply_to_message_id=update.effective_message.message_id)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def get_file(self, file_id: str) -> File:
        return self.updater.bot.get_file(file_id)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def delete_message(self, chat_id, message_id):
        return self.updater.bot.delete_message(chat_id, message_id)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def answer_callback_query(self, *args, prefix="", suffix="", text=None,
                              message_id=None, **kwargs):
        if text is None:
            return self.updater.bot.answer_callback_query(
                *args, **kwargs
            )
        prefix = (prefix and (prefix + "\n")) or prefix
        suffix = (suffix and ("\n" + suffix)) or suffix

        chat_id = kwargs.get('chat_id')

        if len(prefix + text + suffix) >= MAX_CALLBACK_QUERY_ANSWER_LENGTH:
            full_message = prefix + text + suffix
            full_message_buffer = io.StringIO(full_message)
            keep_size = MAX_CALLBACK_QUERY_ANSWER_LENGTH // 3
            truncated = full_message[:keep_size] + "…" + full_message[keep_size:]
            result = self.updater.bot.answer_callback_query(*args, text=truncated, **kwargs)
            filename = f"{chat_id}_{message_id}.txt"
            self.updater.bot.send_document(args[0], full_message_buffer, filename,
                                           reply_to_message_id=message_id,
                                           caption=self._("Response is truncated due to its length. "
                                                          "Full message is sent as attachment."))
            return result
        self.logger.debug(f"answer_callback_query({args}, {kwargs})")
        return self.updater.bot.answer_callback_query(
            *args, text=prefix + text + suffix, **kwargs
        )

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def set_chat_title(self, *args, **kwargs):
        return self.updater.bot.set_chat_title(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def set_chat_photo(self, *args, **kwargs):
        return self.updater.bot.set_chat_photo(*args, **kwargs)

    @Decorators.retry_on_timeout
    @Decorators.retry_on_chat_migration
    def set_chat_description(self, *args, **kwargs):
        return self.updater.bot.set_chat_description(*args, **kwargs)

    def polling(self, drop_pending_updates: bool = False):
        """
        Poll message from Telegram Bot API. Can be used to extend for web hook.
        This method must NOT be blocking.

        Args:
            drop_pending_updates: Whether to clean any pending updates on
                Telegram servers before actually starting to poll.
                Default is False.
        """
        if self.webhook:
            start_webhook = self.channel.config['webhook']['start_webhook']
            self.updater.start_webhook(**start_webhook)
        else:
            self.updater.start_polling(timeout=10, drop_pending_updates=drop_pending_updates)

    def graceful_stop(self):
        """Gracefully stop the bot"""
        self.updater.stop()

    def _detect_empty_file(self, file, chat, caption, prefix, suffix):
        empty = True
        if isinstance(file, str):
            empty = os.stat(file).st_size == 0
        elif hasattr(file, "seekable"):
            if file.seekable():
                file.seek(0, 2)
                empty = file.tell() == 0
                file.seek(0, 0)
        elif isinstance(file, InputFile):
            empty = not bool(len(file.input_file_content))
        if empty:
            return self.send_message(chat, prefix=self._("Empty attachment detected.") + prefix,
                                     text=caption, suffix=suffix)
