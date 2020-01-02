import asyncio
import logging
import time
from typing import Set

import pytest
from telethon import TelegramClient

from .helper.helper import TelegramIntegrationTestHelper
from ..bot import get_user_session

pytest.register_assert_rewrite("tests.integration.utils")


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for all test cases."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def user_session_info():
    return get_user_session()


@pytest.fixture(scope="session")
def user_session(user_session_info) -> str:
    return user_session_info['user_session']


@pytest.fixture(scope="session")
def api_id(user_session_info) -> int:
    return user_session_info['api_id']


@pytest.fixture(scope="session")
def api_hash(user_session_info) -> str:
    return user_session_info['api_hash']


@pytest.fixture(scope="session")
def filter_chats(bot_id, bot_groups, bot_channels) -> Set[int]:
    """Only receive updates from the following chats"""
    chats = set()
    chats.add(bot_id)
    chats = chats.union(bot_groups)
    chats = chats.union(bot_channels)
    return chats


@pytest.fixture(scope="session")
async def helper_wrap(event_loop, user_session, api_id, api_hash, bot_id,
                      filter_chats) -> TelegramIntegrationTestHelper:
    async with TelegramIntegrationTestHelper(
            user_session, api_id, api_hash, event_loop, bot_id,
            chats=filter_chats
    ) as helper:
        yield helper


@pytest.fixture(scope="function")
async def helper(helper_wrap, slave) -> TelegramIntegrationTestHelper:
    """Clean the message queue before each test."""
    helper_wrap.clear_queue()
    assert helper_wrap.queue.empty()
    slave.clear_messages()
    assert slave.messages.empty()
    slave.clear_statuses()
    assert slave.statuses.empty()
    yield helper_wrap


@pytest.fixture(scope="module")
def poll_bot(channel):
    logging.root.setLevel(logging.DEBUG)
    # peewee.logger.setLevel(logging.DEBUG)
    channel.bot_manager.polling(clean=True)
    time.sleep(1)
    yield channel.bot_manager
    channel.bot_manager.graceful_stop()


@pytest.fixture(scope="session")
async def client(helper_wrap) -> TelegramClient:
    yield helper_wrap.client
