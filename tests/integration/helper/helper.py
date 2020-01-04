import asyncio
import logging
import os
import time
from asyncio import QueueEmpty
from typing import Tuple, Optional, Dict, Iterable

from telethon import TelegramClient
from telethon.events import NewMessage, UserUpdate, MessageDeleted, MessageEdited, ChatAction
from telethon.events.common import EventCommon
from telethon.sessions import StringSession
from telethon.tl.custom import Message
from telethon.tl.types import TypeInputPeer

from . import filters
from .filters import BaseFilter
from .utils import parse_socks5_link


class TelegramIntegrationTestHelper:
    def __init__(self,
                 session: str, api_id: int, api_hash: str,
                 loop: asyncio.AbstractEventLoop,
                 bot_id: int,
                 chats: Iterable[int] = tuple()):
        """
        Need to create a client with API key, hash, and a session file
        Need a list of whitelisted chat IDs

        Create a queue for incoming messages.

        Args:
            session: Session authorization string
            api_id: API ID of Telegram client
            api_hash: API Hash of Telegram client
            loop: Event loop to run the client on, (can be provided by ``pytest-asyncio``)
        """

        # Build proxy parameters
        # Currently only support SOCKS5 proxy in ALL_PROXY environment variable
        proxy_env = os.environ.get('all_proxy') or os.environ.get('ALL_PROXY')
        if proxy_env and proxy_env.startswith('socks5://'):
            from socks import SOCKS5
            hostname, port, username, password = parse_socks5_link(proxy_env)
            proxy: Optional[Tuple] = (SOCKS5, hostname, port, True, username, password)
        else:
            proxy = None

        # Telethon client to use
        self.client: TelegramClient = TelegramClient(
            StringSession(session), api_id, api_hash, proxy=proxy, loop=loop,
            sequential_updates=True
        )

        # Queue for incoming messages
        self.queue: "asyncio.queues.Queue[EventCommon]" = asyncio.queues.Queue()

        # Collect mappings from message ID to its chat (as Telegram API is not sending them)
        self.message_chat_map: Dict[int, TypeInputPeer] = dict()

        self.chats = list(map(abs, chats))
        self.client.parse_mode = "html"
        self.client.add_event_handler(self.new_message_handler,
                                      NewMessage(chats=self.chats, incoming=True, from_users=[bot_id]))
        # self.client.add_event_handler(self.new_message_handler,
        #                               NewMessage(incoming=True))
        self.client.add_event_handler(self.deleted_message_handler, MessageDeleted())
        self.client.add_event_handler(self.update_handler, UserUpdate(chats=self.chats))
        self.client.add_event_handler(self.update_handler, MessageEdited(chats=self.chats))
        self.client.add_event_handler(self.update_handler, ChatAction(chats=self.chats))

        self.logger = logging.getLogger(__name__)

    async def update_handler(self, event):
        self.logger.debug("Got event, %s, %s", time.time(), event.to_dict())
        await self.queue.put(event)

    def clear_queue(self):
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except QueueEmpty:
                return

    async def new_message_handler(self, event: NewMessage.Event):
        # record the mapping of message ID and its chat
        message: Message = event.message
        self.message_chat_map[message.id] = await message.get_input_chat()
        self.logger.debug("Got new message event, %s, %s", time.time(), event.to_dict())
        await self.queue.put(event)

    async def deleted_message_handler(self, event: MessageDeleted.Event):
        # Try to recover chat of the message from the mapping
        message_id = event.deleted_id
        if event._chat_peer is None and message_id in self.message_chat_map:
            input_peer = self.message_chat_map[message_id]
            event._chat_peer = input_peer
            del self.message_chat_map[message_id]
        self.logger.debug("Got deleted message event, %s, %s", time.time(), event.to_dict())
        await self.queue.put(event)

    async def wait_for_event(self, event_filter: BaseFilter = filters.everything,
                             timeout: float = 10.0) -> EventCommon:
        """
        Args:
            event_filter: Filter updates to collect
            timeout: raises an exception when no update is found in the
                indicated time

        Returns:
            the update

        Raises:
            :exc:`asyncio.TimeoutError`: when the request timed out
        """
        t = time.time() + timeout
        while t > time.time():
            time_left = t - time.time()
            # print("START TO WAIT FOR EVENTS")
            value = await asyncio.wait_for(self.queue.get(), time_left)
            self.queue.task_done()
            # print("EVENT", time.time(), value)
            if callable(event_filter) and event_filter(value):
                return value
            elif event_filter is None:
                return value

    async def wait_for_message(self, event_filter: BaseFilter = filters.everything,
                               timeout: float = 10.0) -> Message:
        """Short cut for “Wait for a message and return its entity”."""
        event = await self.wait_for_event(filters.message & event_filter, timeout=timeout)
        # noinspection PyUnresolvedReferences
        return event.message  # type: ignore

    async def wait_for_message_text(self, event_filter: BaseFilter = filters.everything,
                                    timeout: float = 10.0) -> str:
        """Short cut for “Wait for a text message and return its text”."""
        event = await self.wait_for_event(filters.text & event_filter, timeout=timeout)
        # noinspection PyUnresolvedReferences
        return event.message.text  # type: ignore

    # Context management
    # ------------------

    async def __aenter__(self) -> 'TelegramIntegrationTestHelper':
        await self.client.connect()

        # Issue a high level command to start receiving message
        await self.client.get_me()
        # Fill the entity cache
        await self.client.get_dialogs()

        return self

    def __enter__(self) -> 'TelegramIntegrationTestHelper':
        """
        Start the client and return the helper

        Returns:
            self
        """
        self.client.loop.run_until_complete(self.__aenter__())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.disconnect()
        await self.client.disconnected

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Trigger the event to end the main async task."""
        self.client.loop.run_until_complete(self.__aexit__(exc_type, exc_val, exc_tb))
