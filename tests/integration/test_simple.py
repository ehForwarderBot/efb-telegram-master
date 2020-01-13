import re

from pytest import mark
from telethon.tl.custom import Message

from ehforwarderbot.__version__ import __version__ as efb_version
from .helper.filters import in_chats, regex
from .utils import link_chats

pytestmark = mark.asyncio


async def test_start(helper, client, bot_id):
    await client.send_message(bot_id, "/start")
    text = await helper.wait_for_message_text(in_chats(bot_id))
    assert "EFB" in text


async def test_help(helper, client, bot_id):
    await client.send_message(bot_id, "/help")
    text = await helper.wait_for_message_text(in_chats(bot_id))
    for i in ("/link", "/chat", "/extra", "/unlink_all", "/info", "/react",
              "/update_info", "/rm", "/help"):
        assert i in text


async def test_info_bot(helper, client, bot_id, coordinator, channel, slave):
    await client.send_message(bot_id, "/info")
    text = await helper.wait_for_message_text(in_chats(bot_id))

    # Expect EFB framework info
    assert efb_version in text
    assert coordinator.profile in text

    # Expect ETM info
    assert channel.__version__ in text
    if channel.instance_id:
        assert channel.instance_id in text

    # Expect slave channel info
    assert slave.channel_emoji in text
    assert slave.channel_name in text
    assert slave.channel_id in text
    assert slave.__version__ in text


async def test_info_chat(helper, client, bot_group, channel, slave):
    # Not linked
    group_name = (await client.get_entity(bot_group)).title
    await client.send_message(bot_group, "/info")
    text = await helper.wait_for_message_text(in_chats(bot_group))
    assert group_name in text
    assert str(bot_group) in text
    assert "/link" in text

    # Linked group
    with link_chats(channel, (
        slave.unknown_chat,
        slave.unknown_channel,
        slave.chat_with_alias
    ), bot_group):
        await client.send_message(bot_group, "/info")
        text = await helper.wait_for_message_text(in_chats(bot_group))

        # Group info
        assert group_name in text
        assert str(bot_group) in text

        # Unknown channel
        assert slave.unknown_channel.module_id in text
        assert slave.unknown_channel.uid in text

        # Unknown chat
        assert slave.unknown_chat.module_id in text
        assert slave.unknown_chat.module_name in text
        assert slave.unknown_chat.uid in text

        # Known chat
        assert slave.chat_with_alias.module_id in text
        assert slave.chat_with_alias.module_name in text
        assert slave.chat_with_alias.uid in text
        assert slave.chat_with_alias.name in text
        assert slave.chat_with_alias.alias in text


async def test_info_channel(helper, client, bot_id, bot_channel, channel, slave):
    # Not linked
    group_name = (await client.get_entity(bot_channel)).title
    message: Message = await client.send_message(bot_channel, "/info")
    await message.forward_to(bot_id)
    text = await helper.wait_for_message_text(in_chats(bot_id))
    assert group_name in text
    assert str(bot_channel) in text
    assert "/link" in text

    # Linked group
    with link_chats(channel, (
        slave.unknown_chat,
        slave.unknown_channel,
        slave.chat_with_alias
    ), bot_channel):
        message: Message = await client.send_message(bot_channel, "/info")
        await message.forward_to(bot_id)
        text = await helper.wait_for_message_text(in_chats(bot_id))

        # Group info
        assert group_name in text
        assert str(bot_channel) in text

        # Unknown channel
        assert slave.unknown_channel.module_id in text
        assert slave.unknown_channel.uid in text

        # Unknown chat
        assert slave.unknown_chat.module_id in text
        assert slave.unknown_chat.module_name in text
        assert slave.unknown_chat.uid in text

        # Known chat
        assert slave.chat_with_alias.module_id in text
        assert slave.chat_with_alias.module_name in text
        assert slave.chat_with_alias.uid in text
        assert slave.chat_with_alias.name in text
        assert slave.chat_with_alias.alias in text


async def test_extra_echo(helper, client, bot_id, bot_channel, channel, slave):
    # Get command list
    await client.send_message(bot_id, "/extra")
    text = await helper.wait_for_message_text(in_chats(bot_id) & regex("echo"))
    assert slave.echo.name in text

    cmd_match = re.search(r'/[a-zA-Z0-9_-]+echo', text)
    assert cmd_match is not None, "Help text of echo command should be found."
    command = cmd_match.group()

    # Get command help
    await client.send_message(bot_id, command)
    text = await helper.wait_for_message_text(in_chats(bot_id))

    cmd_match = re.search(r'/[a-zA-Z0-9_-]+echo', text)
    assert cmd_match is not None, "Echo command should be found."
    command = cmd_match.group()
    assert slave.echo.name in text
    assert slave.echo.desc.format(function_name=command) in text

    # Run command
    content = "信じたものは、都合のいい妄想を繰り返し映し出す鏡。"
    await client.send_message(bot_id, f"{command} {content}")
    await helper.wait_for_event(in_chats(bot_id) & regex(content))
