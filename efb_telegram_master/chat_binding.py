# coding=utf-8

import html
import io
import logging
import re
import urllib.parse
from contextlib import suppress
from typing import Tuple, Dict, Optional, List, TYPE_CHECKING, IO, Union, Pattern

import telegram  # lgtm [py/import-and-import-from]
from PIL import Image
from telegram import Update, Message, TelegramError, InlineKeyboardButton, ChatAction, InlineKeyboardMarkup, \
    ParseMode
from telegram.error import BadRequest
from telegram.ext import ConversationHandler, CommandHandler, CallbackQueryHandler, CallbackContext, Filters, \
    MessageHandler

from ehforwarderbot import coordinator, Channel, MsgType
from ehforwarderbot.channel import SlaveChannel
from ehforwarderbot.chat import SystemChatMember
from ehforwarderbot.exceptions import EFBChatNotFound, EFBOperationNotSupported
from ehforwarderbot.types import ModuleID, ChatID, MessageID
from . import utils
from .chat import ETMChatType, ETMGroupChat
from .constants import Emoji, Flags
from .locale_mixin import LocaleMixin
from .message import ETMMsg
from .msg_type import TGMsgType
from .utils import EFBChannelChatIDStr, TelegramChatID, TelegramMessageID, TgChatMsgIDStr

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
        channels (Dict[str, SlaveChannel]): List of channels involved
        offset (int): Current offset to display
    """

    def __init__(self, chats: List[ETMChatType], offset: int = 0):
        self.__chats: List[ETMChatType] = []
        self.channels: Dict[ModuleID, SlaveChannel] = dict()
        self.chats = chats.copy()  # initialize chats with setter.
        self.offset: int = offset
        self.update: Optional[Update] = None
        self.candidates: Optional[List[EFBChannelChatIDStr]] = None

    @property
    def length(self) -> int:
        return len(self.chats)

    @property
    def chats(self) -> List[ETMChatType]:
        return self.__chats

    @chats.setter
    def chats(self, value: List[ETMChatType]):
        self.__chats = value
        self.channels = dict()
        for i in value:
            if i.module_id not in self.channels and i.module_id in coordinator.slaves:
                self.channels[i.module_id] = coordinator.slaves[i.module_id]

    def set_chat_suggestion(self, update: Update):
        """Set suggestion message without recipient indicated."""
        assert isinstance(update, Update)
        self.update = update


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

    def pre_link_check(self, message: Message):
        """Check if the bot would work properly in a linked group.
        If potential error is found, reply error messages to the user.

        Args:
            message: /link command message.
        """
        err_msg = []

        # self.bot.me is not refreshed after startup, need to refresh it here
        # to check if user has updated the setting with bot father.
        # Assuming user will not revert the settings back.

        # Refresh bot status if any of the settings is not enabled.
        if not self.bot.me.can_join_groups or not self.bot.me.can_read_all_group_messages:
            self.bot.me = self.bot.get_me()

        if not self.bot.me.can_join_groups:
            err_msg.append(self._(
                "This bot cannot join groups. "
                "Chat linking might not work properly. "
                "Please enable this setting with @BotFather."
            ))
        if not self.bot.me.can_read_all_group_messages:
            err_msg.append(self._(
                "This bot cannot read all messages in a group chat. "
                "Message delivery in linked groups might not work properly. "
                "Please adjust my privacy settings with @BotFather."
            ))

        if err_msg:
            message.reply_text("\n".join(err_msg))

    def link_chat_show_list(self, update: Update, context: CallbackContext):
        """
        Show the list of available chats for linking.
        Triggered by `/link`.

        When triggered in private chat, it shows all chats available,
        or list of remote chats linked to the group otherwise.
        If no chat is linked to this group, then the bot messages
        the full list privately.
        """
        assert isinstance(update, Update)
        assert update.effective_message

        args = context.args or []
        message: Message = update.effective_message

        # Perform pre-link check
        self.pre_link_check(message)

        # Send link confirmation message when replying to a Telegram message
        # that is recorded in database.
        if message.reply_to_message:
            rtm: Message = message.reply_to_message
            msg_log = self.db.get_msg_log(
                master_msg_id=utils.message_id_to_str(
                    chat_id=TelegramChatID(rtm.chat_id),
                    message_id=TelegramMessageID(rtm.message_id)
                )
            )
            if msg_log:
                channel_id, chat_id, _ = utils.chat_id_str_to_id(msg_log.slave_origin_uid)
                chat: ETMChatType = self.chat_manager.get_chat(channel_id, chat_id, build_dummy=True)
                tg_chat_id = TelegramChatID(message.chat_id)
                tg_msg_id = TelegramMessageID(message.reply_text(self._("Processing...")).message_id)
                storage_id: Tuple[TelegramChatID, TelegramMessageID] = (tg_chat_id, tg_msg_id)
                self.link_handler.conversations[storage_id] = Flags.LINK_EXEC
                self.msg_storage[storage_id] = ChatListStorage([chat])
                return self.build_link_action_message(chat, tg_chat_id, tg_msg_id)

        if message.chat.type != telegram.Chat.PRIVATE:
            links = self.db.get_chat_assoc(
                master_uid=utils.chat_id_to_str(self.channel.channel_id, ChatID(str(message.chat.id))))
            if links:
                return self.link_chat_gen_list(TelegramChatID(message.chat.id), pattern=" ".join(args),
                                               chats=links, filter_availability=False)
        elif message.forward_from_chat and \
                message.forward_from_chat.type == telegram.Chat.CHANNEL:
            chat_id = ChatID(str(message.forward_from_chat.id))
            links = self.db.get_chat_assoc(
                master_uid=utils.chat_id_to_str(self.channel.channel_id, chat_id))
            if links:
                return self.link_chat_gen_list(TelegramChatID(message.chat.id),
                                               pattern=" ".join(args),
                                               chats=links, filter_availability=False)
        assert message.from_user
        return self.link_chat_gen_list(TelegramChatID(message.from_user.id), pattern=" ".join(args))

    def slave_chats_pagination(self, storage_id: Tuple[TelegramChatID, TelegramMessageID],
                               offset: int = 0,
                               pattern: Optional[str] = "",
                               source_chats: Optional[List[EFBChannelChatIDStr]] = None,
                               filter_availability: bool = True) \
            -> Tuple[List[str], List[List[InlineKeyboardButton]]]:
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
            filter_availability (bool): Whether to filter chats based on the availabilities.
                Only works when ``source_chats`` is specified.

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
            chats: List[ETMChatType] = []
            if source_chats:
                for s_chat in source_chats:
                    channel_id, chat_uid, _ = utils.chat_id_str_to_id(s_chat)
                    with suppress(NameError):
                        coordinator.get_module_by_id(channel_id)
                    chat = self.chat_manager.get_chat(channel_id, chat_uid, build_dummy=not filter_availability)
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
        chat_btn_list: List[List[InlineKeyboardButton]] = []
        chats_per_page = self.channel.flag("chats_per_page")
        for idx in range(offset, min(offset + chats_per_page, chat_list.length)):
            chat = chat_list.chats[idx]
            if chat.linked:
                mode = Emoji.LINK
            else:
                mode = ""
            chat_type = chat.chat_type_emoji
            chat_name = chat.long_name
            button_text = f"{chat.channel_emoji}{chat_type}{mode}: {chat_name}"
            button_callback = f"chat {idx}"
            chat_btn_list.append([InlineKeyboardButton(button_text, callback_data=button_callback)])

        # Pagination
        page_number_row: List[InlineKeyboardButton] = []

        if offset - chats_per_page >= 0:
            page_number_row.append(InlineKeyboardButton(self._("< Prev"),
                                                        callback_data=f"offset {offset - chats_per_page}"))
        page_number_row.append(InlineKeyboardButton(self._("Cancel"),
                                                    callback_data=Flags.CANCEL_PROCESS))
        if offset + chats_per_page < chat_list.length:
            page_number_row.append(InlineKeyboardButton(self._("Next >"),
                                                        callback_data=f"offset {offset + chats_per_page}"))
        chat_btn_list.append(page_number_row)

        return legend, chat_btn_list

    def link_chat_gen_list(self, chat_id: TelegramChatID,
                           message_id: TelegramMessageID = None, offset: int = 0,
                           pattern: str = "", chats: List[EFBChannelChatIDStr] = None,
                           filter_availability: bool = True):
        """
        Generate the list for chat linking, and update it to a message.

        Args:
            chat_id: Chat ID
            message_id: ID of message to be updated, None to send a new message.
            offset: Offset for pagination.
            pattern (str): Regex expression to filter chats.
            chats (List[str]): Specified chats to link
            filter_availability (bool): Whether to show only chats that are available.
                Only works when ``chats`` are specified.

        Returns:
            int: The next state
        """

        if message_id is None:
            message_id = self.bot.send_message(chat_id, self._("Processing...")).message_id
        self.bot.send_chat_action(chat_id, ChatAction.TYPING)
        if chats:
            msg_text = self._("This Telegram group is currently linked with...")
        else:
            msg_text = self._("Please choose the chat you want to link with...")
        msg_text += self._("\n\nLegend:\n")

        legend, chat_btn_list = self.slave_chats_pagination((chat_id, message_id),
                                                            offset,
                                                            pattern=pattern,
                                                            source_chats=chats,
                                                            filter_availability=filter_availability)
        for i in legend:
            msg_text += "%s\n" % i

        self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msg_text,
                                   reply_markup=InlineKeyboardMarkup(chat_btn_list))

        self.link_handler.conversations[(chat_id, message_id)] = Flags.LINK_CONFIRM

        return Flags.LINK_CONFIRM

    def link_chat_confirm(self, update: Update, context: CallbackContext) -> int:
        """
        Confirmation of chat linking. Triggered by callback message on status `Flags.CONFIRM_LINK`.

        A part of ``/link`` conversation handler.

        Returns:
            int: Next status
        """
        assert isinstance(update, Update)
        assert update.effective_chat
        assert update.effective_message
        assert update.callback_query
        assert update.callback_query.data

        tg_chat_id = TelegramChatID(update.effective_chat.id)
        tg_msg_id = TelegramMessageID(update.effective_message.message_id)
        callback_uid: str = update.callback_query.data
        if callback_uid.split()[0] == "offset":
            # Offer a new page of chats
            update.callback_query.answer()
            return self.link_chat_gen_list(tg_chat_id, message_id=tg_msg_id, offset=int(callback_uid.split()[1]))

        if callback_uid == Flags.CANCEL_PROCESS:
            # Terminate the process
            txt = self._("Cancelled.")
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            update.callback_query.answer()
            return ConversationHandler.END

        if callback_uid[:4] != "chat":
            # The only possible command now is "chat".
            txt = self._("Invalid parameter ({0}). (IP01)").format(callback_uid)
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            update.callback_query.answer()
            return ConversationHandler.END

        callback_idx: int = int(callback_uid.split()[1])
        chat: ETMChatType = self.msg_storage[(tg_chat_id, tg_msg_id)].chats[callback_idx]

        self.build_link_action_message(chat, tg_chat_id, tg_msg_id)

        update.callback_query.answer()
        return Flags.LINK_EXEC

    def build_link_action_message(self, chat: ETMChatType,
                                  tg_chat_id: TelegramChatID,
                                  tg_msg_id: TelegramMessageID):
        chat_display_name = chat.full_name
        self.msg_storage[(tg_chat_id, tg_msg_id)].chats = [chat]
        txt = self._("You've selected chat {0}.").format(html.escape(chat_display_name))
        if chat.linked:
            txt += self._("\nThis chat has already linked to Telegram.")
        txt += self._("\nWhat would you like to do?\n\n"
                      "<i>* If the link button doesn't work for you, please try to link manually.</i>")
        link_url = f"https://telegram.me/{self.bot.me.username}?" \
                   f"startgroup={urllib.parse.quote(utils.b64en(utils.message_id_to_str(tg_chat_id, tg_msg_id)))}"
        self.logger.debug("Telegram start trigger for linking chat: %s", link_url)
        if chat.linked:
            btn_list = [InlineKeyboardButton(self._("Relink"), url=link_url),
                        InlineKeyboardButton(self._("Restore"), callback_data="unlink 0")]
        else:
            btn_list = [InlineKeyboardButton(self._("Link"), url=link_url)]
        btn_list.append(InlineKeyboardButton(self._("Manual {link_or_relink}")
                                             .format(link_or_relink=btn_list[0].text),
                                             callback_data="manual_link 0"))
        buttons = [btn_list,
                   [InlineKeyboardButton(self._("Cancel"), callback_data=Flags.CANCEL_PROCESS)]]

        self.bot.edit_message_text(text=txt,
                                   chat_id=tg_chat_id,
                                   message_id=tg_msg_id,
                                   reply_markup=InlineKeyboardMarkup(buttons),
                                   parse_mode='HTML')

    def link_chat_exec(self, update: Update, context: CallbackContext) -> int:
        """
        Action to link a chat. Triggered by callback message with status `Flags.EXEC_LINK`.
        """
        assert isinstance(update, Update)
        assert update.effective_chat
        assert update.effective_message
        assert update.callback_query
        assert update.callback_query.data

        tg_chat_id = TelegramChatID(update.effective_chat.id)
        tg_msg_id = TelegramMessageID(update.effective_message.message_id)
        callback_uid = update.callback_query.data

        if callback_uid == Flags.CANCEL_PROCESS:
            txt = self._("Cancelled.")
            self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            update.callback_query.answer()
            return ConversationHandler.END

        cmd, chat_lid = callback_uid.split()
        chat: ETMChatType = self.msg_storage[(tg_chat_id, tg_msg_id)].chats[int(chat_lid)]
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
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton(self._("Cancel"),
                                                                  callback_data=Flags.CANCEL_PROCESS)]]),
                                       parse_mode='HTML')
            return Flags.LINK_EXEC
        else:
            txt = self._("Command ‘{command}’ ({query}) is not recognised, please try again.") \
                .format(command=cmd, query=callback_uid)
            self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
        update.callback_query.answer()
        self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
        return ConversationHandler.END

    def link_chat(self, update: Update, args: Optional[List[str]]):
        """Actual code of linking a chat by manipulating database.
        Triggered by ``/start BASE64(msg_id_to_str(chat_id, msg_id))``.
        """
        assert isinstance(update, Update)
        assert update.message
        assert update.effective_message
        assert update.effective_chat
        assert args

        try:
            msg_id = utils.message_id_str_to_id(TgChatMsgIDStr(utils.b64de(args[0])))
            storage_key = (TelegramChatID(int(msg_id[0])), TelegramMessageID(int(msg_id[1])))
            data = self.msg_storage[storage_key]
        except KeyError:
            return update.message.reply_text(self._("Session expired or unknown parameter. (SE02)"))
        chat: ETMChatType = data.chats[0]
        chat_display_name = chat.full_name
        slave_channel, slave_chat_uid = chat.module_id, chat.uid
        try:
            coordinator.get_module_by_id(slave_channel)
        except NameError:
            self.bot.edit_message_text(
                text=self._("{module_id} is not activated in current profile. "
                            "It cannot be linked.").format(module_id=slave_channel),
                chat_id=storage_key[0],
                message_id=storage_key[1])

        # Use channel ID if command is forwarded from a channel.
        forwarded_chat = update.effective_message.forward_from_chat
        if forwarded_chat and forwarded_chat.type == telegram.Chat.CHANNEL:
            tg_chat_to_link = forwarded_chat.id
        else:
            tg_chat_to_link = update.effective_chat.id

        txt = self._('Trying to link chat {0}...').format(chat_display_name)
        msg = self.bot.send_message(tg_chat_to_link, text=txt)

        chat.link(self.channel.channel_id, ChatID(str(tg_chat_to_link)), self.channel.flag("multiple_slave_chats"))

        txt = self._("Chat {0} is now linked.").format(chat_display_name)
        self.bot.edit_message_text(text=txt, chat_id=msg.chat.id, message_id=msg.message_id)

        self.bot.edit_message_text(chat_id=storage_key[0],
                                   message_id=storage_key[1],
                                   text=txt)
        self.msg_storage.pop(storage_key, None)

    def unlink_all(self, update: Update, context: CallbackContext):
        """
        Unlink all chats linked to the telegram group.
        Triggered by `/unlink_all`.
        """
        assert isinstance(update, Update)
        assert update.message

        if update.message.chat.type != telegram.Chat.PRIVATE:

            links = self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(self.channel.channel_id,
                                                                           ChatID(str(update.message.chat.id))))
            if len(links) < 1:
                return self.bot.send_message(update.message.chat.id, self._("No chat is linked to the group."),
                                             reply_to_message_id=update.message.message_id)
            else:
                self.db.remove_chat_assoc(master_uid=utils.chat_id_to_str(self.channel.channel_id,
                                                                          ChatID(str(update.message.chat.id))))
                return self.bot.send_message(update.message.chat.id,
                                             self.ngettext("All {0} chat has been unlinked from this group.",
                                                           "All {0} chats has been unlinked from this group.",
                                                           len(links)).format(len(links)),
                                             reply_to_message_id=update.message.message_id)
        else:
            forwarded_chat = update.message.forward_from_chat
            if forwarded_chat and forwarded_chat.type == telegram.Chat.CHANNEL:
                links = self.db.get_chat_assoc(
                    master_uid=utils.chat_id_to_str(self.channel.channel_id, ChatID(str(forwarded_chat.id))))

                if len(links) < 1:
                    return self.bot.send_message(update.message.chat.id, self._("No chat is linked to the channel."),
                                                 reply_to_message_id=update.message.message_id)
                else:
                    self.db.remove_chat_assoc(
                        master_uid=utils.chat_id_to_str(self.channel.channel_id, ChatID(str(forwarded_chat.id))))
                    return self.bot.send_message(update.message.chat.id,
                                                 self.ngettext("All {0} chat has been unlinked from this channel.",
                                                               "All {0} chats has been unlinked from this channel.",
                                                               len(links)).format(len(links)),
                                                 reply_to_message_id=update.message.message_id)
            else:
                return self.bot.send_message(update.message.chat.id,
                                             self._("Send `/unlink_all` to a group to unlink all remote chats "
                                                    "from it."),
                                             parse_mode=ParseMode.MARKDOWN,
                                             reply_to_message_id=update.message.message_id)

    def start_chat_list(self, update: Update, context: CallbackContext):
        """
        Send a list to for chat list generation.
        Triggered by `/chat`.
        """
        assert isinstance(update, Update)
        assert update.message

        args = context.args or []
        chats = None
        if update.message.chat.type != telegram.Chat.PRIVATE:
            chats = self.db.get_chat_assoc(
                master_uid=utils.chat_id_to_str(self.channel.channel_id, ChatID(str(update.message.chat_id)))
            )
            chats = chats or None
        if chats:
            target = TelegramChatID(update.message.chat_id)
        elif update.message.from_user:
            target = TelegramChatID(update.message.from_user.id)
        else:
            raise Exception("No target chat is found when generating chat list.")
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
        self.bot.send_chat_action(chat_id, ChatAction.TYPING)

        if chats and len(chats):
            if len(chats) == 1:
                slave_channel_id, slave_chat_id, _ = utils.chat_id_str_to_id(chats[0])
                # TODO: Channel might be gone, add a check here.
                chat = self.chat_manager.get_chat(slave_channel_id, slave_chat_id)
                if chat:
                    msg_text = self._('This group is linked to {0}. '
                                      'Send a message to this group to deliver it to the chat.\n'
                                      'Do NOT reply to this system message.').format(chat.full_name)

                else:
                    try:
                        channel = coordinator.get_module_by_id(slave_channel_id)
                        if isinstance(channel, Channel):
                            name = channel.channel_name
                        else:
                            name = channel.middleware_name
                        msg_text = self._("This group is linked to an unknown chat ({chat_id}) "
                                          "on channel {channel_name} ({channel_id}). Possibly you can "
                                          "no longer reach this chat. Send /unlink_all to unlink all chats "
                                          "from this group.").format(channel_name=name,
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
                                   reply_markup=InlineKeyboardMarkup(chat_btn_list))

        self.chat_head_handler.conversations[(chat_id, message_id)] = Flags.CHAT_HEAD_CONFIRM

    def make_chat_head(self, update: Update, context: CallbackContext) -> int:
        """
        Create a chat head. Triggered by callback message with status `Flags.CHAT_HEAD_CONFIRM`.

        This message is a part of the ``/chat`` conversation handler.
        """
        assert isinstance(update, Update)
        assert update.effective_chat
        assert update.effective_message
        assert update.callback_query
        assert update.callback_query.data

        tg_chat_id = TelegramChatID(update.effective_chat.id)
        tg_msg_id = TelegramMessageID(update.effective_message.message_id)
        callback_uid: str = update.callback_query.data

        # Refresh with a new set of pages
        if callback_uid.split()[0] == "offset":
            update.callback_query.answer()
            return self.chat_head_req_generate(tg_chat_id, message_id=tg_msg_id,
                                               offset=int(callback_uid.split()[1]))
        if callback_uid == Flags.CANCEL_PROCESS:
            txt = self._("Cancelled.")
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            update.callback_query.answer()
            return ConversationHandler.END

        if not callback_uid.startswith("chat "):
            # Invalid command
            txt = self._("Invalid command. ({0})").format(callback_uid)
            self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
            self.bot.edit_message_text(text=txt,
                                       chat_id=tg_chat_id,
                                       message_id=tg_msg_id)
            update.callback_query.answer()
            return ConversationHandler.END

        callback_idx = int(callback_uid.split()[1])
        chat: ETMChatType = self.msg_storage[(tg_chat_id, tg_msg_id)].chats[callback_idx]
        chat_display_name = chat.full_name
        self.msg_storage.pop((tg_chat_id, tg_msg_id), None)
        txt = self._("Reply to this message to chat with {0}.").format(chat_display_name)
        chat_head_etm = ETMMsg()
        chat_head_etm.chat = chat
        chat_head_etm.author = chat.self or chat.add_self()
        chat_head_etm.uid = MessageID("__chathead__")
        chat_head_etm.type = MsgType.Text
        chat_head_etm.text = txt
        chat_head_etm.type_telegram = TGMsgType.Text
        chat_head_etm.deliver_to = self.channel
        self.db.add_or_update_message_log(chat_head_etm, update.effective_message)
        self.bot.edit_message_text(text=txt, chat_id=tg_chat_id, message_id=tg_msg_id)
        update.callback_query.answer()
        return ConversationHandler.END

    def register_suggestions(self, update: Update,
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
        # chat_list: Optional[ChatListStorage] = self.msg_storage.get(storage_id, None)
        self.msg_storage[storage_id].set_chat_suggestion(update)
        self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                               "Please reply to a previous message, "
                                               "or choose a recipient:\n\nLegend:\n") + "\n".join(legends),
                                   chat_id=chat_id, message_id=message_id,
                                   reply_markup=InlineKeyboardMarkup(buttons))
        self.suggestion_handler.conversations[storage_id] = Flags.SUGGEST_RECIPIENTS

    def suggested_recipient(self, update: Update, context: CallbackContext):
        """Send the message to selected recipient among all suggested when a
        message is sent with unspecified recipient.

        Triggered by flag ``SUGGEST_RECIPIENTS``.
        """
        assert isinstance(update, Update)
        assert update.effective_message
        assert update.effective_chat
        assert update.callback_query
        assert update.callback_query.data

        chat_id = TelegramChatID(update.effective_chat.id)
        msg_id = TelegramMessageID(update.effective_message.message_id)
        param = update.callback_query.data

        storage_id = (chat_id, msg_id)
        if param.startswith("chat "):
            if storage_id not in self.msg_storage:
                self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                                       "Please reply to a previous message.\n\n"
                                                       "Session expired, please try again."),
                                           chat_id=chat_id,
                                           message_id=msg_id)
            update_ = self.msg_storage[storage_id].update
            assert update_
            update = update_
            chats = self.msg_storage[storage_id].chats
            if not chats:
                self.bot.edit_message_text(text=self._("Error: No recipient specified.\n"
                                                       "Please reply to a previous message.\n\n"
                                                       "Session expired, please try again."),
                                           chat_id=chat_id,
                                           message_id=msg_id)
                if update.callback_query:
                    update.callback_query.answer()
                return ConversationHandler.END
            slave_chat = chats[int(param.split(' ', 1)[1])]
            slave_chat_id = utils.chat_id_to_str(chat=slave_chat)
            self.channel.master_messages.process_telegram_message(update, context, slave_chat_id)
            self.bot.edit_message_text(text=self._("Delivering the message to {0}.").format(slave_chat.full_name),
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
        if update.callback_query:
            update.callback_query.answer()
        return ConversationHandler.END

    def update_group_info(self, update: Update, context: CallbackContext):
        """
        Update the title and profile picture of singly-linked Telegram group
        according to the linked remote chat.

        Triggered by ``/update_info`` command.
        """
        assert isinstance(update, Update)
        assert update.effective_message
        assert update.effective_chat

        if update.effective_chat.type == telegram.Chat.PRIVATE:
            return self.bot.reply_error(update, self._('Send /update_info to a group where this bot is a group admin '
                                                       'to update group title, description and profile picture.'))
        forwarded_from_chat = update.effective_message.forward_from_chat
        if forwarded_from_chat and forwarded_from_chat.type == telegram.Chat.CHANNEL:
            tg_chat = forwarded_from_chat.id
        else:
            tg_chat = update.effective_chat.id
        chats = self.db.get_chat_assoc(master_uid=utils.chat_id_to_str(channel=self.channel,
                                                                       chat_uid=ChatID(str(tg_chat))))
        if len(chats) != 1:
            return self.bot.reply_error(update, self.ngettext('This only works in a group linked with one chat. '
                                                              'Currently {0} chat linked to this group.',
                                                              'This only works in a group linked with one chat. '
                                                              'Currently {0} chats linked to this group.',
                                                              len(chats)).format(len(chats)))
        picture: Optional[IO] = None
        pic_resized: Optional[IO] = None
        channel_id, chat_uid, _ = utils.chat_id_str_to_id(chats[0])
        if channel_id not in coordinator.slaves:
            self.logger.exception(f"Channel linked ({channel_id}) is not found.")
            return self.bot.reply_error(update, self._('Channel linked ({channel}) is not found.')
                                        .format(channel=channel_id))
        channel = coordinator.slaves[channel_id]
        try:
            chat = self.chat_manager.update_chat_obj(channel.get_chat(chat_uid), full_update=True)

            self.bot.set_chat_title(tg_chat, self.truncate_ellipsis(chat.chat_title, self.MAX_LEN_CHAT_TITLE))

            # Update remote group members list to Telegram group description if available
            desc = chat.description
            if isinstance(chat, ETMGroupChat):
                names = [i.long_name for i in chat.members if not isinstance(i, SystemChatMember)]
                # TRANSLATORS: Separator between group members in a Telegram group description generated by /update_info
                members = self._(", ").join(names)
                if desc:
                    desc += "\n"
                desc += self.ngettext("{count} group member: {list}", "{count} group members: {list}",
                                      len(names)).format(count=len(names), list=members)
            if desc:
                try:
                    self.bot.set_chat_description(
                        tg_chat, self.truncate_ellipsis(desc, self.MAX_LEN_CHAT_DESC))
                except BadRequest as e:
                    if "Chat description is not modified" in e.message:
                        pass
                    else:
                        self.logger.exception("Exception occurred while trying to update chat description: %s", e)
                except TelegramError as e:  # description is not updated
                    self.logger.exception("Exception occurred while trying to update chat description: %s", e)

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
            update.effective_message.reply_text(self._('Chat details updated.'))
        except EFBChatNotFound:
            self.logger.exception("Chat linked (%s) is not found in the slave channel "
                                  "(%s).", channel_id, chat_uid)
            return self.bot.reply_error(update, self._("Chat linked ({chat_uid}) is not found in the slave channel "
                                                       "({channel_name}, {channel_id}).")
                                        .format(channel_name=channel.channel_name, channel_id=channel_id,
                                                chat_uid=chat_uid))
        except TelegramError as e:
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
        assert isinstance(update, Update)
        assert update.effective_message

        message = update.effective_message
        if message.migrate_from_chat_id is not None:
            from_id = ChatID(str(message.migrate_from_chat_id))
            to_id = ChatID(str(message.chat.id))
        elif message.migrate_to_chat_id is not None:
            from_id = ChatID(str(message.chat.id))
            to_id = ChatID(str(message.migrate_to_chat_id))
        else:
            # Per ptb filter specs, this part of code should not be reached.
            return
        self.chat_migration_by_id(from_id, to_id)

    def chat_migration_by_id(self, from_id, to_id):
        from_str = utils.chat_id_to_str(self.channel.channel_id, from_id)
        to_str = utils.chat_id_to_str(self.channel.channel_id, to_id)
        for i in self.db.get_chat_assoc(master_uid=from_str):
            self.db.add_chat_assoc(master_uid=to_str, slave_uid=i, multiple_slave=True)
        self.db.remove_chat_assoc(master_uid=from_str)

    @staticmethod
    def truncate_ellipsis(text: str, length: int) -> str:
        """Truncate a string with ellipsis added to the end if needed."""
        if len(text) <= length:
            return text
        return text[:length - 1] + "…"
