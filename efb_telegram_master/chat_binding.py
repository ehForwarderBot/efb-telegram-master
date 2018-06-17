# coding=utf-8

import html
import logging
import re
import threading
import urllib.parse
import io
from typing import Tuple, Dict, Optional, List, Pattern, TYPE_CHECKING

import peewee
import telegram
from PIL import Image
from telegram.ext import ConversationHandler, CommandHandler, CallbackQueryHandler

from ehforwarderbot import coordinator, EFBChat, EFBChannel
from ehforwarderbot.constants import ChatType
from ehforwarderbot.exceptions import EFBChatNotFound, EFBOperationNotSupported
from . import utils
from .constants import Emoji, Flags
from .global_command_handler import GlobalCommandHandler
from .locale_mixin import LocaleMixin

if TYPE_CHECKING:
    from . import TelegramChannel
    from .bot_manager import TelegramBotManager
    from .db import DatabaseManager

__all__ = ['ChatBindingManager', 'ETMChat']


class ETMChat(EFBChat):
    # Constant
    MUTE_CHAT_ID = "__muted__"

    def __init__(self,
                 channel: Optional[EFBChannel] = None,
                 chat: Optional[EFBChat] = None,
                 db: 'DatabaseManager' = None):
        self.db = db
        if channel:
            super().__init__(channel)
        if chat:
            self.channel_name = chat.channel_name
            self.channel_emoji = chat.channel_emoji
            self.channel_id = chat.channel_id
            self.chat_name = chat.chat_name
            self.chat_type = chat.chat_type
            self.chat_alias = chat.chat_alias
            self.chat_uid = chat.chat_uid
            self.is_chat = chat.is_chat
            self.members = chat.members.copy()
            self.chat = chat.group
            self.vendor_specific = chat.vendor_specific.copy()
        self.linked: List[str] = self.db.get_chat_assoc(slave_uid=utils.chat_id_to_str(self.channel_id, self.chat_uid))
        self.muted: bool = self.MUTE_CHAT_ID in self.linked

    def match(self, pattern: Optional[Pattern]) -> bool:
        """
        Match the chat against a compiled regular expression
        with a string in the following format::

            Channel: <Channel name>
            Name: <Chat name>
            Alias: <Chat Alias>
            ID: <Chat Unique ID>
            Type: (User|Group)
            Mode: [[Muted, ]Linked]
            Other: <Python Dictionary String>

        Args:
            pattern: Regular expression

        Returns:
            If the expression is matched using ``pattern.search``.
        """
        if pattern is None:
            return True
        mode = []
        if self.muted:
            mode.append("Muted")
        if self.linked:
            mode.append("Linked")
        mode = ', '.join(mode)
        entry_string = "Channel: %s\nName: %s\nAlias: %s\nID: %s\nType: %s\nMode: %s\nOther: %s" \
                       % (self.channel_name, self.chat_name, self.chat_alias, self.chat_uid, self.chat_type,
                          mode, self.vendor_specific)
        return bool(pattern.search(entry_string))

    def unlink(self):
        """ Unlink this chat from any Telegram group."""
        self.db.remove_chat_assoc(slave_uid=utils.chat_id_to_str(self.channel_id, self.chat_uid))

    def mute(self):
        """Mute this chat completely."""
        self.unlink()
        self.db.add_chat_assoc(slave_uid=utils.chat_id_to_str(self.channel_id, self.chat_uid),
                               master_uid=ETMChat.MUTE_CHAT_ID, multiple_slave=True)

    def link(self, channel_id: str, chat_id: str, multiple_slave: bool):
        self.db.add_chat_assoc(master_uid=utils.chat_id_to_str(channel_id, chat_id),
                               slave_uid=utils.chat_id_to_str(self.channel_id, self.chat_uid),
                               multiple_slave=multiple_slave)

    @property
    def full_name(self):
        chat_display_name = self.display_name
        return "'%s' @ '%s %s'" % (chat_display_name, self.channel_emoji, self.channel_name) \
            if self.channel_name else "'%s'" % chat_display_name

    @property
    def display_name(self):
        return self.chat_name if not self.chat_alias \
            else "%s (%s)" % (self.chat_alias, self.chat_name)

    @property
    def chat_title(self):
        return "%s%s %s" % (self.channel_emoji,
                            Emoji.get_source_emoji(self.chat_type),
                            self.chat_alias or self.chat_name)


class ChatListStorage:
    """
    Storage for list of chats displayed in a message as inline buttons.

    Attributes:
        chats (List[ETMChat]): List of chats to display
        channels (Dict[str, EFBChannel]): List of channels involved
        offset (int): Current offset to display
        length (int): Length of chats.
    """

    def __init__(self, chats: List[ETMChat], offset: Optional[int] = 0):
        self.__chats: List[ETMChat] = None
        self.channels: Dict[str, EFBChannel] = None
        self.chats: List[ETMChat] = chats.copy()
        self.offset: int = offset
        self.update: Optional[telegram.Update] = None
        self.candidates: Optional[List[str]] = None

    @property
    def length(self) -> int:
        return len(self.chats)

    @property
    def chats(self) -> List[ETMChat]:
        return self.__chats

    @chats.setter
    def chats(self, value: List[ETMChat]):
        self.__chats = value
        self.channels = dict()
        for i in value:
            if i.channel_id not in self.channels:
                self.channels[i.channel_id] = coordinator.slaves[i.channel_id]

    def set_chat_suggestion(self, update: telegram.Update, candidates: List[str]):
        self.update: telegram.Update = update
        self.candidates: List[str] = candidates


class ChatBindingManager(LocaleMixin):
    """
    Manages chat bindings (links), generation of chat heads, and chat recipient suggestion.
    """

    # Message storage
    msg_storage: Dict[Tuple[int, int], ChatListStorage] = dict()
    logger: logging.Logger = logging.getLogger(__name__)

    # Consts
    TELEGRAM_MIN_PROFILE_PICTURE_SIZE = 256

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        self.bot: 'TelegramBotManager' = channel.bot_manager
        self.db: 'DatabaseManager' = channel.db

        # Link handler
        self.bot.dispatcher.add_handler(GlobalCommandHandler("link", self.link_chat_show_list, pass_args=True))
        self.link_handler = ConversationHandler(
            entry_points=[],
            states={
                Flags.LINK_CONFIRM: [CallbackQueryHandler(self.link_chat_confirm)],
                Flags.LINK_EXEC: [CallbackQueryHandler(self.link_chat_exec)],
            },
            fallbacks=[CallbackQueryHandler(self.bot.session_expired)],
            per_message=True,
            per_chat=True,
            per_user=False
        )
        self.bot.dispatcher.add_handler(self.link_handler)

        # Chat head handler
        self.bot.dispatcher.add_handler(GlobalCommandHandler("chat", self.start_chat_list, pass_args=True))
        self.chat_head_handler = ConversationHandler(
            entry_points=[],
            states={
                Flags.CHAT_HEAD_CONFIRM: [CallbackQueryHandler(self.make_chat_head)],
            },
            fallbacks=[CallbackQueryHandler(self.bot.session_expired)],
            per_message=True,
            per_chat=True,
            per_user=False
        )
        self.bot.dispatcher.add_handler(self.chat_head_handler)

        # Unlink all
        self.bot.dispatcher.add_handler(
            CommandHandler("unlink_all", self.unlink_all))

        # Recipient suggestion
        self.suggestion_handler: ConversationHandler = ConversationHandler(
            entry_points=[],
            states={Flags.SUGGEST_RECIPIENT: [CallbackQueryHandler(self.suggested_recipient)]},
            fallbacks=[CallbackQueryHandler(self.bot.session_expired)],
            per_message=True,
        )

        self.bot.dispatcher.add_handler(self.suggestion_handler)

        # Update group title and profile picture
        self.bot.dispatcher.add_handler(CommandHandler('update_info', self.update_group_info))

    def link_chat_show_list(self, bot, update, args=None):
        """
        Show the list of available chats for linking.
        Triggered by `/link`.

        When triggered in private chat, it shows all chats available,
        or list of remote chats linked to the group otherwise.
        If no chat is linked to this group, then the bot messages
        the full list privately.

        Args:
            bot: Telegram Bot instance
            update (telegram.Update): Message update
            args: Regex filter
        """
        args = args or []
        message = update.effective_message
        if message.chat.type != telegram.Chat.PRIVATE:
            links = self.db.get_chat_assoc(
                master_uid=utils.chat_id_to_str(self.channel.channel_id, message.chat.id))
            if links:
                return self.link_chat_gen_list(message.chat.id, pattern=" ".join(args), chats=links)
        elif message.forward_from_chat and \
                message.forward_from_chat.type == telegram.Chat.CHANNEL:
            chat_id = message.forward_from_chat.id
            links = self.db.get_chat_assoc(
                master_uid=utils.chat_id_to_str(self.channel.channel_id, chat_id))
            if links:
                return self.link_chat_gen_list(message.chat.id, pattern=" ".join(args), chats=links)

        return self.link_chat_gen_list(message.from_user.id, pattern=" ".join(args))

    def slave_chats_pagination(self, storage_id: Tuple[int, int],
                               offset: int = 0,
                               pattern: Optional[str] = "",
                               source_chats: Optional[List[str]] = None) \
            -> Tuple[List[str], List[List[telegram.InlineKeyboardButton]]]:
        """
        Generate a list of (list of) `InlineKeyboardButton`s of chats in slave channels,
        based on the status of message located by `storage_id` and the paging from
        `offset` value.

        Args:
            pattern: Regular expression filter for chat details
            storage_id (Tuple[int, int]): Message_storage ID for generating the buttons list.
            offset (int): Offset for pagination
            source_chats (Optional[List[str]]): A list of chats used to generate the pagination list.
                Each str is in the format of "{channel_id}.{chat_uid}".

        Returns:
            Tuple[List[str], List[List[telegram.InlineKeyboardButton]]]:
                A tuple: legend, chat_btn_list
                `legend` is the legend of all Emoji headings in the entire list.
                `chat_btn_list` is a list which can be fit into `telegram.InlineKeyboardMarkup`.
        """
        self.logger.debug("Generating pagination of chats.\nStorage ID: %s; Offset: %s; Filter: %s; Source chats: %s;",
                          storage_id, offset, pattern, source_chats)
        legend: List[str] = [
            self._("{0}: Linked").format(Emoji.LINK),
            self._("{0}: Muted").format(Emoji.MUTED),
            self._("{0}: User").format(Emoji.USER),
            self._("{0}: Group").format(Emoji.GROUP),
        ]

        chat_list: ChatListStorage = self.msg_storage.get(storage_id, None)

        if chat_list is None or chat_list.length == 0:
            # Generate the full chat list first
            re_filter = re.compile(pattern, re.DOTALL | re.IGNORECASE) if pattern else None
            if pattern:
                self.logger.debug("Filter pattern: %s", pattern)
            chats: List[ETMChat] = []
            if source_chats:
                for i in source_chats:
                    channel_id, chat_uid = utils.chat_id_str_to_id(i)
                    if channel_id not in coordinator.slaves:
                        continue
                    channel = coordinator.slaves[channel_id]
                    try:
                        chat = ETMChat(chat=self.get_chat_from_db(channel_id, chat_uid) or channel.get_chat(chat_uid),
                                       db=self.db)
                    except KeyError:
                        self.logger.error("slave_chats_pagination with chat list: Chat %s not found.", i)
                        continue

                    if chat.match(re_filter):
                        chats.append(chat)
            else:
                for slave in coordinator.slaves.values():
                    slave_chats = slave.get_chats()
                    for chat in slave_chats:
                        chat = ETMChat(chat=chat, db=self.db)
                        if chat.match(re_filter):
                            chats.append(chat)
            chat_list = self.msg_storage[storage_id] = ChatListStorage(chats, offset)

        threading.Thread(target=self._db_update_slave_chats_cache, args=(chat_list.chats,)).start()

        for ch in chat_list.channels.values():
            legend.append("%s: %s" % (ch.channel_emoji, ch.channel_name))

        # Build inline button list
        chat_btn_list: List[List[telegram.InlineKeyboardButton]] = []
        chats_per_page = self.channel.flag("chats_per_page")
        for i in range(offset, min(offset + chats_per_page, chat_list.length)):
            chat = chat_list.chats[i]
            if chat.muted:
                mode = Emoji.MUTED
            elif chat.linked:
                mode = Emoji.LINK
            else:
                mode = ""
            chat_type = Emoji.get_source_emoji(chat.chat_type)
            chat_name = chat.chat_name if not chat.chat_alias else "%s (%s)" % (
                chat.chat_alias, chat.chat_name)
            button_text = "%s%s%s: %s" % (chat.channel_emoji, chat_type, mode, chat_name)
            button_callback = "chat %s" % i
            chat_btn_list.append([telegram.InlineKeyboardButton(button_text, callback_data=button_callback)])

        # Pagination
        page_number_row: List[telegram.InlineKeyboardButton] = []

        if offset - chats_per_page >= 0:
            page_number_row.append(telegram.InlineKeyboardButton(self._("< Prev"), callback_data="offset %s" % (
                    offset - chats_per_page)))
        page_number_row.append(telegram.InlineKeyboardButton(self._("Cancel"), callback_data=Flags.CANCEL_PROCESS))
        if offset + chats_per_page < chat_list.length:
            page_number_row.append(telegram.InlineKeyboardButton(self._("Next >"), callback_data="offset %s" % (
                    offset + chats_per_page)))
        chat_btn_list.append(page_number_row)

        return legend, chat_btn_list

    def _db_update_slave_chats_cache(self, chats: List[EFBChat]):
        """
        Update all slave chats info cache to database. Triggered by retrieving
        the entire list of chats from all slaves by the method `slave_chats_pagination`.

        Args:
            chats: List of chats generated
        """
        try:
            for i in chats:
                self.db.set_slave_chat_info(slave_channel_id=i.channel_id,
                                            slave_channel_name=i.channel_name,
                                            slave_channel_emoji=i.channel_emoji,
                                            slave_chat_uid=i.chat_uid,
                                            slave_chat_name=i.chat_name,
                                            slave_chat_alias=i.chat_alias,
                                            slave_chat_type=i.chat_type)
        except peewee.OperationalError:
            # Suppress exception of background database update
            pass

    def link_chat_gen_list(self, chat_id, message_id: int = None, offset=0,
                           pattern: str = "", chats: List[str] = None):
        """
        Generate the list for chat linking, and update it to a message.

        Args:
            chat_id: Chat ID
            message_id: ID of message to be updated, None to send a new message.
            offset: Offset for pagination.
            pattern (str): Regex expression to filter chats.
            chats (List[str]): Specified chats to link

        Returns:
            int: The next state
        """

        if not message_id:
            message_id = self.bot.send_message(chat_id, self._("Processing...")).message_id
        self.bot.send_chat_action(chat_id, telegram.ChatAction.TYPING)
        if chats:
            msg_text = self._("This Telegram group is currently linked with...")
        else:
            msg_text = self._("Please choose the chat you want to link with...")
        msg_text += self._("\n\nLegend:\n")

        legend, chat_btn_list = self.slave_chats_pagination((chat_id, message_id),
                                                            offset,
                                                            pattern=pattern,
                                                            source_chats=chats)
        for i in legend:
            msg_text += "%s\n" % i

        self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msg_text,
                                   reply_markup=telegram.InlineKeyboardMarkup(chat_btn_list))

        self.link_handler.conversations[(chat_id, message_id)] = Flags.LINK_CONFIRM

        return Flags.LINK_CONFIRM

    def link_chat_confirm(self, bot, update) -> int:
        """
        Confirmation of chat linking. Triggered by callback message on status `Flags.CONFIRM_LINK`.

        A part of ``/link`` conversation handler.

        Args:
            bot: Telegram Bot instance
            update: The update

        Returns:
            int: Next status
        """

        tg_chat_id = update.effective_chat.id
        tg_msg_id = update.effective_message.message_id
        callback_uid: str = update.callback_query.data
        if callback_uid.split()[0] == "offset":
            # Offer a new page of chats
            return self.link_chat_gen_list(tg_chat_id, message_id=tg_msg_id, offset=int(callback_uid.split()[1]))

        if callback_uid == Flags.CANCEL_PROCESS:
            # Terminate the process
            txt = self._("Cancelled.")
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            return ConversationHandler.END

        if callback_uid[:4] != "chat":
            # The only possible command now is "chat".
            txt = self._("Invalid parameter ({0}). (IP01)").format(callback_uid)
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            return ConversationHandler.END

        callback_uid: int = int(callback_uid.split()[1])
        chat: ETMChat = self.msg_storage[(tg_chat_id, tg_msg_id)].chats[callback_uid]
        chat_display_name = chat.chat_name if not chat.chat_alias else self._("{alias} ({name})") \
            .format(alias=chat.chat_alias, name=chat.chat_name)
        chat_display_name = chat.full_name

        self.msg_storage[(tg_chat_id, tg_msg_id)].chats = [chat]

        txt = self._("You've selected chat {0}.").format(html.escape(chat_display_name))
        if chat.muted:
            txt += self._("\nThis chat is currently muted.")
        elif chat.linked:
            txt += self._("\nThis chat has already linked to Telegram.")
        txt += self._("\nWhat would you like to do?\n\n"
                      "<i>* If the link button doesn't work for you, please try to link manually.</i>")

        link_url = "https://telegram.me/%s?startgroup=%s" % (
            self.bot.me.username, urllib.parse.quote(utils.b64en(utils.message_id_to_str(tg_chat_id, tg_msg_id))))
        self.logger.debug("Telegram start trigger for linking chat: %s", link_url)
        if chat.linked and not chat.muted:
            btn_list = [telegram.InlineKeyboardButton(self._("Relink"), url=link_url),
                        telegram.InlineKeyboardButton(self._("Mute"), callback_data="mute 0"),
                        telegram.InlineKeyboardButton(self._("Restore"), callback_data="unlink 0")]
        elif chat.muted:
            btn_list = [telegram.InlineKeyboardButton(self._("Link"), url=link_url),
                        telegram.InlineKeyboardButton(self._("Unmute"), callback_data="unlink 0")]
        else:
            btn_list = [telegram.InlineKeyboardButton(self._("Link"), url=link_url),
                        telegram.InlineKeyboardButton(self._("Mute"), callback_data="mute 0")]

        btn_list.append(telegram.InlineKeyboardButton(self._("Manual {link_or_relink}")
                                                      .format(link_or_relink=btn_list[0].text),
                                                      callback_data="manual_link 0"))

        btns = [btn_list,
                [telegram.InlineKeyboardButton("Cancel", callback_data=Flags.CANCEL_PROCESS)]]

        self.bot.edit_message_text(text=txt,
                                   chat_id=tg_chat_id,
                                   message_id=tg_msg_id,
                                   reply_markup=telegram.InlineKeyboardMarkup(btns),
                                   parse_mode='HTML')

        return Flags.LINK_EXEC

    def link_chat_exec(self, bot, update) -> int:
        """
        Action to link a chat. Triggered by callback message with status `Flags.EXEC_LINK`.

        Args:
            bot: Telegram Bot instance
            update: The update
        """

        tg_chat_id = update.effective_chat.id
        tg_msg_id = update.effective_message.message_id
        callback_uid = update.callback_query.data

        if callback_uid == Flags.CANCEL_PROCESS:
            txt = self._("Cancelled.")
            self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            return ConversationHandler.END

        cmd, chat_lid = callback_uid.split()
        chat: ETMChat = self.msg_storage[(tg_chat_id, tg_msg_id)].chats[int(chat_lid)]
        chat_display_name = chat.full_name
        if cmd == "unlink":
            chat.unlink()
            txt = "Chat %s is restored." % chat_display_name
            self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
        elif cmd == "mute":
            chat.mute()
            txt = "Chat %s is now muted." % chat_display_name
            self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
        elif cmd == "manual_link":
            txt = self._("To link {chat_display_name} manually, please:\n\n"
                         "1. Add me to the Telegram Group you want to link to.\n"
                         "2. Send the following code.\n\n"
                         "<code>/start {code}</code>\n\n"
                         "3. Then I would notify you if the chat is linked successfully.\n"
                         "\n"
                         "<i>* To link a channel, send the code above to your channel, "
                         "and forward it to the bot. Note that the bot will not process any "
                         "message others sent in channels.</i>") \
                .format(chat_display_name=html.escape(chat_display_name),
                        code=html.escape(utils.b64en(utils.message_id_to_str(tg_chat_id, tg_msg_id))))
            self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id,
                                       reply_markup=
                                       telegram.InlineKeyboardMarkup(
                                           [[telegram.InlineKeyboardButton(self._("Cancel"),
                                                                           callback_data=Flags.CANCEL_PROCESS)]]),
                                       parse_mode='HTML')
            return Flags.LINK_EXEC
        else:
            txt = self._("Command '{command}' ({query}) is not recognised, please try again") \
                .format(command=cmd, query=callback_uid)
            self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
        self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
        return ConversationHandler.END

    def link_chat(self, update, args):
        try:
            storage_key: Tuple[int, int] = tuple(map(int, utils.message_id_str_to_id(utils.b64de(args[0]))))
            data = self.msg_storage[storage_key]
        except KeyError:
            return update.message.reply_text(self._("Session expired or unknown parameter. (SE02)"))
        chat: ETMChat = data.chats[0]
        chat_display_name = chat.full_name
        slave_channel, slave_chat_uid = chat.channel_id, chat.chat_uid
        if slave_channel in coordinator.slaves:

            # Use channel ID if command is forwarded from a channel.
            tg_chat_to_link = update.effective_message.forward_from_chat and \
                              update.effective_message.forward_from_chat.type == telegram.Chat.CHANNEL and \
                              update.effective_message.forward_from_chat.id
            tg_chat_to_link = tg_chat_to_link or update.effective_chat.id

            txt = self._('Trying to link chat {0}...').format(chat_display_name)
            msg = self.bot.send_message(tg_chat_to_link, text=txt)

            if chat.muted:
                chat.unlink()

            chat.link(self.channel.channel_id, tg_chat_to_link, self.channel.flag("multiple_slave_chats"))

            txt = self._("Chat {0} is now linked.").format(chat_display_name)
            self.bot.edit_message_text(text=txt, chat_id=msg.chat.id, message_id=msg.message_id)

            self.bot.edit_message_text(chat_id=storage_key[0],
                                       message_id=storage_key[1],
                                       text=txt)

    def unlink_all(self, bot, update):
        """
        Unlink all chats linked to the telegram group.
        Triggered by `/unlink_all`.

        Args:
            bot: Telegram Bot instance
            update: Message update
        """
        if update.message.chat.type != telegram.Chat.PRIVATE:

            links = self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(self.channel.channel_id,
                                                                           update.message.chat.id))
            if len(links) < 1:
                return self.bot.send_message(update.message.chat.id, self._("No chat is linked to the group."),
                                             reply_to_message_id=update.message.message_id)
            else:
                self.db.remove_chat_assoc(master_uid=utils.chat_id_to_str(self.channel.channel_id,
                                                                          update.message.chat.id))
                return self.bot.send_message(update.message.chat.id,
                                             self.ngettext("All {0} chat has been unlinked from this group.",
                                                           "All {0} chats has been unlinked from this group.",
                                                           len(links)).format(len(links)),
                                             reply_to_message_id=update.message.message_id)
        else:
            if update.effective_message.forward_from_chat and \
                    update.effective_message.forward_from_chat.type == telegram.Chat.CHANNEL:
                chat = update.effective_message.forward_from_chat

                links = self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(self.channel.channel_id, chat.id))

                if len(links) < 1:
                    return self.bot.send_message(update.message.chat.id, self._("No chat is linked to the channel."),
                                                 reply_to_message_id=update.message.message_id)
                else:
                    self.db.remove_chat_assoc(master_uid=utils.chat_id_to_str(self.channel.channel_id, chat.id))
                    return self.bot.send_message(update.message.chat.id,
                                                 self.ngettext("All {0} chat has been unlinked from this channel.",
                                                               "All {0} chats has been unlinked from this channel.",
                                                               len(links)).format(len(links)),
                                                 reply_to_message_id=update.message.message_id)
            else:
                return self.bot.send_message(update.message.chat.id,
                                             self._("Send `/unlink_all` to a group to unlink all remote chats "
                                                    "from it."),
                                             parse_mode=telegram.ParseMode.MARKDOWN,
                                             reply_to_message_id=update.message.message_id)

    def start_chat_list(self, bot, update, args=None):
        """
        Send a list to for chat list generation.
        Triggered by `/chat`.

        Args:
            bot: Telegram Bot instance
            update: Message update
            args: Arguments from the command message
        """
        args = args or []
        chats = None
        if update.message.from_user.id != update.message.chat_id:
            chats = self.db.get_chat_assoc(
                master_uid=utils.chat_id_to_str(self.channel.channel_id, update.message.chat_id))
            chats = chats or None
        if chats:
            target = update.message.chat_id
        else:
            target = update.message.from_user.id
        return self.chat_head_req_generate(bot, target, pattern=" ".join(args), chats=chats)

    def chat_head_req_generate(self, bot, chat_id: int, message_id: int = None,
                               offset: int = 0, pattern: str = "", chats: List[str] = None):
        """
        Generate the list for chat head, and update it to a message.

        Args:
            bot: Telegram Bot instance
            chat_id: Chat ID
            message_id: ID of message to be updated, None to send a new message.
            offset: Offset for pagination.
            pattern: Regex String used as a filter.
            chats: Specified list of chats to start a chat head.
        """
        if not message_id:
            message_id = self.bot.send_message(chat_id, text=self._("Processing...")).message_id
        self.bot.send_chat_action(chat_id, telegram.ChatAction.TYPING)

        if chats and len(chats):
            if len(chats) == 1:
                slave_channel_id, slave_chat_id = utils.chat_id_str_to_id(chats[0])
                channel = coordinator.slaves[slave_channel_id]
                try:
                    chat: ETMChat = ETMChat(chat=self.get_chat_from_db(slave_channel_id, slave_chat_id)
                                                 or channel.get_chat(slave_chat_id))
                    msg_text = self._('This group is linked to {0}'
                                      'Send a message to this group to deliver it to the chat.\n'
                                      'Do NOT reply to this system message.') \
                        .format(chat.full_name)

                except KeyError:
                    msg_text = self._("This group is linked to an unknown chat ({chat_id}) "
                                      "on channel {channel_emoji} {channel_name}. Possibly you can "
                                      "no longer reach this chat. Send /unlink_all to unlink all chats "
                                      "from this group.").format(channel_emoji=channel.channel_emoji,
                                                                 channel_name=channel.channel_name,
                                                                 chat_id=slave_chat_id)
                self.bot.edit_message_text(text=msg_text,
                                           chat_id=chat_id,
                                           message_id=message_id)
                return ConversationHandler.END
            else:
                msg_text = self._("This Telegram group is linked to the following chats, "
                                  "choose one to start a conversation with.")
        else:
            msg_text = "Choose a chat you want to start a conversation with."

        legend, chat_btn_list = self.slave_chats_pagination((chat_id, message_id), offset, pattern=pattern,
                                                            source_chats=chats)

        msg_text += self._("\n\nLegend:\n")
        for i in legend:
            msg_text += "%s\n" % i
        self.bot.edit_message_text(text=msg_text,
                                   chat_id=chat_id,
                                   message_id=message_id,
                                   reply_markup=telegram.InlineKeyboardMarkup(chat_btn_list))

        self.chat_head_handler.conversations[(chat_id, message_id)] = Flags.CHAT_HEAD_CONFIRM

    def make_chat_head(self, bot, update) -> int:
        """
        Create a chat head. Triggered by callback message with status `Flags.START_CHOOSE_CHAT`.

        This message is a part of the ``/chat`` conversation handler.

        Args:
            bot: Telegram Bot instance
            update: The update
        """
        tg_chat_id = update.effective_chat.id
        tg_msg_id = update.effective_message.message_id
        callback_uid = update.callback_query.data

        # Refresh with a new set of pages
        if callback_uid.split()[0] == "offset":
            return self.chat_head_req_generate(bot, tg_chat_id, message_id=tg_msg_id,
                                               offset=int(callback_uid.split()[1]))
        if callback_uid == Flags.CANCEL_PROCESS:
            txt = self._("Cancelled.")
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            return ConversationHandler.END

        if callback_uid[:4] != "chat":
            # Invalid command
            txt = self._("Invalid command. ({0})").format(callback_uid)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            return ConversationHandler.END

        callback_uid = int(callback_uid.split()[1])
        chat: ETMChat = self.msg_storage[(tg_chat_id, tg_msg_id)].chats[callback_uid]
        chat_uid = utils.chat_id_to_str(chat=chat)
        chat_display_name = chat.full_name
        self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
        txt = self._("Reply to this message to chat with {0}.").format(chat_display_name)
        msg_log = {"master_msg_id": utils.message_id_to_str(tg_chat_id, tg_msg_id),
                   "text": txt,
                   "msg_type": "Text",
                   "sent_to": "master",
                   "slave_origin_uid": chat_uid,
                   "slave_origin_display_name": chat_display_name,
                   "slave_member_uid": None,
                   "slave_member_display_name": None,
                   "slave_message_id": "__chathead__"}
        self.db.add_msg_log(**msg_log)
        self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
        return ConversationHandler.END

    def get_chat_from_db(self, channel_id: str, chat_id: str) -> Optional[EFBChat]:
        d = self.db.get_slave_chat_info(slave_channel_id=channel_id, slave_chat_uid=chat_id)
        if d:
            chat = EFBChat(coordinator.slaves[channel_id])
            chat.chat_name = d.slave_chat_name
            chat.chat_alias = d.slave_chat_alias
            chat.chat_uid = d.slave_chat_uid
            chat.chat_type = ChatType(d.slave_chat_type)
            return chat
        else:
            chat = coordinator.slaves[channel_id].get_chat(chat_id)
            if chat:
                self._db_update_slave_chats_cache([chat])
                return chat

    def register_suggestions(self, update: telegram.Update, candidates: List[str], chat_id: int, message_id: int):
        storage_id = (chat_id, message_id)
        self.msg_storage[storage_id] = ChatListStorage([])
        self.msg_storage[storage_id].set_chat_suggestion(update, candidates)
        legends, buttons = self.channel.chat_binding.slave_chats_pagination(
            storage_id, 0, source_chats=candidates)
        self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                               "Please reply to a previous message, "
                                               "or choose a recipient:\n\nLegend:\n") + "\n".join(legends),
                                   chat_id=chat_id, message_id=message_id,
                                   reply_markup=telegram.InlineKeyboardMarkup(buttons))
        self.suggestion_handler.conversations[storage_id] = Flags.SUGGEST_RECIPIENT

    def suggested_recipient(self, bot, update: telegram.Update):
        chat_id = update.effective_chat.id
        msg_id = update.effective_message.message_id
        param = update.callback_query.data
        storage_id = (chat_id, msg_id)
        if param.startswith("chat "):
            update = self.msg_storage[storage_id].update
            chat = self.msg_storage[storage_id].candidates[int(param.split(' ', 1)[1])]
            chat = ETMChat(chat=self.get_chat_from_db(*utils.chat_id_str_to_id(chat)), db=self.db)
            self.channel.master_messages.process_telegram_message(bot, update, channel_id=chat.channel_id,
                                                                  chat_id=chat.chat_uid)
            self.bot.edit_message_text(text=self._("Delivering the message to {0}").format(chat.full_name),
                                       chat_id=chat_id,
                                       message_id=msg_id)
        elif param == Flags.CANCEL_PROCESS:
            self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                                   "Please reply to a previous message."),
                                       chat_id=chat_id,
                                       message_id=msg_id)
        else:
            self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                                   "Please reply to a previous message.\n\n"
                                                   "Invalid parameter ({0}).").format(param),
                                       chat_id=chat_id,
                                       message_id=msg_id)
        return ConversationHandler.END

    def update_group_info(self, bot: telegram.Bot, update: telegram.Update):
        """
        Update the title and profile picture of singly-linked Telegram group
        according to the linked remote chat.
        """
        if update.effective_chat.id == self.bot.get_me().id:
            return self.bot.reply_error(update, self._('Send /update_info in a group where this bot is a group admin '
                                                       'to update group title and profile picture'))
        if update.effective_message.forward_from_chat and \
                update.effective_message.forward_from_chat.type == telegram.Chat.CHANNEL:
            tg_chat = update.effective_message.forward_from_chat.id
        else:
            tg_chat = update.effective_chat.id
        chats = self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(channel=self.channel,
                                                                       chat_uid=tg_chat))
        if len(chats) != 1:
            return self.bot.reply_error(update, self.ngettext('This only works in a group linked with one chat. '
                                                              'Currently {0} chat linked to this group.',
                                                              'This only works in a group linked with one chat. '
                                                              'Currently {0} chats linked to this group.',
                                                              len(chats)).format(len(chats)))
        picture = None
        pic_resized = None
        try:
            channel_id, chat_uid = utils.chat_id_str_to_id(chats[0])
            channel = coordinator.slaves[channel_id]
            chat = ETMChat(chat=channel.get_chat(chat_uid), db=self.db)
            bot.set_chat_title(tg_chat, chat.chat_title)
            picture = channel.get_chat_picture(chat)
            if not picture:
                raise EFBOperationNotSupported()
            pic_img = Image.open(picture)

            if pic_img.size[0] < self.TELEGRAM_MIN_PROFILE_PICTURE_SIZE or \
                    pic_img.size[1] < self.TELEGRAM_MIN_PROFILE_PICTURE_SIZE:
                # resize
                scale = self.TELEGRAM_MIN_PROFILE_PICTURE_SIZE / min(pic_img.size)
                pic_resized = io.BytesIO()
                pic_img.resize(tuple(map(lambda a: int(scale * a), pic_img.size)), Image.BICUBIC) \
                    .save(pic_resized, 'PNG')
                pic_resized.seek(0)

            picture.seek(0)

            bot.set_chat_photo(tg_chat, pic_resized or picture)
            update.message.reply_text(self._('Chat information updated.'))
        except KeyError:
            return self.bot.reply_error(update, self._('Channel linked is not found.'))
        except EFBChatNotFound:
            return self.bot.reply_error(update, self._('Chat linked is not found in channel.'))
        except telegram.TelegramError as e:
            return self.bot.reply_error(update, self._('Error occurred while update chat information.\n'
                                                       '{0}'.format(e.message)))
        except Exception as e:
            return self.bot.reply_error(update, self._('Error occurred while update chat information. \n'
                                                       '{0}'.format(e)))
        except EFBOperationNotSupported:
            return self.bot.reply_error(update, self._('No profile picture provided from this chat.'))
        finally:
            if getattr(picture, 'close', None):
                picture.close()
            if getattr(pic_resized, 'close', None):
                pic_resized.close()
