# coding: utf-8
"""
Manage chat destination
Adapted from messud4312 ( https://my.oschina.net/u/914655/blog/1799159 ).
"""

import time
from collections import deque
from weakref import WeakValueDictionary

from typing import Deque, Optional

from .utils import EFBChannelChatIDStr

CHAT_DEST_CACHE_SIZE = 20
"""Number of records to be kept in the cache."""
CHAT_DEST_CACHE_TIMEOUT = 60 * 60
"""Number of seconds for the cache to be valid."""


class ChatDestination:
    """Data class encapsulating last chat destination from a Telegram chat.

    Attributes:
        destination (str): Chat destination string
        expiry (float): Expiry time of this record
    """

    def __init__(self, destination: EFBChannelChatIDStr, timeout: float):
        self.destination: EFBChannelChatIDStr = destination
        self.expiry: float = time.time() + timeout
        self.warned: bool = False

    def update_timeout(self, timeout: float):
        self.expiry = time.time() + timeout


class ChatDestinationCache:
    def __init__(self, mode: str, size: int = CHAT_DEST_CACHE_SIZE):
        self.enabled = mode in ('enabled', 'warn')
        if self.enabled:
            # noinspection PyUnresolvedReferences
            self.weak: 'WeakValueDictionary[str, ChatDestination]' = WeakValueDictionary()
            self.strong: Deque[ChatDestination] = deque(maxlen=size)

    def get(self, key: str) -> Optional[EFBChannelChatIDStr]:
        if not self.enabled:
            return None
        val = self.weak.get(key, None)
        if val is not None:
            if time.time() > val.expiry:
                # Remove entry on expiry
                self.strong.remove(val)
                self.weak.pop(key)
                return None
            else:
                return val.destination
        return None

    def is_warned(self, key: str) -> bool:
        if not self.enabled:
            return True
        return key in self.weak and self.weak[key].warned

    def set_warned(self, key: str):
        if not self.enabled:
            return
        if key in self.weak:
            self.weak[key].warned = True

    def set(self, key: str, value: EFBChannelChatIDStr, timeout: float = CHAT_DEST_CACHE_TIMEOUT):
        if not self.enabled:
            return
        # Just update timeout if destination is same
        if key in self.weak and self.weak[key].destination == value:
            self.weak[key].update_timeout(timeout)
        else:
            # strong_ref prevent object from being collected by gc.
            self.weak[key] = strong_ref = ChatDestination(value, timeout)
            # Enqueue the element and waiting to be collected by gc once popped.
            self.strong.append(strong_ref)

    def remove(self, key: str):
        if not self.enabled:
            return
        return self.weak.pop(key, None)
