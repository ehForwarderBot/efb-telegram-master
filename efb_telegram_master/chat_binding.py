# coding=utf-8

import html
import io
import logging
import re
import urllib.parse
from typing import Tuple, Dict, Optional, List, TYPE_CHECKING, IO, Sequence, Union, Pattern

import telegram
from PIL import Image
from telegram import Update, Message, Chat
from telegram.ext import ConversationHandler, CommandHandler, CallbackQueryHandler, CallbackContext, Filters, \
    MessageHandler

from ehforwarderbot import coordinator, EFBChat, EFBChannel
from ehforwarderbot.constants import ChatType
from ehforwarderbot.exceptions import EFBChatNotFound, EFBOperationNotSupported
from ehforwarderbot.types import ModuleID, ChatID
from . import utils
from .chat import ETMChat
from .constants import Emoji, Flags
from .locale_mixin import LocaleMixin
from .message import ETMMsg
from .utils import EFBChannelChatIDStr, TelegramChatID, TelegramMessageID

if TYPE_CHECKING:
    from . import TelegramChannel
    from .bot_manager import TelegramBotManager
    from .chat_object_cache import ChatObjectCacheManager
    from .db import DatabaseManager

__all__ = ['ChatBindingManager']


class ChatListStorage:
    """
    Storage for list of chats displayed in a message as inline buttons.

    Attributes:
        chats (List[ETMChat]): List of chats to display
        channels (Dict[str, EFBChannel]): List of channels involved
        offset (int): Current offset to display
    """

    def __init__(self, chats: List[ETMChat], offset: int = 0):
        self.__chats: List[ETMChat] = []
        self.channels: Dict[ModuleID, EFBChannel] = dict()
        self.chats = chats.copy()  # initialize chats with setter.
        self.offset: int = offset
        self.update: Optional[telegram.Update] = None
        self.candidates: Optional[List[EFBChannelChatIDStr]] = None

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
            if i.module_id not in self.channels:
                self.channels[i.module_id] = coordinator.slaves[i.module_id]

    def set_chat_suggestion(self, update: telegram.Update,
                            candidates: List[EFBChannelChatIDStr]):
        """Set suggested chats of a message without recipient indicated."""
        self.update = update
        self.candidates = candidates


class ChatBindingManager(LocaleMixin):
    """
    Manages chat bindings (links), generation of chat heads, and chat recipient suggestion.
    """

    # Message storage
    msg_storage: Dict[Tuple[TelegramChatID, TelegramMessageID], ChatListStorage] = dict()
    logger: logging.Logger = logging.getLogger(__name__)

    # Consts
    TELEGRAM_MIN_PROFILE_PICTURE_SIZE = 256
    MAX_LEN_CHAT_TITLE = 255
    MAX_LEN_CHAT_DESC = 255

    def __init__(self, channel: 'TelegramChannel'):
        self.channel: 'TelegramChannel' = channel
        self.bot: 'TelegramBotManager' = channel.bot_manager
        self.db: 'DatabaseManager' = channel.db
        self.chat_manager: 'ChatObjectCacheManager' = channel.chat_manager

        # Link handler
        non_edit_filter = Filters.update.message | Filters.update.channel_post
        self.bot.dispatcher.add_handler(
            CommandHandler("link", self.link_chat_show_list, filters=non_edit_filter))
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
        self.bot.dispatcher.add_handler(
            CommandHandler("chat", self.start_chat_list, filters=non_edit_filter))
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
            states={Flags.SUGGEST_RECIPIENTS: [CallbackQueryHandler(self.suggested_recipient)]},
            fallbacks=[CallbackQueryHandler(self.bot.session_expired)],
            per_message=True,
            per_chat=True,
            per_user=False
        )

        self.bot.dispatcher.add_handler(self.suggestion_handler)

        # Update group title and profile picture
        self.bot.dispatcher.add_handler(CommandHandler('update_info', self.update_group_info))

        self.bot.dispatcher.add_handler(
            MessageHandler(Filters.status_update.migrate, self.chat_migration))

    def link_chat_show_list(self, update: Update, context: CallbackContext):
        """
        Show the list of available chats for linking.
        Triggered by `/link`.

        When triggered in private chat, it shows all chats available,
        or list of remote chats linked to the group otherwise.
        If no chat is linked to this group, then the bot messages
        the full list privately.
        """
        args = context.args or []
        message: Message = update.effective_message

        # Send link confirmation message when replying to a Telegram message
        # that is recorded in database.
        if message.reply_to_message:
            rtm: Message = message.reply_to_message
            msg_log = self.db.get_msg_log(
                master_msg_id=utils.message_id_to_str(
                    chat_id=rtm.chat_id, message_id=rtm.message_id))
            if msg_log and msg_log.pickle:
                chat: ETMChat = ETMMsg.unpickle(msg_log.pickle, chat_manager=self.chat_manager).chat
                tg_chat_id = message.chat_id
                tg_msg_id = message.reply_text(self._("Processing...")).message_id
                storage_id = (tg_chat_id, tg_msg_id)
                self.link_handler.conversations[storage_id] = Flags.LINK_EXEC
                self.msg_storage[storage_id] = ChatListStorage([chat])
                return self.build_link_action_message(chat, tg_chat_id, tg_msg_id)

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

    def slave_chats_pagination(self, storage_id: Tuple[TelegramChatID, TelegramMessageID],
                               offset: int = 0,
                               pattern: Optional[str] = "",
                               source_chats: Optional[List[EFBChannelChatIDStr]] = None) \
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
            self._("{0}: User").format(Emoji.USER),
            self._("{0}: Group").format(Emoji.GROUP),
        ]

        chat_list: Optional[ChatListStorage] = self.msg_storage.get(storage_id, None)

        if chat_list is None or chat_list.length == 0:
            # Generate the full chat list first
            re_filter: Union[str, Pattern, None] = None
            if pattern:
                self.logger.debug("Filter pattern: %s", pattern)
                escaped_pattern = re.escape(pattern)
                # Use simple string match if no regex significance is found.
                if pattern == escaped_pattern:
                    re_filter = pattern
                else:
                    # Use simple string match if regex provided is invalid
                    try:
                        re_filter = re.compile(pattern, re.DOTALL | re.IGNORECASE)
                    except re.error:
                        re_filter = pattern
            chats: List[ETMChat] = []
            if source_chats:
                for s_chat in source_chats:
                    channel_id, chat_uid = utils.chat_id_str_to_id(s_chat)
                    try:
                        coordinator.get_module_by_id(channel_id)
                    except NameError:
                        continue
                    chat = self.chat_manager.get_chat(channel_id, chat_uid)
                    if not chat:
                        self.logger.debug("slave_chats_pagination with chat list: Chat %s not found.", s_chat)
                        continue
                    if chat.match(re_filter):
                        chats.append(chat)
            else:
                for etm_chat in self.chat_manager.all_chats:
                    if etm_chat.match(re_filter):
                        chats.append(etm_chat)

            chats.sort(key=lambda a: a.last_message_time, reverse=True)
            chat_list = self.msg_storage[storage_id] = ChatListStorage(chats, offset)

        # self._db_update_slave_chats_cache(chat_list.chats)

        for ch in chat_list.channels.values():
            legend.append(f"{ch.channel_emoji}: {ch.channel_name}")

        # Build inline button list
        chat_btn_list: List[List[telegram.InlineKeyboardButton]] = []
        chats_per_page = self.channel.flag("chats_per_page")
        for idx in range(offset, min(offset + chats_per_page, chat_list.length)):
            chat = chat_list.chats[idx]
            # TODO: Remove code for muted chats.
            if chat.muted:
                mode = Emoji.MUTED
            elif chat.linked:
                mode = Emoji.LINK
            else:
                mode = ""
            chat_type = Emoji.get_source_emoji(chat.chat_type)
            chat_name = chat.long_name
            button_text = f"{chat.channel_emoji}{chat_type}{mode}: {chat_name}"
            button_callback = f"chat {idx}"
            chat_btn_list.append([telegram.InlineKeyboardButton(button_text, callback_data=button_callback)])

        # Pagination
        page_number_row: List[telegram.InlineKeyboardButton] = []

        if offset - chats_per_page >= 0:
            page_number_row.append(telegram.InlineKeyboardButton(self._("< Prev"),
                                                                 callback_data=f"offset {offset - chats_per_page}"))
        page_number_row.append(telegram.InlineKeyboardButton(self._("Cancel"),
                                                             callback_data=Flags.CANCEL_PROCESS))
        if offset + chats_per_page < chat_list.length:
            page_number_row.append(telegram.InlineKeyboardButton(self._("Next >"),
                                                                 callback_data=f"offset {offset + chats_per_page}"))
        chat_btn_list.append(page_number_row)

        return legend, chat_btn_list

    def _db_update_slave_chats_cache(self, chats: Sequence[EFBChat]):
        """
        Update all slave chats info cache to database. Triggered by retrieving
        the entire list of chats from all slaves by the method `slave_chats_pagination`.

        Args:
            chats: List of chats generated
        """
        for i in chats:
            self.db.add_task(self.db.set_slave_chat_info, tuple(), {'chat_object': i})

    def link_chat_gen_list(self, chat_id: TelegramChatID,
                           message_id: TelegramMessageID = None, offset: int = 0,
                           pattern: str = "", chats: List[EFBChannelChatIDStr] = None):
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

        if message_id is None:
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

    def link_chat_confirm(self, update: Update, context: CallbackContext) -> int:
        """
        Confirmation of chat linking. Triggered by callback message on status `Flags.CONFIRM_LINK`.

        A part of ``/link`` conversation handler.

        Returns:
            int: Next status
        """

        tg_chat_id = TelegramChatID(update.effective_chat.id)
        tg_msg_id = TelegramMessageID(update.effective_message.message_id)
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

        callback_idx: int = int(callback_uid.split()[1])
        chat: ETMChat = self.msg_storage[(tg_chat_id, tg_msg_id)].chats[callback_idx]

        self.build_link_action_message(chat, tg_chat_id, tg_msg_id)

        return Flags.LINK_EXEC

    def build_link_action_message(self, chat: ETMChat,
                                  tg_chat_id: TelegramChatID,
                                  tg_msg_id: TelegramMessageID):
        chat_display_name = chat.full_name
        self.msg_storage[(tg_chat_id, tg_msg_id)].chats = [chat]
        txt = self._("You've selected chat {0}.").format(html.escape(chat_display_name))
        # TODO: Remove code for muted chats.
        if chat.muted:
            txt += self._("\nThis chat is currently muted.")
        elif chat.linked:
            txt += self._("\nThis chat has already linked to Telegram.")
        txt += self._("\nWhat would you like to do?\n\n"
                      "<i>* If the link button doesn't work for you, please try to link manually.</i>")
        link_url = f"https://telegram.me/{self.bot.me.username}?" \
                   f"startgroup={urllib.parse.quote(utils.b64en(utils.message_id_to_str(tg_chat_id, tg_msg_id)))}"
        self.logger.debug("Telegram start trigger for linking chat: %s", link_url)
        if chat.linked:
            btn_list = [telegram.InlineKeyboardButton(self._("Relink"), url=link_url),
                        telegram.InlineKeyboardButton(self._("Restore"), callback_data="unlink 0")]
        else:
            btn_list = [telegram.InlineKeyboardButton(self._("Link"), url=link_url)]
        btn_list.append(telegram.InlineKeyboardButton(self._("Manual {link_or_relink}")
                                                      .format(link_or_relink=btn_list[0].text),
                                                      callback_data="manual_link 0"))
        buttons = [btn_list,
                   [telegram.InlineKeyboardButton("Cancel", callback_data=Flags.CANCEL_PROCESS)]]

        self.bot.edit_message_text(text=txt,
                                   chat_id=tg_chat_id,
                                   message_id=tg_msg_id,
                                   reply_markup=telegram.InlineKeyboardMarkup(buttons),
                                   parse_mode='HTML')

    def link_chat_exec(self, update: Update, context: CallbackContext) -> int:
        """
        Action to link a chat. Triggered by callback message with status `Flags.EXEC_LINK`.
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
            txt = self._('Chat {} is restored.').format(chat_display_name)
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
                                       reply_markup=telegram.InlineKeyboardMarkup(
                                           [[telegram.InlineKeyboardButton(self._("Cancel"),
                                                                           callback_data=Flags.CANCEL_PROCESS)]]),
                                       parse_mode='HTML')
            return Flags.LINK_EXEC
        else:
            txt = self._("Command ‘{command}’ ({query}) is not recognised, please try again.") \
                .format(command=cmd, query=callback_uid)
            self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
        self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
        return ConversationHandler.END

    def link_chat(self, update, args):
        """Actual code of linking a chat by manipulating database.
        Triggered by ``/start BASE64(msg_id_to_str(chat_id, msg_id))``.
        """
        try:
            msg_id = utils.message_id_str_to_id(utils.b64de(args[0]))
            storage_key: Tuple[int, int] = (int(msg_id[0]), int(msg_id[1]))
            data = self.msg_storage[storage_key]
        except KeyError:
            return update.message.reply_text(self._("Session expired or unknown parameter. (SE02)"))
        chat: ETMChat = data.chats[0]
        chat_display_name = chat.full_name
        slave_channel, slave_chat_uid = chat.module_id, chat.chat_uid
        try:
            coordinator.get_module_by_id(slave_channel)
        except NameError:
            self.bot.edit_message_text(
                text=self._("{module_id} is not activated in current profile. "
                            "It cannot be linked.").format(module_id=slave_channel),
                chat_id=storage_key[0],
                message_id=storage_key[1])

        # Use channel ID if command is forwarded from a channel.
        forwarded_chat: Chat = update.effective_message.forward_from_chat
        if forwarded_chat and forwarded_chat.type == telegram.Chat.CHANNEL:
            tg_chat_to_link = forwarded_chat.id
        else:
            tg_chat_to_link = update.effective_chat.id

        txt = self._('Trying to link chat {0}...').format(chat_display_name)
        msg = self.bot.send_message(tg_chat_to_link, text=txt)

        # TODO: remove mute related code
        if chat.muted:
            chat.unlink()

        chat.link(self.channel.channel_id, tg_chat_to_link, self.channel.flag("multiple_slave_chats"))

        txt = self._("Chat {0} is now linked.").format(chat_display_name)
        self.bot.edit_message_text(text=txt, chat_id=msg.chat.id, message_id=msg.message_id)

        self.bot.edit_message_text(chat_id=storage_key[0],
                                   message_id=storage_key[1],
                                   text=txt)
        # TODO: show error message on the ``else`` case.
        self.msg_storage.pop(storage_key, None)

    def unlink_all(self, update: Update, context: CallbackContext):
        """
        Unlink all chats linked to the telegram group.
        Triggered by `/unlink_all`.
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
            forwarded_chat = update.effective_message.forward_from_chat
            if forwarded_chat and forwarded_chat.type == telegram.Chat.CHANNEL:
                links = self.db.get_chat_assoc(
                    master_uid=utils.chat_id_to_str(self.channel.channel_id, forwarded_chat.id))

                if len(links) < 1:
                    return self.bot.send_message(update.message.chat.id, self._("No chat is linked to the channel."),
                                                 reply_to_message_id=update.message.message_id)
                else:
                    self.db.remove_chat_assoc(
                        master_uid=utils.chat_id_to_str(self.channel.channel_id, forwarded_chat.id))
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

    def start_chat_list(self, update: Update, context: CallbackContext):
        """
        Send a list to for chat list generation.
        Triggered by `/chat`.
        """
        args = context.args or []
        chats = None
        if update.message.chat.type != Chat.PRIVATE:
            chats = self.db.get_chat_assoc(
                master_uid=utils.chat_id_to_str(self.channel.channel_id, update.message.chat_id))
            chats = chats or None
        if chats:
            target = update.message.chat_id
        else:
            target = update.message.from_user.id
        return self.chat_head_req_generate(target, pattern=" ".join(args), chats=chats)

    def chat_head_req_generate(self, chat_id: TelegramChatID,
                               message_id: TelegramMessageID = None,
                               offset: int = 0, pattern: str = "",
                               chats: List[EFBChannelChatIDStr] = None):
        """
        Generate the list for chat head, and update it to a message.

        Args:
            chat_id: Chat ID
            message_id: ID of message to be updated, None to send a new message.
            offset: Offset for pagination.
            pattern: Regex String used as a filter.
            chats: Specified list of chats to start a chat head.
        """
        if message_id is None:
            message_id = self.bot.send_message(chat_id, text=self._("Processing...")).message_id
        self.bot.send_chat_action(chat_id, telegram.ChatAction.TYPING)

        if chats and len(chats):
            if len(chats) == 1:
                slave_channel_id, slave_chat_id = utils.chat_id_str_to_id(chats[0])
                # TODO: Channel might be gone, add a check here.
                chat: ETMChat = self.chat_manager.get_chat(slave_channel_id, slave_chat_id)
                if chat:
                    msg_text = self._('This group is linked to {0}'
                                      'Send a message to this group to deliver it to the chat.\n'
                                      'Do NOT reply to this system message.').format(chat.full_name)

                else:
                    try:
                        channel = coordinator.get_module_by_id(slave_channel_id)
                        msg_text = self._("This group is linked to an unknown chat ({chat_id}) "
                                          "on channel {channel_name} ({channel_id}). Possibly you can "
                                          "no longer reach this chat. Send /unlink_all to unlink all chats "
                                          "from this group.").format(channel_name=channel.module_name,
                                                                     channel_id=slave_channel_id,
                                                                     chat_id=slave_chat_id)
                    except NameError:
                        msg_text = self._("This group is linked to a chat from a channel that is not activated "
                                          "({channel_id}, {chat_id}). You cannot reach this chat unless the channel is "
                                          "enabled. Send /unlink_all to unlink all chats "
                                          "from this group.").format(channel_id=slave_channel_id,
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
            msg_text += f"{i}\n"
        self.bot.edit_message_text(text=msg_text,
                                   chat_id=chat_id,
                                   message_id=message_id,
                                   reply_markup=telegram.InlineKeyboardMarkup(chat_btn_list))

        self.chat_head_handler.conversations[(chat_id, message_id)] = Flags.CHAT_HEAD_CONFIRM

    def make_chat_head(self, update: Update, context: CallbackContext) -> int:
        """
        Create a chat head. Triggered by callback message with status `Flags.CHAT_HEAD_CONFIRM`.

        This message is a part of the ``/chat`` conversation handler.
        """
        tg_chat_id = update.effective_chat.id
        tg_msg_id = update.effective_message.message_id
        callback_uid: str = update.callback_query.data

        # Refresh with a new set of pages
        if callback_uid.split()[0] == "offset":
            return self.chat_head_req_generate(tg_chat_id, message_id=tg_msg_id,
                                               offset=int(callback_uid.split()[1]))
        if callback_uid == Flags.CANCEL_PROCESS:
            txt = self._("Cancelled.")
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            return ConversationHandler.END

        if not callback_uid.startswith("chat "):
            # Invalid command
            txt = self._("Invalid command. ({0})").format(callback_uid)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            return ConversationHandler.END

        callback_idx = int(callback_uid.split()[1])
        chat: ETMChat = self.msg_storage[(tg_chat_id, tg_msg_id)].chats[callback_idx]
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

    def register_suggestions(self, update: telegram.Update,
                             candidates: List[EFBChannelChatIDStr],
                             chat_id: TelegramChatID, message_id: TelegramMessageID):
        storage_id = (chat_id, message_id)
        legends, buttons = self.channel.chat_binding.slave_chats_pagination(
            storage_id, 0, source_chats=candidates)
        if len(buttons) <= 1:
            # Stop editing the message as no valid suggestion is available.
            # Remove message from cache and return
            del self.msg_storage[storage_id]
            return
        self.msg_storage[storage_id].set_chat_suggestion(update, candidates)
        self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                               "Please reply to a previous message, "
                                               "or choose a recipient:\n\nLegend:\n") + "\n".join(legends),
                                   chat_id=chat_id, message_id=message_id,
                                   reply_markup=telegram.InlineKeyboardMarkup(buttons))
        self.suggestion_handler.conversations[storage_id] = Flags.SUGGEST_RECIPIENTS

    def suggested_recipient(self, update: Update, context: CallbackContext):
        """Send the message to selected recipient among all suggested when a
        message is sent with unspecified recipient.

        Triggered by flag ``SUGGEST_RECIPIENTS``.
        """
        chat_id = update.effective_chat.id
        msg_id = update.effective_message.message_id
        param = update.callback_query.data
        storage_id = (chat_id, msg_id)
        if param.startswith("chat "):
            if storage_id not in self.msg_storage:
                self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                                       "Please reply to a previous message.\n\n"
                                                       "Session expired, please try again."),
                                           chat_id=chat_id,
                                           message_id=msg_id)
            update = self.msg_storage[storage_id].update
            candidates = self.msg_storage[storage_id].candidates
            if candidates is None:
                self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                                       "Please reply to a previous message.\n\n"
                                                       "Session expired, please try again."),
                                           chat_id=chat_id,
                                           message_id=msg_id)
            slave_chat_id = candidates[int(param.split(' ', 1)[1])]
            chat = self.chat_manager.get_chat(*utils.chat_id_str_to_id(slave_chat_id))
            self.channel.master_messages.process_telegram_message(update, context, channel_id=chat.module_id,
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
        del self.msg_storage[storage_id]
        return ConversationHandler.END

    def update_group_info(self, update: Update, context: CallbackContext):
        """
        Update the title and profile picture of singly-linked Telegram group
        according to the linked remote chat.

        Triggered by ``/update_info`` command.
        """
        if update.effective_chat.type == Chat.PRIVATE:
            return self.bot.reply_error(update, self._('Send /update_info in a group where this bot is a group admin '
                                                       'to update group title and profile picture.'))
        forwarded_from_chat = update.effective_message.forward_from_chat
        if forwarded_from_chat and forwarded_from_chat.type == Chat.CHANNEL:
            tg_chat = forwarded_from_chat.id
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
        picture: Optional[IO] = None
        pic_resized: Optional[IO] = None
        channel_id, chat_uid = utils.chat_id_str_to_id(chats[0])
        if channel_id not in coordinator.slaves:
            self.logger.exception(f"Channel linked ({channel_id}) is not found.")
            return self.bot.reply_error(update, self._('Channel linked ({channel}) is not found.')
                                        .format(channel=channel_id))
        channel = coordinator.slaves[channel_id]
        try:
            chat = self.chat_manager.update_chat_obj(channel.get_chat(chat_uid), full_update=True)

            self.bot.set_chat_title(tg_chat, self.truncate_ellipsis(chat.chat_title, self.MAX_LEN_CHAT_TITLE))

            # Update remote group members list to Telegram group description if available
            # TODO: Add chat bio too when it’s available in the framework
            if chat.members:
                # TRANSLATORS: Separator between group members in a Telegram group description generated by /update_info
                desc = self._(", ").join(i.long_name for i in chat.members)
                desc = self.ngettext("{count} group member: {list}",
                                     "{count} group members: {list}").format(
                    len(chat.members), desc
                )
                self.bot.set_chat_description(tg_chat,
                                              self.truncate_ellipsis(desc, self.MAX_LEN_CHAT_DESC))

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

            self.bot.set_chat_photo(tg_chat, pic_resized or picture)
            update.message.reply_text(self._('Chat details updated.'))
        except EFBChatNotFound:
            self.logger.exception("Chat linked (%s) is not found in the slave channel "
                                  "(%s).", channel_id, chat_uid)
            return self.bot.reply_error(update, self._("Chat linked ({chat_uid}) is not found in the slave channel "
                                                       "({channel_name}, {channel_id}).")
                                        .format(channel_name=channel.channel_name, channel_id=channel_id,
                                                chat_uid=chat_uid))
        except telegram.TelegramError as e:
            self.logger.exception("Error occurred while update chat details.")
            return self.bot.reply_error(update, self._('Error occurred while update chat details.\n'
                                                       '{0}'.format(e.message)))
        except EFBOperationNotSupported:
            return self.bot.reply_error(update, self._('No profile picture provided from this chat.'))
        except Exception as e:
            self.logger.exception("Unknown error caught when querying chat.")
            return self.bot.reply_error(update, self._('Error occurred while update chat details. \n'
                                                       '{0}'.format(e)))
        finally:
            if picture and getattr(picture, 'close', None):
                picture.close()
            if pic_resized and getattr(pic_resized, 'close', None):
                pic_resized.close()

    def chat_migration(self, update: Update, context: CallbackContext):
        """Triggered by any message update with either
        ``migrate_from_chat_id`` or ``migrate_to_chat_id``
        or both (which shouldn’t happen).
        """
        message = update.effective_message
        if message.migrate_from_chat_id is not None:
            from_id = ChatID(message.migrate_from_chat_id)
            to_id = ChatID(message.chat.id)
        elif message.migrate_to_chat_id is not None:
            from_id = ChatID(message.chat.id)
            to_id = ChatID(message.migrate_to_chat_id)
        else:
            # Per ptb filter specs, this part of code should not be reached.
            return
        from_str = utils.chat_id_to_str(self.channel.channel_id, from_id)
        to_str = utils.chat_id_to_str(self.channel.channel_id, to_id)
        for i in self.db.get_chat_assoc(master_uid=from_str):
            self.db.add_chat_assoc(master_uid=to_str, slave_uid=i)
        self.db.remove_chat_assoc(master_uid=from_str)

    @staticmethod
    def truncate_ellipsis(text: str, length: int) -> str:
        """Truncate a string with ellipsis added to the end if needed."""
        if len(text) <= length:
            return text
        return text[:length - 1] + "…"
