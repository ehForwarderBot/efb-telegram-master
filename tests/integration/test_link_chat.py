import re
from itertools import chain
from typing import List, Optional

from pytest import mark
from telethon.errors import MessageIdInvalidError
from telethon.tl.custom import Message, MessageButton
from telethon.tl.types import MessageEntityCode

from ehforwarderbot import Chat
from .helper.filters import in_chats, has_button, edited, regex, text
from .utils import link_chats, assert_is_linked, unlink_all_chats

retry_on_message_id_invalid_error = mark.flaky(
    max_runs=2, min_passes=1,  # default value
    rerun_filter=lambda err, *_: issubclass(err[0], MessageIdInvalidError))
"""Retry on ``MessageIdInvalidError`` due to flaky behavior of MTProto API"""

pytestmark = [mark.asyncio, retry_on_message_id_invalid_error]


async def test_link_chat_cancel(helper, client, bot_id, slave):
    await client.send_message(bot_id, "/link")
    message = await helper.wait_for_message(in_chats(bot_id) & has_button)

    # Cancel the message (cancel button)
    await message.click(text="Cancel")
    # Wait message to be cancelled: cancelled message should be an edited one
    # with no button.
    await helper.wait_for_event(in_chats(bot_id) & edited(message.id) & ~has_button)


async def test_link_chat_private_filter(helper, client, bot_id, slave):
    # Only testing one filter example.
    # Other chat filter examples are tested in unit test
    # (test_etm_chat.py::test_etm_chat_match)
    await client.send_message(bot_id, "/link type: user")
    message = await helper.wait_for_message(in_chats(bot_id) & has_button)

    slave_users = slave.get_chats_by_criteria(chat_type="PrivateChat")
    for row in message.buttons[:-1]:
        button: MessageButton = row[0]
        assert any(user.display_name in button.text for user in slave_users), f"{button.text} should be a user"

    # Cancel the message (cancel button)
    await message.click(text="Cancel")


async def test_unlink_unavailable_chat(helper, client, bot_group, slave, channel):
    with link_chats(channel, (slave.chat_with_alias, slave.unknown_chat), bot_group):
        await client.send_message(bot_group, "/link")
        message = await helper.wait_for_message(in_chats(bot_group) & has_button)

        assert message.button_count == 3, f"{message.buttons} should be one known, one unknown, one cancel"
        await message.click(i=1, j=0)  # click the unknown chat

        message = await helper.wait_for_message(in_chats(bot_group) & has_button)
        await message.click(text="Restore")
        await helper.wait_for_message(in_chats(bot_group))

        assert_is_linked(channel, (slave.chat_with_alias,), bot_group)


async def test_link_chat_private_filter_invalid_regex(helper, client, bot_id, slave):
    # Invalid regular expression filter should fall back to simple string matching
    # This is done in integration test as the logic is a part of chat_binding.slave_chats_pagination
    # Issue a command with an invalid regex filter
    await client.send_message(bot_id, "/link (")
    message = await helper.wait_for_message(in_chats(bot_id) & has_button)

    # Cancel the message (cancel button)
    await message.click(text="Cancel")


async def test_link_chat_pagination(helper, client, bot_id, slave):
    await client.send_message(bot_id, "/link")
    message: Message = await helper.wait_for_message(in_chats(bot_id) & has_button)
    content = message.text

    assert slave.channel_emoji in content
    assert slave.channel_name in content

    buttons: List[List[MessageButton]] = message.buttons

    # Test pagination
    assert message.button_count > 2, "more than 2 buttons found on the chats list."
    assert ">" in buttons[-1][-1].text, "Next page button exists"
    # Go to next page
    await buttons[-1][-1].click()
    message = await helper.wait_for_message(in_chats(bot_id) & edited(message.id) & has_button)
    buttons = message.buttons
    assert "<" in buttons[-1][0].text, "Previous page button exists"
    # Go to previous page
    await message.mark_read()
    await buttons[-1][0].click()

    # Cancel the message (cancel button)
    await message.click(text="Cancel")


async def test_link_chat_private(helper, client, bot_id, bot_group, slave, channel):
    chat_0 = slave.chat_with_alias
    chat_1 = slave.chat_without_alias

    await client.send_message(bot_id, f"/link {chat_0.uid}")
    message: Message = await helper.wait_for_message(in_chats(bot_id) & has_button)
    choose_chat: MessageButton = message.buttons[0][0]
    assert chat_0.display_name in choose_chat.text

    # Choose chat
    await choose_chat.click()
    message: Message = await helper.wait_for_message(in_chats(bot_id) & edited(message.id) & has_button)
    url = ""
    manual_button: MessageButton = message.buttons[0][-1]
    for i in chain.from_iterable(message.buttons):
        if i.url:
            url = i.url
            break

    # Get link, manual link buttons
    assert url
    assert "manual" in manual_button.text.lower()
    await manual_button.click()
    message: Message = await helper.wait_for_message(in_chats(bot_id) & edited(message.id) & has_button)

    command: str = next(
        txt
        for _, txt in message.get_entities_text(MessageEntityCode)
        if txt.startswith("/start ")
    )
    token = command[len("/start "):]

    assert token == re.search(r"\?startgroup=(.+)", url).groups()[0], "URL token matches manual token"

    # Link chat_0 to bot_group
    await client.send_message(bot_group, command)
    await helper.wait_for_message(in_chats(bot_id) & text)

    # assert chat_0 is linked singly
    assert_is_linked(channel, (chat_0, ), bot_group)

    # link chat_1
    await simulate_link_chat(client, helper, chat_1, bot_id, bot_group)

    # assert chat_0 and chat_1 is linked
    assert_is_linked(channel, (chat_0, chat_1), bot_group)

    # unlink all via db
    unlink_all_chats(channel, bot_group)


async def test_link_chat_multi_link_flag_off(helper, client, bot_id, bot_group, slave, channel):
    chat_0 = slave.chat_with_alias
    chat_1 = slave.chat_without_alias

    backup = channel.flag.config['multiple_slave_chats']
    channel.flag.config['multiple_slave_chats'] = False

    with link_chats(channel, (chat_0, ), bot_group):
        assert_is_linked(channel, (chat_0,), bot_group)
        await simulate_link_chat(client, helper, chat_1, bot_id, bot_group)
        assert_is_linked(channel, (chat_1,), bot_group)

    channel.flag.config['multiple_slave_chats'] = backup


async def test_link_chat_group_unlinked(helper, client, bot_id, bot_group, channel):
    with link_chats(channel, tuple(), bot_group):
        await client.send_message(bot_group, f"/link")
        message: Message = await helper.wait_for_message(in_chats(bot_id) & has_button)
        await message.click(text="Cancel")


async def test_link_chat_group_linked_unlink(helper, client, bot_id, bot_group, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_group):
        await client.send_message(bot_group, f"/link")
        message: Message = await helper.wait_for_message(in_chats(bot_group) & has_button)
        assert 2 == len(message.buttons), "link message in group should have 2 rows"
        assert chat.display_name in message.buttons[0][0].text
        await message.click(0)

        message: Message = await helper.wait_for_message(in_chats(bot_group) & edited(message.id) & has_button)
        assert (await message.click(text="Restore")) is not None, "Restore"

        await helper.wait_for_message(in_chats(bot_group) & edited(message.id) & ~has_button)

        assert_is_linked(channel, tuple(), bot_group)


async def test_link_chat_group_linked_relink(helper, client, bot_id, bot_group, bot_channel, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_channel):
        await simulate_link_chat(client, helper, chat, bot_id, bot_group, command_channel=bot_channel)
        assert_is_linked(channel, tuple(), bot_channel)
        assert_is_linked(channel, (chat,), bot_group)


async def test_link_chat_channel(helper, client, bot_id, bot_group, bot_channel, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, tuple(), bot_channel):
        await simulate_link_chat(client, helper, chat, bot_id, bot_id, dest_channel=bot_channel)
        assert_is_linked(channel, (chat,), bot_channel)


async def test_link_chat_channel_linked_cancel(helper, client, bot_id, bot_channel, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_channel):
        message: Message = await client.send_message(bot_channel, f"/link")
        await message.forward_to(bot_id)

        message = await helper.wait_for_message(in_chats(bot_id) & has_button)
        assert 2 == len(message.buttons), "link message from channel should have 2 rows"
        await message.click(text="Cancel")


async def test_link_chat_target_incoming_message(helper, client, bot_id, slave, channel):
    chat = slave.chat_with_alias
    efb_msg = slave.send_text_message(chat, chat.other)

    incoming_msg = await helper.wait_for_message(in_chats(bot_id) & regex(re.escape(efb_msg.text)))
    await client.send_message(bot_id, f"/link", reply_to=incoming_msg)

    message = await helper.wait_for_message(in_chats(bot_id) & has_button)
    assert chat.display_name in message.raw_text
    await message.click(text="Cancel")


async def simulate_link_chat(client, helper, chat: Chat, command_chat: int, dest_chat: int,
                             command_channel: Optional[int] = None, dest_channel: Optional[int] = None):
    """Simulate the procedure of linking a chat.

    Provide command_channel to link from a channel.
    """
    if command_channel is not None:
        message = await client.send_message(command_channel, f"/link {chat.uid}")
        await message.forward_to(command_chat)
    else:
        await client.send_message(command_chat, f"/link {chat.uid}")
    message = await helper.wait_for_message(in_chats(command_chat) & has_button)  # chat list
    await message.buttons[0][0].click()  # choose chat
    message = await helper.wait_for_message(in_chats(command_chat) & has_button)  # operation panel
    url = None
    # print("STIMULATE_LINK_CHAT_MESSAGE_DICT", message.to_dict())
    for i in chain.from_iterable(message.buttons):
        if i.url:
            url = i.url
            break
    token = re.search(r"\?startgroup=(.+)", url).groups()[0]
    command = f"/start {token}"
    if dest_channel:
        message = await client.send_message(dest_channel, command)
        await message.forward_to(dest_chat)
    else:
        await client.send_message(dest_chat, command)
    await helper.wait_for_message(in_chats(command_chat) & text)
