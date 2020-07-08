import copy
import pickle
import time
from abc import ABC
from contextlib import suppress
from datetime import datetime
from typing import Optional, TYPE_CHECKING, Pattern, List, Dict, Any, Union, TypeVar, overload, MutableSequence

from ehforwarderbot import Middleware, coordinator
from ehforwarderbot.channel import SlaveChannel
from ehforwarderbot.chat import ChatNotificationState, BaseChat, Chat, PrivateChat, ChatMember, SystemChatMember, \
    SelfChatMember, GroupChat, SystemChat
from ehforwarderbot.types import ChatID, ModuleID
from . import utils
from .constants import Emoji
from .utils import EFBChannelChatIDStr

if TYPE_CHECKING:
    from .db import DatabaseManager

__all__ = ['ETMChatMember', 'ETMSelfChatMember', 'ETMSystemChatMember',
           'ETMPrivateChat', 'ETMSystemChat', 'ETMGroupChat',
           'convert_chat', 'unpickle',
           'ETMChatType', 'ETMBaseChatType']


class ETMBaseChatMixin(BaseChat, ABC):  # lgtm [py/missing-equals]
    # Allow mypy to recognize subclass output for `return self` methods.
    _Self = TypeVar('_Self', bound='ETMBaseChatMixin')
    chat_type_name = "BaseChat"

    # noinspection PyMissingConstructor
    def __init__(self, db: 'DatabaseManager', *args, **kwargs):
        self.db = db
        super().__init__(*args, **kwargs)

    def remove_from_db(self):
        """Remove this chat from database."""
        self.db.delete_slave_chat_info(self.module_id, self.uid)

    def __getstate__(self) -> Dict[str, Any]:
        state = self.__dict__.copy()
        if 'db' in state:
            del state['db']
        return state

    def __setstate__(self, state: Dict[str, Any]):
        from . import TelegramChannel
        # Import inline to prevent cyclic import
        self.__dict__.update(state)
        with suppress(NameError, AttributeError):
            if isinstance(coordinator.master, TelegramChannel):
                self.db = coordinator.master.db

    def __copy__(self):
        rv = self.__reduce_ex__(4)
        if isinstance(rv, str):
            return self
        obj = copy._reconstruct(self, None, *rv)
        obj.db = self.db
        return obj


class ETMChatMember(ETMBaseChatMixin, ChatMember):
    chat_type_name = "ChatMember"

    def __init__(self, db: 'DatabaseManager', chat: 'Chat', *, name: str = "", alias: Optional[str] = None,
                 uid: ChatID = ChatID(""), vendor_specific: Dict[str, Any] = None, description: str = "",
                 middleware: Optional[Middleware] = None):
        super().__init__(db, chat, name=name, alias=alias, uid=uid, vendor_specific=vendor_specific,
                         description=description, middleware=middleware)


class ETMSelfChatMember(ETMChatMember, SelfChatMember):
    chat_type_name = "SelfChatMember"

    def __init__(self, db: 'DatabaseManager', chat: 'Chat', *, name: str = "", alias: Optional[str] = None,
                 uid: ChatID = ChatID(""), vendor_specific: Dict[str, Any] = None, description: str = "",
                 middleware: Optional[Middleware] = None):
        super().__init__(db, chat, name=name, alias=alias, uid=uid, vendor_specific=vendor_specific,
                         description=description, middleware=middleware)


class ETMSystemChatMember(ETMChatMember, SystemChatMember):
    chat_type_name = "SystemChatMember"

    def __init__(self, db: 'DatabaseManager', chat: 'Chat', *, name: str = "", alias: Optional[str] = None,
                 uid: ChatID = ChatID(""), vendor_specific: Dict[str, Any] = None, description: str = "",
                 middleware: Optional[Middleware] = None):
        super().__init__(db, chat, name=name, alias=alias, uid=uid, vendor_specific=vendor_specific,
                         description=description, middleware=middleware)


class ETMChatMixin(ETMBaseChatMixin, Chat, ABC):
    _last_message_time: Optional[datetime] = None
    _last_message_time_query: float = 0
    LAST_MESSAGE_QUERY_TIMEOUT_MS: float = 60000  # 60s

    _linked: Optional[List[EFBChannelChatIDStr]] = None

    members: MutableSequence[ETMChatMember]  # type: ignore
    self: Optional[ETMSelfChatMember]

    chat_type_name = "Chat"
    chat_type_emoji = Emoji.UNKNOWN

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
            Description: <Description>
            Notification: (ALL|MENTION|NONE)
            Other: <Python Dictionary String>

        If a string is provided instead of compiled regular expression pattern,
        simple string match is used instead.

        String match is about 5x faster than re.search when there’s no
        significance of regex used.
        Ref: https://etm.1a23.studio/pull/77

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
                       f"Name: {self.name}\n" \
                       f"Alias: {self.alias}\n" \
                       f"ID: {self.uid}\n" \
                       f"Type: {self.chat_type_name}\n" \
                       f"Mode: {mode_str}\n" \
                       f"Description: {self.description}\n" \
                       f"Notification: {self.notification.name}\n" \
                       f"Other: {self.vendor_specific}"
        if isinstance(pattern, str):
            return pattern.lower() in entry_string.lower()
        else:  # pattern is re.Pattern
            return bool(pattern.search(entry_string))

    def unlink(self):
        """ Unlink this chat from any Telegram group."""
        self.db.remove_chat_assoc(slave_uid=utils.chat_id_to_str(self.module_id, self.uid))
        self._update_linked()

    def link(self, channel_id: ModuleID, chat_id: ChatID, multiple_slave: bool):
        self.db.add_chat_assoc(master_uid=utils.chat_id_to_str(channel_id, chat_id),
                               slave_uid=utils.chat_id_to_str(self.module_id, self.uid),
                               multiple_slave=multiple_slave)
        self._update_linked()

    @property
    def linked(self) -> List[EFBChannelChatIDStr]:
        if self._linked is None:
            self._update_linked()
        return self._linked or []

    def _update_linked(self):
        self._linked = self.db.get_chat_assoc(
            slave_uid=utils.chat_id_to_str(self.module_id, self.uid)
        )

    @property
    def full_name(self) -> str:
        """Chat name with channel name and emoji"""
        chat_long_name = self.long_name
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

        Shows only alias if available.

        An asterisk (*) is added to the beginning if the channel is not
        running on its default instance.
        """
        non_default_instance_flag = "*" if "#" in self.module_id else ""
        return f"{non_default_instance_flag}" \
               f"{self.channel_emoji}{self.chat_type_emoji} " \
               f"{self.display_name}"

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
        assert self._last_message_time
        return self._last_message_time

    def update_to_db(self):
        """Update this object to database."""
        self.db.set_slave_chat_info(self)

    @property
    def pickle(self) -> bytes:
        return pickle.dumps(self)

    def remove_from_db(self):
        super().remove_from_db()
        for i in self.members:
            self.db.delete_slave_chat_info(self.module_id, i.uid, self.uid)

    def add_self(self) -> ETMSelfChatMember:
        if getattr(self, 'self', None) and isinstance(self.self, ETMSelfChatMember):
            return self.self
        assert not any(isinstance(i, SelfChatMember) for i in self.members)
        s = ETMSelfChatMember(self.db, self)
        self.members.append(s)
        return s

    def add_member(self, name: str, uid: ChatID, alias: Optional[str] = None,  # type: ignore
                   vendor_specific: Dict[str, Any] = None, id='',
                   description: str = "", middleware: Optional[Middleware] = None) -> ETMChatMember:
        # TODO: remove deprecated ID
        assert not id, f"id is {id!r}"
        member = ETMChatMember(self.db, self, name=name, alias=alias, uid=uid,
                               vendor_specific=vendor_specific, description=description,
                               middleware=middleware)
        self.members.append(member)
        return member

    # type: ignore
    def add_system_member(self, name: str = "", alias: Optional[str] = None, uid: ChatID = ChatID(""),  # type: ignore
                          vendor_specific: Dict[str, Any] = None, description: str = "", id='',
                          middleware: Optional[Middleware] = None) -> ETMSystemChatMember:
        # TODO: remove deprecated ID
        assert not id, f"id is {id!r}"
        member = self.make_system_member(name=name, alias=alias, uid=uid,
                                         vendor_specific=vendor_specific, description=description,
                                         middleware=middleware)
        self.members.append(member)
        return member

    def make_system_member(self, name: str = "", alias: Optional[str] = None, id: ChatID = ChatID(""),
                           uid: ChatID = ChatID(""), vendor_specific: Dict[str, Any] = None, description: str = "",
                           middleware: Optional[Middleware] = None) -> ETMSystemChatMember:
        # TODO: remove deprecated ID
        assert not id, f"id is {id!r}"
        return ETMSystemChatMember(self.db, self, name=name, alias=alias, uid=uid,
                                   vendor_specific=vendor_specific, description=description, middleware=middleware)

    def get_member(self, member_id: ChatID) -> ETMChatMember:
        return super().get_member(member_id)  # type: ignore


class ETMPrivateChat(ETMChatMixin, PrivateChat):
    chat_type_name = "Private"
    chat_type_emoji = Emoji.USER

    other: ETMChatMember

    def __init__(self, db: 'DatabaseManager', *, channel: Optional[SlaveChannel] = None,
                 middleware: Optional[Middleware] = None,
                 module_name: str = "", channel_emoji: str = "", module_id: ModuleID = ModuleID(""), name: str = "",
                 alias: Optional[str] = None, uid: ChatID = ChatID(""), vendor_specific: Dict[str, Any] = None,
                 description: str = "", notification: ChatNotificationState = ChatNotificationState.ALL,
                 with_self: bool = True, other_is_self: bool = False):
        super().__init__(db, channel=channel, middleware=middleware, module_name=module_name,
                         channel_emoji=channel_emoji,
                         module_id=module_id, name=name, alias=alias, uid=uid, vendor_specific=vendor_specific,
                         description=description, notification=notification, with_self=with_self,
                         other_is_self=other_is_self)


class ETMSystemChat(ETMChatMixin, SystemChat):
    chat_type_name = "System"
    chat_type_emoji = Emoji.SYSTEM

    other: ETMSystemChatMember

    def __init__(self, db: 'DatabaseManager', *, channel: Optional[SlaveChannel] = None,
                 middleware: Optional[Middleware] = None,
                 module_name: str = "", channel_emoji: str = "", module_id: ModuleID = ModuleID(""), name: str = "",
                 alias: Optional[str] = None, uid: ChatID = ChatID(""), vendor_specific: Dict[str, Any] = None,
                 description: str = "", notification: ChatNotificationState = ChatNotificationState.ALL,
                 with_self: bool = True):
        super().__init__(db, channel=channel, middleware=middleware, module_name=module_name,
                         channel_emoji=channel_emoji,
                         module_id=module_id, name=name, alias=alias, uid=uid, vendor_specific=vendor_specific,
                         description=description, notification=notification, with_self=with_self)


class ETMGroupChat(ETMChatMixin, GroupChat):
    chat_type_name = "Group"
    chat_type_emoji = Emoji.GROUP

    def __init__(self, db: 'DatabaseManager', *, channel: Optional[SlaveChannel] = None,
                 middleware: Optional[Middleware] = None,
                 module_name: str = "", channel_emoji: str = "", module_id: ModuleID = ModuleID(""), name: str = "",
                 alias: Optional[str] = None, uid: ChatID = ChatID(""), vendor_specific: Dict[str, Any] = None,
                 description: str = "", notification: ChatNotificationState = ChatNotificationState.ALL,
                 with_self: bool = True):
        super().__init__(db, channel=channel, middleware=middleware, module_name=module_name,
                         channel_emoji=channel_emoji,
                         module_id=module_id, name=name, alias=alias, uid=uid, vendor_specific=vendor_specific,
                         description=description, notification=notification, with_self=with_self)


# Class name alias for type checking
ETMChatType = ETMChatMixin
ETMBaseChatType = ETMBaseChatMixin


@overload
def convert_chat(db: 'DatabaseManager', chat: PrivateChat) -> ETMPrivateChat: ...


@overload
def convert_chat(db: 'DatabaseManager', chat: GroupChat) -> ETMGroupChat: ...


@overload
def convert_chat(db: 'DatabaseManager', chat: SystemChat) -> ETMSystemChat: ...


@overload
def convert_chat(db: 'DatabaseManager', chat: Chat) -> ETMChatType: ...


def convert_chat(db: 'DatabaseManager', chat: Chat) -> ETMChatType:
    """Convert an EFB chat object to a ETM extended version.

    Raises:
        TypeError: if the chat type is not supported.
    """
    if isinstance(chat, ETMChatType):
        return chat
    etm_chat: ETMBaseChatType
    if isinstance(chat, PrivateChat):
        etm_chat = ETMPrivateChat(db, module_id=chat.module_id, module_name=chat.module_name,
                                  channel_emoji=chat.channel_emoji, name=chat.name, alias=chat.alias, uid=chat.uid,
                                  vendor_specific=chat.vendor_specific.copy(), description=chat.description,
                                  notification=chat.notification, with_self=chat.has_self,
                                  other_is_self=chat.other is chat.self)
        assert isinstance(etm_chat, ETMPrivateChat)  # for type check
        if chat.self and etm_chat.self:
            copy_member(chat.self, etm_chat.self)
        if chat.self is not chat.other and chat.other and etm_chat.other:
            copy_member(chat.other, etm_chat.other)
        return etm_chat
    if isinstance(chat, SystemChat):
        etm_chat = ETMSystemChat(db, module_id=chat.module_id, module_name=chat.module_name,
                                 channel_emoji=chat.channel_emoji, name=chat.name, alias=chat.alias, uid=chat.uid,
                                 vendor_specific=chat.vendor_specific.copy(), description=chat.description,
                                 notification=chat.notification, with_self=chat.has_self)
        assert isinstance(etm_chat, ETMSystemChat)  # for type check
        if chat.self and etm_chat.self:
            copy_member(chat.self, etm_chat.self)
        if chat.other and etm_chat.other:
            copy_member(chat.other, etm_chat.other)
        return etm_chat
    if isinstance(chat, GroupChat):
        etm_chat = ETMGroupChat(db, module_id=chat.module_id, module_name=chat.module_name,
                                channel_emoji=chat.channel_emoji, name=chat.name, alias=chat.alias, uid=chat.uid,
                                vendor_specific=chat.vendor_specific.copy(), description=chat.description,
                                notification=chat.notification, with_self=False)
        assert isinstance(etm_chat, ETMGroupChat)  # for type check
        for i in chat.members:
            if isinstance(i, ETMChatMember):
                etm_chat.members.append(i)
            elif isinstance(i, SystemChatMember):
                etm_chat.add_system_member(
                    name=i.name, alias=i.alias, uid=i.uid,
                    description=i.description, vendor_specific=i.vendor_specific.copy()
                )
            elif isinstance(i, SelfChatMember):
                etm_chat.self = ETMSelfChatMember(
                    db, etm_chat,
                    name=i.name, alias=i.alias, uid=i.uid,
                    description=i.description, vendor_specific=i.vendor_specific.copy()
                )
                etm_chat.members.append(etm_chat.self)
            else:
                etm_chat.add_member(
                    name=i.name, alias=i.alias, uid=i.uid,
                    description=i.description, vendor_specific=i.vendor_specific.copy()
                )
        return etm_chat
    raise TypeError(f"Chat type unknown: {type(chat)}, {chat!r}")


def copy_member(source: ChatMember, dest: ETMChatMember):
    """Copy values from source object to destination object."""
    dest.name = source.name
    dest.alias = source.alias
    dest.uid = source.uid
    dest.vendor_specific = source.vendor_specific.copy()
    dest.module_id = source.module_id
    dest.module_name = source.module_name
    dest.channel_emoji = source.channel_emoji
    dest.description = source.description


def unpickle(data: bytes, db: 'DatabaseManager') -> ETMChatType:
    obj = pickle.loads(data)
    obj.db = db
    return obj
