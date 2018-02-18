# coding=utf-8

from typing import Tuple, Dict, TYPE_CHECKING, List

from telegram import Message, Update
from telegram.ext import CommandHandler, ConversationHandler, RegexHandler, CallbackQueryHandler

from ehforwarderbot import coordinator, EFBChannel
from ehforwarderbot.message import EFBMsgCommand
from .constants import Flags
from .locale_mixin import LocaleMixin

if TYPE_CHECKING:
    from . import TelegramChannel


class ETMCommandMsgStorage:
    def __init__(self, command: List[EFBMsgCommand], channel: EFBChannel, prefix: str, body: str):
        self.commands = command
        self.channels = channel
        self.prefix = prefix
        self.body = body


class CommandsManager(LocaleMixin):
    """
    Functions related to Command messages and
    Additional features of slave channels.
    """

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        self.bot = channel.bot_manager
        self.msg_storage: Dict[Tuple[int, int], ETMCommandMsgStorage] = dict()

        self.bot.dispatcher.add_handler(
            CommandHandler("extra", self.extra_help))
        self.bot.dispatcher.add_handler(
            RegexHandler(r"^/(?P<id>[0-9]+)_(?P<command>[a-z0-9_-]+)", self.extra_call,
                         pass_groupdict=True))

        self.command_conv = ConversationHandler(
            entry_points=[],
            states={Flags.COMMAND_PENDING: [CallbackQueryHandler(self.command_exec)]},
            fallbacks=[CallbackQueryHandler(self.bot.session_expired)],
            per_message=True,
            per_chat=True,
            per_user=False
        )

        self.bot.dispatcher.add_handler(self.command_conv)

    def register_command(self, message: Message, commands: ETMCommandMsgStorage):
        message_identifier = (message.chat.id, message.message_id)
        self.command_conv.conversations[message_identifier] = Flags.COMMAND_PENDING
        self.msg_storage[message_identifier] = commands

    def command_exec(self, bot, update: Update) -> int:
        """
        Run a command from a command message.
        Triggered by callback message with status `Flags.COMMAND_PENDING`.

        This method is a part of the command message conversation handler.

        Args:
            bot: Telegram Bot instance
            update: The update

        Returns:
            The next state
        """

        chat_id = update.effective_chat.id
        message_id = update.effective_message.message_id
        callback = update.callback_query.data

        index = (chat_id, message_id)

        if not callback.isdecimal():
            msg = self._("Invalid parameter: {0}. (CE01)").format(callback)
            self.msg_storage.pop(index, None)
            self.bot.edit_message_text(text=msg, chat_id=chat_id, message_id=message_id)
            return ConversationHandler.END
        elif not (0 <= int(callback) < len(self.msg_storage[index].commands)):
            msg = self._("Index out of bound: {0}. (CE02)").format(callback)
            self.msg_storage.pop(index, None)
            self.bot.edit_message_text(text=msg, chat_id=chat_id, message_id=message_id)
            return ConversationHandler.END

        callback = int(callback)
        command_storage = self.msg_storage[index]
        channel_id = command_storage.channels.channel_id
        command = command_storage.commands[callback]
        prefix = "%s\n%s\n--------" % (command_storage.prefix, command_storage.body)

        fn = getattr(coordinator.slaves[channel_id], command.callable_name, None)
        if fn is not None:
            msg = fn(*command.args, **command.kwargs)
        else:
            msg = self._command_fallback(*command.args, __channel_id=channel_id, __callable=command.callable,
                                         **command.kwargs)
        self.msg_storage.pop(index, None)
        self.bot.edit_message_text(prefix=prefix, text=msg,
                                   chat_id=chat_id, message_id=message_id)
        return ConversationHandler.END

    def extra_help(self, bot, update):
        """
        Show list of additional features and their usage.
        Triggered by `/extra`.

        Args:
            bot: Telegram Bot instance
            update: Message update
        """
        msg = self._("List of slave channel features:")
        for n, i in enumerate(sorted(coordinator.slaves)):
            i = coordinator.slaves[i]
            msg += "\n\n<b>%s %s</b>" % (i.channel_emoji, i.channel_name)
            extra_fns = i.get_extra_functions()
            if extra_fns:
                for j in extra_fns:
                    fn_name = "/%s_%s" % (n, j)
                    msg += "\n\n%s <b>(%s)</b>\n%s" % (
                        fn_name, extra_fns[j].name, extra_fns[j].desc.format(function_name=fn_name))
            else:
                msg += self._("\nNo command found.")
        self.bot.send_message(update.effective_chat.id, msg, parse_mode="HTML")

    def extra_call(self, bot, update, groupdict: Dict[str, str] = None):
        """
        Invoke an additional feature from slave channel.

        Args:
            bot: Telegram Bot instance
            update: Message update
            groupdict: Parameters offered by the message
                'id': Index of channel sorted by ``channel_id`` in lexicographical order.
                'command': Name of the command.
        """
        if int(groupdict['id']) >= len(coordinator.slaves):
            return self.bot.reply_error(update, self._("Invalid slave channel ID. (XC01)"))

        slaves = coordinator.slaves

        channel = slaves[sorted(slaves)[int(groupdict['id'])]]
        functions = channel.get_extra_functions()

        if groupdict['command'] not in functions:
            return self.bot.reply_error(update, self._("Command not found in selected channel. (XC02)"))

        header = "%s %s: %s\n-------\n" % (
            channel.channel_emoji, channel.channel_name, functions[groupdict['command']].name)
        msg = self.bot.send_message(update.message.chat.id,
                                    prefix=header, text=self._("Please wait..."))

        result = functions[groupdict['command']](" ".join(update.message.text.split(' ', 1)[1:]))

        self.bot.edit_message_text(prefix=header, text=result,
                                   chat_id=update.message.chat.id, message_id=msg.message_id)

    def _command_fallback(self, *args, __channel_id: str, __callable: str, **kwargs) -> str:
        return self._("Error: Command is not found in the channel.\n"
                      "Function: {channel_id}.{callable}\n"
                      "Arguments: {args!r}\nKeyword Arguments: {kwargs!r}").format(channel_id=__channel_id,
                                                                                   callable=__callable,
                                                                                   args=args,
                                                                                   kwargs=kwargs)
