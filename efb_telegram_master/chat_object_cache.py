from typing import TYPE_CHECKING, Optional, Dict, Tuple, Iterator
from ehforwarderbot import coordinator
from ehforwarderbot.chat import EFBChat
from ehforwarderbot.constants import ChatType
from ehforwarderbot.types import ModuleID, ChatID
from ehforwarderbot.exceptions import EFBChatNotFound

from .chat import ETMChat

if TYPE_CHECKING:
    from . import TelegramChannel


class ChatObjectCacheManager:
    """Maintain and update chat objects from all slave channels and
    middlewares.
    """

    # Cache storage
    # Key: module_id, chat_id, group_id (if available)
    CacheKey = Tuple[ModuleID, ChatID, Optional[ChatID]]
    cache: Dict[CacheKey, ETMChat] = dict()

    def __init__(self, channel: 'TelegramChannel'):
        self.channel = channel
        self.db = channel.db
        self.self = ETMChat(db=self.db, channel=self.channel).self()

        # load all chats from all slave channels and convert to ETMChat object
        for channel_id, channel in coordinator.slaves.items():
            # noinspection PyBroadException
            try:
                chats = channel.get_chats()
            except Exception:
                continue
            for chat in chats:
                self.compound_enrol(chat)

    def compound_enrol(self, chat: EFBChat) -> ETMChat:
        """Convert and enrol a chat object for the first time.
        This method also enrols all members if the chat is a group.
        """
        etm_chat = ETMChat(db=self.db, chat=chat)
        if etm_chat.chat_type == ChatType.Group:
            for i in etm_chat.members:
                self.enrol(i)
        self.enrol(etm_chat)

        return etm_chat

    def enrol(self, chat: ETMChat):
        """Add a chat object to the cache storage *for the first time*.

        This would not update the cached object upon conflicting.
        """
        key = self.get_cache_key(chat)
        self.cache[key] = chat

    @staticmethod
    def get_cache_key(chat: EFBChat) -> CacheKey:
        module_id = chat.module_id
        chat_id = chat.chat_uid
        group_id = None
        if chat.group:
            group_id = chat.group.chat_uid
        return module_id, chat_id, group_id

    def get_chat(self, module_id: ModuleID, chat_id: ChatID,
                 group_id: Optional[ChatID] = None) -> Optional[ETMChat]:
        """
        Get an ETMChat object of a chat from cache.

        If the object queried is not found, try to get from database cache,
        then the relevant channel.
        If still not found, return None.
        """
        key = (module_id, chat_id, group_id)
        if key in self.cache:
            return self.cache[key]
        # TODO: Should it return unassociated chat object if the one in group is not found?
        # key = (channel, chat_id, None)
        # if key in self.cache:
        #     return self.cache[key]

        c_log = self.db.get_slave_chat_info(module_id, chat_id, group_id)
        if c_log is not None and c_log.pickle:
            obj = ETMChat.unpickle(c_log.pickle, self.db)
            self.compound_enrol(obj)
            return obj

        # Only look up from slave channels as middlewares don’t have get_chat_by_id method.
        if module_id not in coordinator.slaves:
            return None
        try:
            chat_obj = coordinator.slaves[module_id].get_chat(chat_id, group_id)
            return self.compound_enrol(chat_obj)
        except EFBChatNotFound:
            return None

    def update_chat_obj(self, chat: EFBChat, full_update: bool = False) -> ETMChat:
        """Insert or update chat object to cache.
        Only checking name and alias, not checking group/member association,
        unless full update is requested.
        """
        key = self.get_cache_key(chat)
        if key not in self.cache:
            return self.compound_enrol(chat)

        cached = self.cache[key]

        if full_update:
            cached.chat_name = chat.chat_name
            cached.chat_alias = chat.chat_alias
            cached.chat_type = chat.chat_type
            cached.is_chat = chat.is_chat
            cached.vendor_specific = chat.vendor_specific
            cached.notification = chat.notification
            if chat.members:
                cached.members = [self.update_chat_obj(i, full_update) for i in chat.members]
            else:
                cached.members = chat.members
            cached.update_to_db()
        else:
            if chat.chat_name != cached.chat_name or \
                    chat.chat_alias != cached.chat_alias or \
                    chat.notification != cached.notification:
                cached.chat_name = chat.chat_name
                cached.chat_alias = chat.chat_alias
                cached.notification = chat.notification
                cached.update_to_db()
        return cached

    def delete_chat_object(self, module_id: ModuleID, chat_id: ChatID, group_id: Optional[ChatID] = None):
        """Remove chat object from cache.

        Removing members of a group too if available.
        """
        key = (module_id, chat_id, group_id)
        if key not in self.cache:
            return
        chat = self.cache.pop(key)
        if chat.members:
            for i in chat.members:
                key = (module_id, i.chat_uid, chat_id)
                if key in self.cache:
                    del self.cache[key]

    @property
    def all_chats(self) -> Iterator[ETMChat]:
        return (val for key, val in self.cache.items() if key[2] is None)
