from typing import Optional, List, TYPE_CHECKING, Callable

import telegram
import telegram.ext
import telegram.error
import telegram.constants
import io
import os

from .whitelisthandler import WhitelistHandler
if TYPE_CHECKING:
    from . import TelegramChannel


class TelegramBotManager:
    """
    This is a wrapper of Telegram's message sending and editing methods.
    Used to deal with text/caption length overflow, parse_mode, document fallback, etc.

    Attributes:
        me (telegram.User): Telegram User
        admins (List[int]): List of admin user IDs.
        updater (telegram.ext.Updater): Updater of the bot
        dispatcher (telegram.ext.Dispatcher): Dispatcher of the updater
    """

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        try:
            self.updater: telegram.ext.Updater = telegram.ext.Updater(self.channel.config['token'])
        except (AttributeError, KeyError):
            raise ValueError("Token is not properly defined.")
        self.me: telegram.User = self.updater.bot.get_me()
        self.admins: List[int] = self.channel.config['admins']
        self.dispatcher: telegram.ext.Dispatcher = self.updater.dispatcher
        self.dispatcher.add_handler(WhitelistHandler(self.admins))

    def send_message(self, *args, prefix: Optional[str]= '', suffix: Optional[str]= '', **kwargs):
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
        text = (args[1:] and args[1]) or kwargs.pop('text', '')
        args = args[:1]
        if len(prefix + text + suffix) >= telegram.constants.MAX_MESSAGE_LENGTH:
            full_message = io.StringIO(prefix + text + suffix)
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
            self.updater.bot.send_document(args[0], full_message, filename,
                                           reply_to_message_id=msg.message_id,
                                           caption="Message is truncated due to its length. "
                                                   "Full message is sent as attachment.")
            return msg
        else:
            kwargs['text'] = prefix + text + suffix
            return self._bot_send_message_fallback(*args, **kwargs)

    def edit_message_text(self, *args, **kwargs):
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
        prefix = kwargs.pop('prefix', '')
        prefix = (prefix and (prefix + "\n")) or prefix
        suffix = kwargs.pop('suffix', '')
        suffix = (suffix and ("\n" + suffix)) or suffix
        text = kwargs.pop('text', '')
        if len(prefix + text + suffix) >= telegram.constants.MAX_MESSAGE_LENGTH:
            full_message = io.BytesIO((prefix + text + suffix).encode())
            truncated = prefix + text[:100] + "\n...\n" + text[-100:] + suffix
            msg = self._bot_edit_message_text_fallback(truncated, **kwargs)
            filename = "%s_%s" % (kwargs['chat_id'], msg.message_id)
            if kwargs.get('parse_mode', '').lower() == 'markdown':
                filename += ".md"
            elif kwargs.get('parse_mode', '').lower() == 'html':
                filename += ".html"
            else:
                filename += ".txt"
            self.updater.bot.send_document(kwargs['chat_id'], full_message, filename,
                                           reply_to_message_id=msg.message_id,
                                           caption="Message is truncated due to its length. "
                                                   "Full message is sent as attachment.")
            return msg
        else:
            kwargs['text'] = prefix + text + suffix
            return self._bot_edit_message_text_fallback(*args, **kwargs)

    def _bot_send_message_fallback(self, *args, **kwargs):
        """
        Remove ``parse_mode`` if the server fails to parse.
        
        Returns:
            telegram.Message: The message sent
        """
        try:
            return self.updater.bot.send_message(*args, **kwargs)
        except telegram.error.BadRequest:
            kwargs.pop("parse_mode")
            return self.updater.bot.send_message(*args, **kwargs)

    def _bot_edit_message_text_fallback(self, *args, **kwargs):
        """
        Remove ``parse_mode`` if the server fails to parse.

        Returns:
            telegram.Message: The message sent
        """
        try:
            return self.updater.bot.edit_message_text(*args, **kwargs)
        except telegram.error.BadRequest:
            if 'parse_mode' in kwargs:
                kwargs.pop("parse_mode")
            return self.updater.bot.edit_message_text(*args, **kwargs)

    # @Decorator
    def caption_affix_decorator(fn: Callable):
        def caption_affix(self, *args, **kwargs):
            prefix = kwargs.pop('prefix', '')
            suffix = kwargs.pop('suffix', '')
            text = kwargs.pop('caption', '')

            is_empty = self._detect_empty_file(args[1], args[0], text, prefix, suffix)

            if is_empty:
                return is_empty

            prefix = (prefix and (prefix + "\n")) or prefix
            suffix = (suffix and ("\n" + suffix)) or suffix

            if len(prefix + text + suffix) >= telegram.constants.MAX_CAPTION_LENGTH:
                full_message = io.StringIO(prefix + text + suffix)
                truncated = prefix + text[:100] + "\n...\n" + text[:-100] + suffix
                kwargs['caption'] = truncated
                msg = fn(self, *args, **kwargs)
                filename = "%s_%s.txt" % (args[0], msg.message_id)
                self.updater.bot.send_document(args[0], full_message, filename,
                                               reply_to_message_id=msg.message_id,
                                               caption="Message is truncated due to its length. "
                                                       "Full message is sent as attachment.")
                return msg
            else:
                kwargs['caption'] = prefix + text + suffix
                return fn(self, *args, **kwargs)
        return caption_affix

    @caption_affix_decorator
    def send_picture(self, *args, **kwargs):
        """
        Send a picture.
        
        Takes exactly same parameters as telegram.bot.send_picture, 
        plus the following.
        
        Fallback to document when failed to send.

        Args:
            prefix (str, optional): Prefix of the caption. Default: ""
            suffix (str, optional): Suffix of the caption. Default: ""

        Returns:
            telegram.Message
        """
        try:
            return self.updater.bot.send_picture(*args, **kwargs)
        except telegram.error.BadRequest:
            return self.updater.bot.send_document(*args, **kwargs)

    @caption_affix_decorator
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

    @caption_affix_decorator
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

    @caption_affix_decorator
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

    @caption_affix_decorator
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

    @caption_affix_decorator
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
        return self.updater.bot.send_photo(*args, **kwargs)

    def send_chat_action(self, *args, **kwargs):
        return self.updater.bot.send_chat_action(*args, **kwargs)

    def send_venue(self, *args, **kwargs):
        return self.updater.bot.send_venue(*args, **kwargs)

    def get_me(self, *args, **kwargs):
        return self.updater.bot.get_me(*args, **kwargs)

    def session_expired(self, bot, update):
        self.edit_message_text(text="Session expired. Please try again. (SE01)",
                                   chat_id=update.effective_chat.id,
                                   message_id=update.effective_message.message_id)

    @caption_affix_decorator
    def edit_message_caption(self, *args, **kwargs):
        return self.updater.bot.edit_message_caption(*args, **kwargs)

    def reply_error(self, update, errmsg):
        """
        A wrap that directly reply a message with error details.

        Returns:
            telegram.Message: Message sent
        """
        return self.send_message(update.effective_chat.id, errmsg,
                                 reply_to_message_id=update.effective_message.message_id)

    def get_file(self, file_id):
        return self.updater.bot.get_file(file_id)

    def delete_message(self, chat_id, message_id):
        return self.updater.bot.delete_message(chat_id, message_id)

    def polling(self):
        """
        Poll message from Telegram Bot API. Can be used to extend for web hook.
        This method must NOT be blocking.
        """
        self.updater.start_polling(timeout=10)

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
        if empty:
            return self.send_message(chat, prefix="Empty attachment detected." + prefix,
                                     text=caption, suffix=suffix)
