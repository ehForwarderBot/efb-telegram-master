from pytest import mark
from telethon.tl.custom import Message

from .helper.filters import in_chats
from .utils import link_chats, assert_is_linked

pytestmark = mark.asyncio


async def test_unlink_all_private(helper, client, bot_id, slave, channel):
    await client.send_message(bot_id, "/unlink_all")
    content: str = await helper.wait_for_message_text(in_chats(bot_id))
    assert "/unlink_all" in content


async def test_unlink_all_group_empty(helper, client, bot_group, slave, channel):
    with link_chats(channel, tuple(), bot_group):
        await client.send_message(bot_group, "/unlink_all")
        await helper.wait_for_message(in_chats(bot_group))
        assert_is_linked(channel, tuple(), bot_group)


async def test_unlink_all_group_linked(helper, client, bot_group, slave, channel):
    with link_chats(channel, slave.get_chats_by_criteria(alias=True, avatar=True), bot_group):
        await client.send_message(bot_group, "/unlink_all")
        await helper.wait_for_message(in_chats(bot_group))
        assert_is_linked(channel, tuple(), bot_group)


async def test_unlink_all_channel_linked(helper, client, bot_channel, bot_id, slave, channel):
    with link_chats(channel, slave.get_chats_by_criteria(alias=True, avatar=True), bot_channel):
        message: Message = await client.send_message(bot_channel, "/unlink_all")
        await message.forward_to(bot_id)
        await helper.wait_for_message(in_chats(bot_id))
        assert_is_linked(channel, tuple(), bot_channel)
