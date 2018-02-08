# coding=utf-8

from telegram import Update
from telegram.ext import CommandHandler


class GlobalCommandHandler(CommandHandler):
    """Global command handler, handles commands from both chats and channels."""

    def check_update(self, update):
        """Determines whether an update should be passed to this handlers :attr:`callback`.

        Args:
            update (:class:`telegram.Update`): Incoming telegram update.

        Returns:
            :obj:`bool`
        """
        if (isinstance(update, Update)
                and ((update.message or update.edited_message and self.allow_edited) or
                     (update.channel_post or update.edited_channel_post and self.allow_edited))):
            message = update.message or update.edited_message

            if message.text and message.text.startswith('/') and len(message.text) > 1:
                command = message.text[1:].split(None, 1)[0].split('@')
                command.append(
                    message.bot.username)  # in case the command was send without a username

                if self.filters is None:
                    res = True
                elif isinstance(self.filters, list):
                    res = any(func(message) for func in self.filters)
                else:
                    res = self.filters(message)

                return res and (command[0].lower() in self.command
                                and command[1].lower() == message.bot.username.lower())
            else:
                return False

        else:
            return False
