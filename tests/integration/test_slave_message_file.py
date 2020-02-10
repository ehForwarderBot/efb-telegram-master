from abc import abstractmethod, ABC
from itertools import chain
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, List, Tuple

from pytest import mark, approx
from telegram import MAX_FILESIZE_UPLOAD
from telethon.tl.custom import Message
from telethon.tl.types import MessageEntityMentionName, MessageEntityCode

from ehforwarderbot import Chat
from ehforwarderbot import Message as EFBMessage
from ehforwarderbot.chat import SelfChatMember
from ehforwarderbot.message import LinkAttribute, LocationAttribute, MsgType
from tests.integration.helper.filters import in_chats, edited, reply_to, regex
from tests.integration.utils import link_chats
from tests.mocks.slave import MockSlaveChannel

pytestmark = mark.asyncio


async def test_slave_message_file_oversize(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_group),\
            NamedTemporaryFile(suffix=".bin") as f:
        # Write a large enough file
        f.truncate(MAX_FILESIZE_UPLOAD + 1024 * 10)
        f.seek(0)

        # Send it
        efb_msg = slave.send_file_like_message(MsgType.File, Path(f.name), mime="application/octet-stream",
                                               chat=chat, author=chat.other, commands=True)

        # Expect a text message and an error message
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        assert not tg_msg.file
        await helper.wait_for_message(in_chats(bot_group) & reply_to(tg_msg.id))
