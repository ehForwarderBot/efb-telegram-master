from contextlib import suppress
from typing import Optional
from unittest.mock import patch
from uuid import uuid4

from pytest import mark
from telethon.tl.custom import Message, InlineResults
from telethon.tl.functions.messages import GetStickerSetRequest, GetInlineBotResultsRequest
from telethon.tl.types import InputStickerSetAnimatedEmoji, Document, PollAnswer, \
    InputMediaPoll, Poll
from telethon.tl.types.messages import StickerSet

from .utils import link_chats

pytestmark = mark.asyncio


async def test_master_msg_animated_sticker(helper, client, bot_group, slave, channel):
    # Get animated sticker document
    animated_sticker_set: StickerSet = await client(GetStickerSetRequest(InputStickerSetAnimatedEmoji()))
    sticker: Document = animated_sticker_set.documents[-1]
    assert sticker.mime_type == "application/x-tgsticker"

    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_group):
        slave.clear_messages()
        await client.send_file(bot_group, sticker)
        await helper.wait_for_message_text()
        assert slave.messages.empty()


async def test_master_msg_game(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_group):
        # Send game message via @gamebot (official)
        # Not using client.inline_query as it does not support specifying chat to send queries
        game_bot = await client.get_input_entity("gamebot")
        input_group = await client.get_input_entity(bot_group)
        bot_results: InlineResults = InlineResults(
            client,
            await client(GetInlineBotResultsRequest(game_bot, input_group, "", ""))
        )
        assert len(bot_results) > 1, "there should be games from @gamebot"

        slave.clear_messages()
        # Send game message
        await bot_results[0].click(input_group)
        await helper.wait_for_message_text()
        assert slave.messages.empty()


def _build_poll(question: str, *answers: str, closed: Optional[bool] = None,
                id: int = 0) -> InputMediaPoll:
    """Build a poll object.
    Message construction adapted from Pyrogram.
    https://github.com/pyrogram/pyrogram/blob/develop/pyrogram/client/methods/messages/send_poll.py
    https://github.com/pyrogram/pyrogram/blob/develop/pyrogram/client/methods/messages/stop_poll.py"""
    return InputMediaPoll(Poll(
        id=id, question=question, answers=[
            PollAnswer(text=i, option=bytes([idx]))
            for idx, i in enumerate(answers)
        ],
        closed=closed
    ))


async def test_master_msg_poll(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias
    poll = _build_poll(f"Question {uuid4()}", "Answer 1", "Answer 2", "Answer 3")

    with link_chats(channel, (chat,), bot_group):
        slave.clear_messages()
        # Send poll
        message: Message = await client.send_message(bot_group, file=poll)
        await helper.wait_for_message_text()
        assert slave.messages.empty()
        # close poll
        poll = _build_poll("", closed=True, id=message.poll.poll.id)
        with suppress(AttributeError):
            # closing a poll with Telethon is throwing an exception for unknown
            # reason, but it doesn’t really bother us here.
            # https://github.com/LonamiWebs/Telethon/issues/1355
            await message.edit(file=poll)


async def test_master_msg_slave_not_supported(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias

    with link_chats(channel, (chat,), bot_group), \
         patch.multiple(slave, supported_message_types=set()):
        # Send poll
        await client.send_message(
            bot_group,
            "test_master_msg_slave_not_supported this shall be “unsupported by slave channel”")
        content = await helper.wait_for_message_text()
        assert slave.channel_name in content
