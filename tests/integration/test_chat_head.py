import re
from typing import List

from pytest import mark
from telethon.tl.custom import Message, MessageButton

from .helper.filters import in_chats, has_button, edited, regex
from .utils import link_chats

pytestmark = mark.asyncio


async def test_chat_head_private_cancel(helper, client, bot_id, slave):
    await client.send_message(bot_id, "/chat")
    message = await helper.wait_for_message(in_chats(bot_id) & has_button)

    # Cancel the message (cancel button)
    await message.click(text="Cancel")
    # Wait message to be cancelled: cancelled message should be an edited one
    # with no button.
    await helper.wait_for_event(in_chats(bot_id) & edited(message.id) & ~has_button)


async def test_chat_head_private(helper, client, bot_id, slave):
    await client.send_message(bot_id, "/chat")
    message: Message = await helper.wait_for_message(in_chats(bot_id) & has_button)
    content = message.text

    assert slave.channel_emoji in content
    assert slave.channel_name in content

    buttons: List[List[MessageButton]] = message.buttons

    # Test pagination
    assert message.button_count > 2, "more than 2 buttons found on the chats list."
    assert ">" in buttons[-1][-1].text, "Next page button exists"
    # Go to next page
    await message.mark_read()
    await buttons[-1][-1].click()
    message = await helper.wait_for_message(in_chats(bot_id) & edited(message.id) & has_button)
    buttons = message.buttons
    assert "<" in buttons[-1][0].text, "Previous page button exists"
    # Go to previous page
    await message.mark_read()
    await buttons[-1][0].click()

    # Choose the first
    message = await helper.wait_for_message(in_chats(bot_id) & edited(message.id) & has_button)
    buttons = message.buttons
    await message.mark_read()
    await buttons[0][0].click()

    # Wait for the chad head
    content = "test_chat_head_private this should be sent to slave channel"
    await helper.wait_for_message(in_chats(bot_id) & edited(message.id) & ~has_button)
    await client.send_message(bot_id, content, reply_to=message)

    efb_msg = slave.messages.get(timeout=5)  # raises queue.Empty upon timeout
    slave.messages.task_done()

    assert efb_msg.text == content


async def test_chat_head_singly_linked(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat, ), bot_group):
        await client.send_message(bot_group, "/chat")
        content: str = await helper.wait_for_message_text(in_chats(bot_group) & regex(chat.name))

        assert chat.name in content
        assert chat.alias in content
        assert chat.channel_emoji in content
        assert chat.module_name in content


async def test_chat_head_singly_linked_unknown_chat(helper, client, bot_group, slave, channel):
    chat = slave.unknown_chat
    with link_chats(channel, (chat,), bot_group):
        await client.send_message(bot_group, "/chat")
        content: str = await helper.wait_for_message_text(in_chats(bot_group) & regex(chat.uid))

        assert chat.uid in content
        assert chat.module_name in content
        assert chat.module_id in content


async def test_chat_head_singly_linked_unknown_channel(helper, client, bot_group, slave, channel):
    chat = slave.unknown_channel
    with link_chats(channel, (chat,), bot_group):
        await client.send_message(bot_group, "/chat")
        content: str = await helper.wait_for_message_text(in_chats(bot_group) & regex(chat.uid))

        assert chat.uid in content
        assert chat.module_id in content


async def test_chat_head_multi_linked(helper, client, bot_group, slave, channel):
    chats = slave.get_chats()[:5]
    chat = chats[0]
    with link_chats(channel, chats, bot_group):
        await client.send_message(bot_group, "/chat")
        message: Message = await helper.wait_for_message(in_chats(bot_group) & has_button)

        assert len(chats) + 1 == len(message.buttons), f"buttons should have {len(chats)} + 1 rows"

        # Click the button for ``chat``
        pattern = r"(^|\W)" + re.escape(chat.name) + r"(\W|$)"
        await message.click(text=re.compile(pattern).search)

        # Wait for the chad head
        content = "test_chat_head_multi_linked this should be sent to slave channel"
        message: Message = await helper.wait_for_message(in_chats(bot_group) & edited(message.id) & ~has_button)
        await client.send_message(bot_group, content, reply_to=message)

        efb_msg = slave.messages.get(timeout=5)  # raises queue.Empty upon timeout
        slave.messages.task_done()

        assert efb_msg.chat == chat
        assert efb_msg.text == content


async def test_chat_head_private_filter(helper, client, bot_id, slave):
    # Only testing one filter example.
    # Other chat filter examples are tested in unit test
    # (test_etm_chat.py::test_etm_chat_match)
    await client.send_message(bot_id, "/chat type: group")
    message = await helper.wait_for_message(in_chats(bot_id) & has_button)

    slave_groups = slave.get_chats_by_criteria(chat_type='GroupChat')
    for row in message.buttons[:-1]:
        button: MessageButton = row[0]
        assert any(group.display_name in button.text for group in slave_groups), f"{button.text} should be a group"

    # Cancel the message (cancel button)
    await message.click(text="Cancel")


async def test_chat_head_private_filter_invalid_regex(helper, client, bot_id, slave):
    # Invalid regular expression filter should fall back to simple string matching
    # This is done in integration test as the logic is a part of chat_binding.slave_chats_pagination
    # Issue a command with an invalid regex filter
    await client.send_message(bot_id, "/chat (")
    message = await helper.wait_for_message(in_chats(bot_id) & has_button)

    # Cancel the message (cancel button)
    await message.click(text="Cancel")
