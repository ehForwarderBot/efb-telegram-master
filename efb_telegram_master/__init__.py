# coding=utf-8

import html
import logging
import mimetypes
import time
from gettext import NullTranslations, translation
from typing import Optional, List, Callable
from xmlrpc.server import SimpleXMLRPCServer

import telegram  # lgtm [py/import-and-import-from]
import telegram.constants
import telegram.error
from PIL import Image, WebPImagePlugin
from pkg_resources import resource_filename
from ruamel.yaml import YAML
from telegram import Update, Message
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext, Filters

import ehforwarderbot  # lgtm [py/import-and-import-from]
from ehforwarderbot import Channel, coordinator
from ehforwarderbot import utils as efb_utils
from ehforwarderbot.channel import MasterChannel
from ehforwarderbot.message import Message as EFBMessage
from ehforwarderbot.chat import Chat
from ehforwarderbot.status import Status
from ehforwarderbot.constants import MsgType
from ehforwarderbot.exceptions import EFBException, EFBOperationNotSupported, EFBChatNotFound, \
    EFBMessageReactionNotPossible
from ehforwarderbot.status import ReactToMessage
from ehforwarderbot.types import ModuleID, InstanceID, MessageID, ReactionName, ChatID
from . import utils as etm_utils
from .__version__ import __version__
from .bot_manager import TelegramBotManager
from .chat_binding import ChatBindingManager
from .chat_destination_cache import ChatDestinationCache
from .chat_object_cache import ChatObjectCacheManager
from .commands import CommandsManager
from .db import DatabaseManager
from .master_message import MasterMessageProcessor
from .message import ETMMsg
from .rpc_utils import RPCUtilities
from .slave_message import SlaveMessageProcessor
from .utils import ExperimentalFlagsManager, EFBChannelChatIDStr, TelegramChatID, TelegramMessageID


class TelegramChannel(MasterChannel):
    """
    EFB Channel - Telegram (Master)
    Based on python-telegram-bot, Telegram Bot API

    Author: Eana Hufwe <https://github.com/blueset>

    Configuration file example:
        .. code-block:: yaml

            token: "12345678:1a2b3c4d5e6g7h8i9j"
            admins:
            - 102938475
            - 91827364
            flags:
                join_msg_threshold_secs: 10
                multiple_slave_chats: false
    """

    # Meta Info
    channel_name = "Telegram Master"
    channel_emoji = "✈"
    channel_id = ModuleID("blueset.telegram")
    supported_message_types = {MsgType.Text, MsgType.File, MsgType.Voice,
                               MsgType.Image, MsgType.Link, MsgType.Location,
                               MsgType.Sticker, MsgType.Video, MsgType.Animation,
                               MsgType.Status}
    __version__ = __version__

    # Data
    _stop_polling = False
    timeout_count = 0
    last_poll_confliction_time = 0.0
    CONFLICTION_TIMEOUT = 60  # seconds since last confliction warnings received

    # Constants
    config: dict

    # Translator
    translator: NullTranslations = translation("efb_telegram_master",
                                               resource_filename('efb_telegram_master', 'locale'),
                                               fallback=True)
    locale: Optional[str] = None

    # RPC server
    rpc_server: Optional[SimpleXMLRPCServer] = None

    def __init__(self, instance_id: InstanceID = None):
        """
        Initialization.
        """
        super().__init__(instance_id)

        # Check PIL support for WebP
        Image.init()
        if 'WEBP' not in Image.ID or not getattr(WebPImagePlugin, "SUPPORTED", None):
            raise EFBException(self._("WebP support of Pillow is required.\n"
                                      "Please refer to Pillow Documentation for instructions.\n"
                                      "https://pillow.readthedocs.io/"))

        # Suppress debug logs from dependencies
        # logging.getLogger('requests').setLevel(logging.CRITICAL)
        # logging.getLogger('urllib3').setLevel(logging.CRITICAL)
        # logging.getLogger('telegram.bot').setLevel(logging.CRITICAL)
        # logging.getLogger('telegram.vendor.ptb_urllib3.urllib3.connectionpool').setLevel(logging.CRITICAL)

        # Set up logger
        self.logger: logging.Logger = logging.getLogger(__name__)

        # Load configs
        self.load_config()

        # Load predefined MIME types
        mimetypes.init(files=["mimetypes"])

        # Initialize managers
        self.flag: ExperimentalFlagsManager = ExperimentalFlagsManager(self)
        self.db: DatabaseManager = DatabaseManager(self)
        self.chat_manager: ChatObjectCacheManager = ChatObjectCacheManager(self)
        self.chat_dest_cache: ChatDestinationCache = ChatDestinationCache(self.flag("send_to_last_chat"))
        self.bot_manager: TelegramBotManager = TelegramBotManager(self)
        self.commands: CommandsManager = CommandsManager(self)
        self.chat_binding: ChatBindingManager = ChatBindingManager(self)
        self.slave_messages: SlaveMessageProcessor = SlaveMessageProcessor(self)

        if not self.flag('auto_locale'):
            self.translator = translation("efb_telegram_master",
                                          resource_filename('efb_telegram_master', 'locale'),
                                          fallback=True)

        # Basic message handlers
        non_edit_filter = Filters.update.message | Filters.update.channel_post
        self.bot_manager.dispatcher.add_handler(
            CommandHandler("start", self.start, filters=non_edit_filter))
        self.bot_manager.dispatcher.add_handler(
            CommandHandler("help", self.help, filters=non_edit_filter))
        self.bot_manager.dispatcher.add_handler(
            CommandHandler("info", self.info, filters=non_edit_filter))
        self.bot_manager.dispatcher.add_handler(
            CallbackQueryHandler(self.void_callback_handler, pattern="void"))
        self.bot_manager.dispatcher.add_handler(
            CallbackQueryHandler(self.bot_manager.session_expired))
        self.bot_manager.dispatcher.add_handler(
            CommandHandler("react", self.react, filters=non_edit_filter)
        )

        # Register master message handlers after commands to prevent commands
        # commands to be delivered as messages
        self.master_messages: MasterMessageProcessor = MasterMessageProcessor(self)

        self.bot_manager.dispatcher.add_error_handler(self.error)

        self.rpc_utilities = RPCUtilities(self)

    @property
    def _(self) -> Callable[[str], str]:
        return self.translator.gettext

    @property
    def ngettext(self) -> Callable[[str, str, int], str]:
        return self.translator.ngettext

    def load_config(self):
        """
        Load configuration from path specified by the framework.

        Configuration file is in YAML format.
        """
        config_path = efb_utils.get_config_path(self.channel_id)
        if not config_path.exists():
            raise FileNotFoundError(self._("Config File does not exist. ({path})").format(path=config_path))
        with config_path.open() as f:
            data = YAML().load(f)

            # Verify configuration
            if not isinstance(data.get('token', None), str):
                raise ValueError(self._('Telegram bot token must be a string'))
            if isinstance(data.get('admins', None), int):
                data['admins'] = [data['admins']]
            if isinstance(data.get('admins', None), str) and data['admins'].isdigit():
                data['admins'] = [int(data['admins'])]
            if not isinstance(data.get('admins', None), list) or not data['admins']:
                raise ValueError(self._("Admins' user IDs must be a list of one number or more."))
            for i in range(len(data['admins'])):
                if isinstance(data['admins'][i], str) and data['admins'][i].isdigit():
                    data['admins'][i] = int(data['admins'][i])
                if not isinstance(data['admins'][i], int):
                    raise ValueError(self._('Admin ID is expected to be an int, but {data} is found.')
                                     .format(data=data['admins'][i]))

            self.config = data.copy()

    def info(self, update: Update, context: CallbackContext):
        """
        Show info of the current telegram conversation.
        Triggered by `/info`.
        """
        assert isinstance(update, Update)
        assert isinstance(update.effective_message, Message)
        if update.effective_message.chat.type != telegram.Chat.PRIVATE:  # Group message
            msg = self.info_group(update)
        elif update.effective_message.forward_from_chat and \
                update.effective_message.forward_from_chat.type == 'channel':  # Forwarded channel command.
            msg = self.info_channel(update)
        else:  # Talking to the bot.
            msg = self.info_general()

        update.effective_message.reply_text(msg)

    def info_general(self):
        """Generate string for information of the current running EFB instance."""
        if self.instance_id:
            if coordinator.profile != "default":
                msg = self._(
                    "This is EFB Telegram Master Channel {version}, running on profile “{profile}”, "
                    "instance “{instance}”, on EFB {fw_version}.")
            else:  # Default profile
                msg = self._(
                    "This is EFB Telegram Master Channel {version}, running on default profile, "
                    "instance “{instance}”, on EFB {fw_version}.")
        else:  # Default instance
            if coordinator.profile != "default":
                msg = self._(
                    "This is EFB Telegram Master Channel {version}, running on profile “{profile}”, "
                    "default instance, on EFB {fw_version}.")
            else:  # Default profile
                msg = self._(
                    "This is EFB Telegram Master Channel {version}, running on default profile and instance, "
                    "on EFB {fw_version}.")
        msg = msg.format(version=self.__version__, fw_version=ehforwarderbot.__version__,
                         profile=coordinator.profile, instance=self.instance_id)
        msg += "\n" + self.ngettext("{count} slave channel activated:",
                                    "{count} slave channels activated:",
                                    len(coordinator.slaves)).format(count=len(coordinator.slaves))
        for i in coordinator.slaves:
            msg += "\n- %s %s (%s, %s)" % (coordinator.slaves[i].channel_emoji,
                                           coordinator.slaves[i].channel_name,
                                           i, coordinator.slaves[i].__version__)
        if coordinator.middlewares:
            msg += self.ngettext("\n\n{count} middleware activated:", "\n\n{count} middlewares activated:",
                                 len(coordinator.middlewares)).format(count=len(coordinator.middlewares))
            for i in coordinator.middlewares:
                msg += "\n- %s (%s, %s)" % (i.middleware_name, i.middleware_id, i.__version__)
        return msg

    def info_channel(self, update):
        """Generate string for chat linking info of a channel."""
        chat = update.effective_message.forward_from_chat
        links = self.db.get_chat_assoc(master_uid=etm_utils.chat_id_to_str(self.channel_id, chat.id))
        if links:  # Linked chat
            # TRANSLATORS: ‘channel’ here refers to a Telegram channel.
            msg = self._("The channel {group_name} ({group_id}) is linked to:") \
                .format(group_name=chat.title,
                        group_id=chat.id)
            msg += self.build_link_chats_info_str(links)
        else:
            # TRANSLATORS: ‘channel’ here means an EFB channel.
            msg = self._("The channel {group_name} ({group_id}) is "
                         "not linked to any remote chat. "
                         "To link one, use /link.").format(group_name=chat.title,
                                                           group_id=chat.id)
        return msg

    def info_group(self, update):
        """Generate string for chat linking info of a group."""
        links = self.db.get_chat_assoc(master_uid=etm_utils.chat_id_to_str(self.channel_id, update.message.chat_id))
        if links:  # Linked chat
            msg = self._("The group {group_name} ({group_id}) is linked to:").format(
                group_name=update.message.chat.title,
                group_id=update.message.chat_id)
            msg += self.build_link_chats_info_str(links)
        else:
            msg = self._("The group {group_name} ({group_id}) is not linked to any remote chat. "
                         "To link one, use /link.").format(group_name=update.message.chat.title,
                                                           group_id=update.message.chat_id)
        return msg

    def build_link_chats_info_str(self, links: List[EFBChannelChatIDStr]) -> str:
        """Build a string indicating all linked chats in argument.

        Returns:
            String that starts with a line break.
        """
        msg = ""
        for i in links:
            channel_id, chat_id, _ = etm_utils.chat_id_str_to_id(i)
            chat_object = self.chat_manager.get_chat(channel_id, chat_id)
            if chat_object:
                msg += "\n- %s (%s:%s)" % (chat_object.full_name,
                                           channel_id, chat_id)
            else:
                try:
                    module = coordinator.get_module_by_id(channel_id)
                    if isinstance(module, Channel):
                        channel_name = f"{module.channel_emoji} {module.channel_name}"
                    else:  # module is Middleware
                        channel_name = module.middleware_name
                    msg += self._("\n- {channel_name}: Unknown chat ({channel_id}:{chat_id})").format(
                        channel_name=channel_name,
                        channel_id=channel_id,
                        chat_id=chat_id
                    )
                except NameError:
                    # TRANSLATORS: ‘channel’ here means an EFB channel.
                    msg += self._("\n- Unknown channel {channel_id}: ({chat_id})").format(
                        channel_id=channel_id,
                        chat_id=chat_id
                    )
        return msg

    def start(self, update: Update, context: CallbackContext):
        """
        Process bot command `/start`.
        """
        assert isinstance(update, Update)
        assert isinstance(update.effective_message, telegram.Message)
        assert isinstance(update.effective_chat, telegram.Chat)
        if context.args:  # Group binding command
            if update.effective_message.chat.type != telegram.Chat.PRIVATE or \
                    (update.effective_message.forward_from_chat and
                     update.effective_message.forward_from_chat.type == telegram.Chat.CHANNEL):
                self.chat_binding.link_chat(update, context.args)
            else:
                self.bot_manager.send_message(update.effective_chat.id,
                                              self._('You cannot link remote chats to here. Please try again.'))
        else:
            txt = self._("This is EFB Telegram Master Channel.\n\n"
                         "To learn more, please visit https://etm.1a23.studio .")
            self.bot_manager.send_message(update.effective_chat.id, txt)

    def react(self, update: Update, context: CallbackContext):
        """React to a message."""
        assert isinstance(update, Update)
        assert isinstance(update.effective_message, Message)
        message: Message = update.effective_message

        reaction = None
        args = message.text and message.text.split(' ', 1)
        if args and len(args) > 1:
            reaction = ReactionName(args[1])

        if not message.reply_to_message:
            message.reply_html(self._("Reply to a message with this command and an emoji "
                                      "to send a reaction. "
                                      "Ex.: <code>/react 👍</code>.\n"
                                      "Send <code>/react -</code> to remove your reaction "
                                      "from a message."))
            return

        target: Message = message.reply_to_message
        msg_log = self.db.get_msg_log(master_msg_id=etm_utils.message_id_to_str(chat_id=TelegramChatID(target.chat_id),
                                                                                message_id=TelegramMessageID(target.message_id)))
        if msg_log is None:
            message.reply_text(self._("The message you replied to is not recorded in ETM database. "
                                      "You cannot react to this message."))
            return

        if not reaction:
            msg_log_obj: ETMMsg = msg_log.build_etm_msg(self.chat_manager)
            reactors = msg_log_obj.reactions
            if not reactors:
                message.reply_html(self._("This message has no reactions yet. "
                                          "Reply to a message with this command and "
                                          "an emoji to send a reaction. "
                                          "Ex.: <code>/react 👍</code>."))
                return
            else:
                text = ""
                for key, values in reactors.items():
                    if not values:
                        continue
                    text += f"{key}:\n"
                    for j in values:
                        text += f"    {j.display_name}\n"
                text = text.strip()
                message.reply_text(text)
                return

        message_id = msg_log.slave_message_id
        channel_id, chat_uid, _ = etm_utils.chat_id_str_to_id(msg_log.slave_origin_uid)

        if channel_id not in coordinator.slaves:
            message.reply_text(self._("The slave channel involved in this message ({}) is not available. "
                                      "You cannot react to this message.").format(channel_id))
            return

        channel = coordinator.slaves[channel_id]

        if channel.suggested_reactions is None:
            message.reply_text(self._("The channel involved in this message ({}) does not accept reactions. "
                                      "You cannot react to this message.").format(channel_id))
            return

        try:
            chat_obj = channel.get_chat(chat_uid)
        except EFBChatNotFound:
            message.reply_text(self._("The chat involved in this message ({}) is not found. "
                                      "You cannot react to this message.").format(chat_uid))
            return

        if reaction == ReactionName("-"):
            reaction = None

        try:
            coordinator.send_status(ReactToMessage(chat=chat_obj, msg_id=message_id, reaction=reaction))
        except EFBOperationNotSupported:
            message.reply_text(self._("You cannot react anything to this message."))
            return
        except EFBMessageReactionNotPossible:
            prompt = self._("{} is not accepted as a reaction to this message.").format(reaction)
            if channel.suggested_reactions:
                # TRANSLATORS: {} is a list of names of possible reactions, separated with comma.
                prompt += "\n" + self._("You may want to try: {}").format(", ".join(channel.suggested_reactions[:10]))
            message.reply_text(prompt)
            return

    def help(self, update: Update, context: CallbackContext):
        assert isinstance(update, Update)
        assert isinstance(update.message, Message)
        txt = self._("EFB Telegram Master Channel\n"
                     "/link\n"
                     "    Link a remote chat to an empty Telegram group.\n"
                     "    Followed by a regular expression to filter results.\n"
                     "/chat\n"
                     "    Generate a chat head to start a conversation.\n"
                     "    Followed by a regular expression to filter results.\n"
                     "/extra\n"
                     "    List all additional features from slave channels.\n"
                     "/unlink_all\n"
                     "    Unlink all remote chats in this chat.\n"
                     "/info\n"
                     "    Show information of the current Telegram chat.\n"
                     "/react [emoji]\n"
                     "    React to a message with an emoji, or show a list of members reacted.\n"
                     "/update_info\n"
                     "    Update info of linked Telegram group.\n"
                     "    Only works in singly linked group where the bot is an admin.\n"
                     "/rm\n"
                     "    Remove the quoted message from its remote chat.\n"
                     "/help\n"
                     "    Print this command list.")
        update.message.reply_text(txt)

    def poll(self):
        """
        Message polling process.
        """
        self.bot_manager.polling()

    def error(self, update: object, context: CallbackContext):
        """
        Print error to console, and send error message to first admin.
        Triggered by python-telegram-bot error callback.
        """
        assert context.error
        error: Exception = context.error
        if "make sure that only one bot instance is running" in str(error):
            now = time.time()
            # Warn the user only from the second time within ``CONFLICTION_TIMEOUT``
            # seconds to suppress isolated warnings.
            # https://github.com/ehForwarderBot/efb-telegram-master/issues/103
            if now - self.last_poll_confliction_time < self.CONFLICTION_TIMEOUT:
                msg = self._('Conflicted polling detected. If this error persists, '
                             'please ensure you are running only one instance of this Telegram bot.')
                self.logger.critical(msg)
                self.bot_manager.send_message(self.config['admins'][0], msg)
            self.last_poll_confliction_time = now
            return
        if "Invalid server response" in str(error) and not update:
            self.logger.error("Boom! Telegram API is no good. (Invalid server response.)")
            return
        # noinspection PyBroadException
        try:
            raise error
        except telegram.error.Unauthorized:
            self.logger.error("The bot is not authorised to send update:\n%s\n%s", str(update), str(error))
        except telegram.error.BadRequest as e:
            assert isinstance(update, Update)
            if e.message == "Message is not modified" and update.callback_query:
                self.logger.error("Chill bro, don't click that fast.")
            else:
                self.logger.exception("Message request is invalid.\n%s\n%s", str(update), str(error))
                self.bot_manager.send_message(self.config['admins'][0],
                                              self._("Message request is invalid.\n{error}\n"
                                                     "<code>{update}</code>").format(
                                                  error=html.escape(str(error)), update=html.escape(str(update))),
                                              parse_mode="HTML")
        except (telegram.error.TimedOut, telegram.error.NetworkError):
            self.timeout_count += 1
            self.logger.error("Poor internet connection detected.\n"
                              "Number of network error occurred since last startup: %s\n%s\nUpdate: %s",
                              self.timeout_count, str(error), str(update))
            if isinstance(update, Update) and isinstance(update.message, Message):
                update.message.reply_text(self._("This message is not processed due to poor internet environment "
                                                 "of the server.\n"
                                                 "<code>{code}</code>").format(code=html.escape(str(error))),
                                          quote=True,
                                          parse_mode="HTML")

            timeout_interval = self.flag('network_error_prompt_interval')
            if timeout_interval > 0 and self.timeout_count % timeout_interval == 0:
                self.bot_manager.send_message(self.config['admins'][0],
                                              self.ngettext("<b>EFB Telegram Master channel</b>\n"
                                                            "You may have a poor internet connection on your server. "
                                                            "Currently {count} network error is detected.\n"
                                                            "For more details, please refer to the log.",
                                                            "<b>EFB Telegram Master channel</b>\n"
                                                            "You may have a poor internet connection on your server. "
                                                            "Currently {count} network errors are detected.\n"
                                                            "For more details, please refer to the log.",
                                                            self.timeout_count).format(
                                                  count=self.timeout_count),
                                              parse_mode="HTML")
        except telegram.error.ChatMigrated as e:
            assert isinstance(update, Update)
            new_id = e.new_chat_id
            assert isinstance(update.message, Message)
            old_id = ChatID(str(update.message.chat_id))
            count = 0
            for i in self.db.get_chat_assoc(master_uid=etm_utils.chat_id_to_str(self.channel_id, old_id)):
                self.logger.debug('Migrating slave chat %s from Telegram chat %s to %s.', i, old_id, new_id)
                self.db.remove_chat_assoc(slave_uid=i)
                self.db.add_chat_assoc(master_uid=etm_utils.chat_id_to_str(self.channel_id, ChatID(str(new_id))), slave_uid=i)
                count += 1
            self.bot_manager.send_message(
                new_id, self.ngettext("Chat migration detected.\n"
                                      "All {count} remote chat are now linked to this new group.",
                                      "Chat migration detected.\n"
                                      "All {count} remote chats are now linked to this new group.",
                                      count).format(count=count))
        except Exception:
            try:
                self.bot_manager.send_message(
                    self.config['admins'][0],
                    self._(
                        "EFB Telegram Master channel encountered error <code>{error}</code> "
                        "caused by update <code>{update}</code>. See log for details.").format(
                        error=html.escape(str(error)),
                        update=html.escape(
                            str(update))),
                    parse_mode="HTML")
            except Exception as ex:
                self.logger.exception("Failed to send error message through Telegram: %s", ex)

            finally:
                self.logger.exception('Unhandled telegram bot error!\n'
                                      'Update %s caused error %s. Exception', update, error)

    def send_message(self, msg: EFBMessage) -> EFBMessage:
        return self.slave_messages.send_message(msg)

    def send_status(self, status: Status):
        return self.slave_messages.send_status(status)

    def get_message_by_id(self, chat: Chat,
                          msg_id: MessageID) -> Optional[EFBMessage]:
        origin_uid = etm_utils.chat_id_to_str(chat=chat)
        msg_log = self.db.get_msg_log(slave_origin_uid=origin_uid,
                                      slave_msg_id=msg_id)
        if msg_log is not None:
            return msg_log.build_etm_msg(self.chat_manager)
        else:
            # Message is not found.
            return None

    def void_callback_handler(self, update: Update, context: CallbackContext):
        assert isinstance(update, Update)
        assert update.effective_message
        assert update.callback_query
        self.bot_manager.answer_callback_query(update.callback_query.id,
                                               text=self._("This button does nothing."),
                                               message_id=update.effective_message.message_id,
                                               cache_time=180)

    def stop_polling(self):
        self.logger.debug("Gracefully stopping %s (%s).", self.channel_name, self.channel_id)
        self.rpc_utilities.shutdown()
        self.bot_manager.graceful_stop()
        self.master_messages.stop_worker()
        self.db.stop_worker()
        self.logger.debug("%s (%s) gracefully stopped.", self.channel_name, self.channel_id)

    def get_chats(self) -> List[Chat]:
        raise EFBOperationNotSupported()
