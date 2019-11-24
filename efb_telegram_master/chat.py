import pickle
import time
from datetime import datetime
from typing import Optional, TYPE_CHECKING, Pattern, List, Dict, Any, Union

from ehforwarderbot import EFBChat, EFBChannel
from ehforwarderbot.types import ChatID, ModuleID
from . import utils
from .constants import Emoji
from .utils import EFBChannelChatIDStr


if TYPE_CHECKING:
    from .db import DatabaseManager


class ETMChat(EFBChat):
    # Constant
    MUTE_CHAT_ID = "__muted__"

    _last_message_time: Optional[datetime] = None
    _last_message_time_query: float = 0
    LAST_MESSAGE_QUERY_TIMEOUT_MS: float = 60000  # 60s

    _linked: Optional[List[EFBChannelChatIDStr]] = None

    def __init__(self, db: 'DatabaseManager',
                 chat: Optional[EFBChat] = None, channel: Optional[EFBChannel] = None):
        assert db
        self.db = db
        if channel:
            super().__init__(channel)
        if chat:
            self.module_name = chat.module_name
            self.channel_emoji = chat.channel_emoji
            self.module_id = chat.module_id
            self.chat_name = chat.chat_name
            self.chat_type = chat.chat_type
            self.chat_alias = chat.chat_alias
            self.chat_uid = chat.chat_uid
            self.is_chat = chat.is_chat
            self.members = [ETMChat(db=db, chat=i) for i in chat.members]
            self.group = chat.group
            self.vendor_specific = chat.vendor_specific.copy()
        self._update_linked()

    def match(self, pattern: Union[Pattern, str, None]) -> bool:
        """
        Match the chat against a compiled regex pattern or string
        with a string in the following format::

            Channel: <Channel name>
            Name: <Chat name>
            Alias: <Chat Alias>
            ID: <Chat Unique ID>
            Type: (User|Group)
            Mode: [Linked]
            Other: <Python Dictionary String>

        If a string is provided instead of compiled regular expression pattern,
        simple string match is used instead.

        String match is about 5x faster than re.search when there’s no
        significance of regex used.
        Ref: https://github.com/blueset/efb-telegram-master/pull/77

        Args:
            pattern: Regex pattern or string to look for

        Returns:
            If the pattern is found in the generated string.
        """
        if pattern is None:
            return True
        mode = []
        if self.linked:
            mode.append("Linked")
        mode_str = ', '.join(mode)
        entry_string = f"Channel: {self.module_name}\n" \
                       f"Channel ID: {self.module_id}\n" \
                       f"Name: {self.chat_name}\n" \
                       f"Alias: {self.chat_alias}\n" \
                       f"ID: {self.chat_uid}\n" \
                       f"Type: {self.chat_type}\n" \
                       f"Mode: {mode_str}" \
                       f"\nOther: {self.vendor_specific}"
        if isinstance(pattern, str):
            return pattern.lower() in entry_string.lower()
        else:  # pattern is re.Pattern
            return bool(pattern.search(entry_string))

    def unlink(self):
        """ Unlink this chat from any Telegram group."""
        self.db.remove_chat_assoc(slave_uid=utils.chat_id_to_str(self.module_id, self.chat_uid))
        self._update_linked()

    def link(self, channel_id: ModuleID, chat_id: ChatID, multiple_slave: bool):
        self.db.add_chat_assoc(master_uid=utils.chat_id_to_str(channel_id, chat_id),
                               slave_uid=utils.chat_id_to_str(self.module_id, self.chat_uid),
                               multiple_slave=multiple_slave)
        self._update_linked()

    @property
    def linked(self) -> List[EFBChannelChatIDStr]:
        if self._linked is None:
            self._update_linked()
        return self._linked or []

    def _update_linked(self):
        self._linked = self.db.get_chat_assoc(
            slave_uid=utils.chat_id_to_str(self.module_id, self.chat_uid)
        )

    @property
    def muted(self) -> bool:
        # TODO: remove mute related code
        return self.MUTE_CHAT_ID in self.linked

    @property
    def full_name(self) -> str:
        """Chat name with channel name and emoji"""
        chat_long_name = self.long_name
        instance_id = None
        if self.module_name:
            instance_id_idx = self.module_id.find('#')
            if instance_id_idx >= 0:
                instance_id = self.module_id[instance_id_idx + 1:]
                return f"‘{chat_long_name}’ @ ‘{self.channel_emoji} {self.module_name} ({instance_id})’"
            else:
                return f"‘{chat_long_name}’ @ ‘{self.channel_emoji} {self.module_name}’"
        else:
            return f"‘{chat_long_name}’ @ ‘{self.module_id}’"

    @property
    def chat_title(self) -> str:
        """Chat title used in updating title for Telegram group.
        An asterisk (*) is added to the beginning if the channel is not
        running on its default instance.
        """
        non_default_instance_flag = "*" if "#" in self.module_id else ""
        return f"{non_default_instance_flag}" \
               f"{self.channel_emoji}{Emoji.get_source_emoji(self.chat_type)} " \
               f"{self.chat_alias or self.chat_name}"

    @property
    def last_message_time(self) -> datetime:
        """Time of the last recorded message from this chat.
        Returns ``datetime.min`` when no recorded message is found.
        """
        now = time.time()
        if self._last_message_time is None or \
                now - self._last_message_time_query < self.LAST_MESSAGE_QUERY_TIMEOUT_MS:
            msg_log = self.db.get_last_message(slave_chat_id=utils.chat_id_to_str(chat=self))
            self._last_message_time_query = now
            if msg_log is None:
                self._last_message_time = datetime.min
            else:
                self._last_message_time = msg_log.time
        return self._last_message_time

    @property
    def group_id(self) -> Optional[ChatID]:
        if self.group:
            return self.group.chat_uid
        else:
            return None

    @property
    def pickle(self) -> bytes:
        return pickle.dumps(self)

    @staticmethod
    def unpickle(data: bytes, db: 'DatabaseManager') -> 'ETMChat':
        obj = pickle.loads(data)
        obj.db = db
        return obj

    @staticmethod
    def from_db_record(db: 'DatabaseManager', module_id: ModuleID, chat_id: ChatID,
                       group_id: ChatID = None) -> 'ETMChat':
        c_log = db.get_slave_chat_info(module_id, chat_id, group_id)
        if c_log is not None:
            c_pickle = c_log.pickle
            obj = ETMChat.unpickle(c_pickle, db)
        else:
            obj = ETMChat(db=db)
            obj.module_id = module_id
            obj.chat_uid = chat_id
        return obj

    def __getstate__(self) -> Dict[str, Any]:
        state = self.__dict__.copy()
        if 'db' in state:
            del state['db']
        return state

    def __setstate__(self, state: Dict[str, Any]):
        self.__dict__.update(state)
