import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Optional, Dict, Tuple, Iterator, overload, cast, MutableSequence, Collection

from typing_extensions import Literal

from ehforwarderbot import coordinator
from ehforwarderbot.chat import Chat, ChatMember, BaseChat, SystemChatMember, SelfChatMember
from ehforwarderbot.exceptions import EFBChatNotFound
from ehforwarderbot.types import ModuleID, ChatID
from .chat import convert_chat, ETMChatType, ETMChatMember, unpickle, ETMSystemChat

if TYPE_CHECKING:
    from . import TelegramChannel

CacheKey = Tuple[ModuleID, ChatID]
"""Cache storage key: module_id, chat_id"""


class ChatObjectCacheManager:
    """Maintain and update chat objects from all slave channels and
    middlewares.
    """

    def __init__(self, channel: 'TelegramChannel'):
        self.channel = channel
        self.db = channel.db
        self.logger = logging.getLogger(__name__)

        self.cache: Dict[CacheKey, ETMChatType] = dict()

        self.logger.debug("Loading chats from slave channels...")
        # load all chats from all slave channels and convert to ETMChat object
        for channel_id, module in coordinator.slaves.items():
            # noinspection PyBroadException
            try:
                self.logger.debug("Loading chats from '%s'...", channel_id)
                chats = module.get_chats()
            except Exception:
                self.logger.exception("Error occurred while getting chats from %. "
                                      "ETM will report no chat from this channel until further noticed.", channel_id)
                continue
            self.logger.debug("Found %s chats from '%s'.", len(chats), channel_id)
            for chat in chats:
                self.compound_enrol(chat)
            self.logger.debug("All %s chats from '%s' are enrolled.", len(chats), channel_id)

    def compound_enrol(self, chat: Chat) -> ETMChatType:
        """Convert and enrol a chat object for the first time.
        """
        etm_chat = convert_chat(self.db, chat)

        self.logger.debug("Compound enrol %s members of %s", len(etm_chat.members), etm_chat)
        self.enrol(etm_chat)

        return etm_chat

    def enrol(self, chat: ETMChatType):
        """Add a chat object to the cache storage *for the first time*.

        This would not update the cached object upon conflicting.
        """
        key = self.get_cache_key(chat)
        self.cache[key] = chat
        self.logger.debug("Enrolling key %s with value %s", key, chat)

    @staticmethod
    def get_cache_key(chat: BaseChat) -> CacheKey:
        module_id = chat.module_id
        chat_id = chat.uid
        return module_id, chat_id

    @overload
    def get_chat(self, module_id: ModuleID, chat_id: ChatID, build_dummy: Literal[True]) -> ETMChatType:
        ...

    @overload
    def get_chat(self, module_id: ModuleID, chat_id: ChatID, build_dummy: bool = False) -> Optional[ETMChatType]:
        ...

    def get_chat(self, module_id: ModuleID, chat_id: ChatID, build_dummy: bool = False) -> Optional[ETMChatType]:
        """
        Get an ETMChat object of a chat from cache.

        If the object queried is not found, try to get from database cache,
        then the relevant channel. If still not found, return None.

        If build_dummy is set to True, this will return a dummy object with
        the module_id, chat_id and group_id specified.
        """
        key = (module_id, chat_id)
        if key in self.cache:
            return self.cache[key]

        c_log = self.db.get_slave_chat_info(module_id, chat_id)
        if c_log is not None and c_log.pickle:
            # Suppress AttributeError caused by change of class name in EFB 2.0.0b26, ETM 2.0.0b40
            with suppress(AttributeError):
                obj = unpickle(c_log.pickle, self.db)
                self.enrol(obj)
                return obj

        # Only look up from slave channels as middlewares don’t have get_chat_by_id method.
        if module_id in coordinator.slaves:
            with suppress(EFBChatNotFound, KeyError):
                chat_obj = coordinator.slaves[module_id].get_chat(chat_id)
                return self.compound_enrol(chat_obj)

        if build_dummy:
            return ETMSystemChat(self.db,
                                 module_id=module_id,
                                 module_name=module_id,
                                 uid=chat_id,
                                 name=chat_id)
        return None

    @overload
    def get_chat_member(self, module_id: ModuleID, chat_id: ChatID, member_id: ChatID,
                        build_dummy: Literal[True]) -> ETMChatMember:
        ...

    @overload
    def get_chat_member(self, module_id: ModuleID, chat_id: ChatID, member_id: ChatID, build_dummy: bool = False) -> \
            Optional[ETMChatMember]:
        ...

    def get_chat_member(self, module_id: ModuleID, chat_id: ChatID, member_id: ChatID, build_dummy: bool = False) -> \
            Optional[ETMChatMember]:
        chat = self.get_chat(module_id, chat_id, build_dummy)
        if chat is None:
            return None
        try:
            return chat.get_member(member_id)
        except KeyError:
            pass
        if not build_dummy:
            return None
        return chat.add_system_member(name=member_id, uid=member_id)

    def update_chat_obj(self, chat: Chat, full_update: bool = False) -> ETMChatType:
        """Insert or update chat object to cache.
        Only checking name and alias, not checking group/member association,
        unless full update is requested.
        """
        key = self.get_cache_key(chat)
        self.logger.debug("Trying to update key %s with object %s. Full update: %s", key, chat, full_update)
        if key not in self.cache:
            self.logger.debug("Key %s is not in cache. Do compound enrol.", key)
            return self.compound_enrol(chat)

        cached = cast(ETMChatType, self.cache[key])
        self.logger.debug("Cached object found with key %s.", key)

        if full_update:
            etm_chat = convert_chat(self.db, chat)
            cached.name = etm_chat.name
            cached.alias = etm_chat.alias
            cached.description = etm_chat.description
            cached.vendor_specific = etm_chat.vendor_specific
            cached.notification = etm_chat.notification
            cached.members = self.update_chat_members(cached, etm_chat.members, full_update)
            cached.update_to_db()
        else:
            if chat.name != cached.name or \
                    chat.alias != cached.alias or \
                    chat.notification != cached.notification or \
                    chat.description != cached.description:
                cached.name = chat.name
                cached.alias = chat.alias
                cached.notification = chat.notification
                cached.description = chat.description
                cached.update_to_db()
        return cached

    def update_chat_members(self,
                            chat: ETMChatType,
                            members: MutableSequence[ETMChatMember],
                            full_update: bool = False) -> MutableSequence[ETMChatMember]:
        """Update chat members. Overwrite, add, and remove member objects if needed."""
        cached_objs = {(i.module_id, i.uid): i for i in chat.members}
        chat.members = []
        for i in members:
            idx = (i.module_id, i.uid)
            if idx in cached_objs:
                chat.members.append(self.update_chat_member_obj(cached_objs[idx], i))
            else:
                i.chat = chat
                chat.members.append(i)
        return chat.members

    @staticmethod
    def get_or_enrol_member(cached: ETMChatType, member: ChatMember) -> ETMChatMember:
        # TODO: Add test case for this
        try:
            return cached.get_member(member.uid)
        except KeyError:
            cached_member: ETMChatMember
            if isinstance(member, SystemChatMember):
                cached_member = cached.add_system_member(name=member.name, alias=member.alias, uid=member.uid,
                                                         vendor_specific=member.vendor_specific.copy(),
                                                         description=member.description)
            elif isinstance(member, SelfChatMember):
                cached_member = cached.add_self()
            else:
                cached_member = cached.add_member(name=member.name, alias=member.alias, uid=member.uid,
                                                  vendor_specific=member.vendor_specific.copy(),
                                                  description=member.description)
            cached_member.module_id = member.module_id
            cached_member.module_name = member.module_name
            cached_member.channel_emoji = member.channel_emoji
            return cached_member

    @staticmethod
    def update_chat_member_obj(cached: ETMChatMember, member: ETMChatMember,
                               full_update: bool = False) -> ETMChatMember:
        """Insert or update chat member object to cache.
        Only checking name and alias, not checking group/member association,
        unless full update is requested.
        """
        if full_update:
            cached.name = member.name
            cached.alias = member.alias
            cached.description = member.description
            cached.vendor_specific = member.vendor_specific
        else:
            if member.name != cached.name or \
                    member.alias != cached.alias or \
                    member.description != cached.description:
                cached.name = member.name
                cached.alias = member.alias
                cached.description = member.description
        return cached

    def delete_chat_object(self, module_id: ModuleID, chat_id: ChatID):
        """Remove chat object from cache."""
        key = (module_id, chat_id)
        if key not in self.cache:
            return
        self.cache.pop(key)

    def delete_chat_members(self, module_id: ModuleID, chat_id: ChatID, member_ids: Collection[ChatID]):
        """Remove chat member objects from cache."""
        key = (module_id, chat_id)
        if key not in self.cache:
            return
        chat = self.cache[key]
        member_ids = set(member_ids)
        chat.members = [i for i in chat.members if i.uid not in member_ids]

    @property
    def all_chats(self) -> Iterator[ETMChatType]:
        """Return all chats that is not a group member and not myself."""
        return (val for val in self.cache.values() if isinstance(val, ETMChatType))
