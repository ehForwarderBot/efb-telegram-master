"""
Test message destinations
Only testing with text messages, as everything else shall follow suit.

- Singly linked chat is tested in test_master_messages.py
- Chat head is tested in test_chat_head.py
"""

import asyncio
import time
from contextlib import suppress
from typing import List
from unittest.mock import patch, MagicMock

from pytest import mark, raises
from telethon.tl.custom import Message, MessageButton

from .helper.filters import in_chats, has_button, edited, regex, text

pytestmark = mark.asyncio


async def test_master_master_quick_reply_no_cache(helper, client, bot_id, slave, channel):
    assert channel.chat_dest_cache.enabled
    channel.chat_dest_cache.weak.clear()
    channel.chat_dest_cache.strong.clear()
    slave.clear_messages()

    await client.send_message(bot_id,
                              "test_master_master_quick_reply_no_cache this shall not be sent due to empty cache")
    await helper.wait_for_message()
    assert slave.messages.empty()


async def test_master_master_quick_reply(helper, client, bot_id, slave, channel):
    """Tests if the quick reply cache exists, and changes afterwards by
    incoming message from slave channel.
    """
    assert channel.chat_dest_cache.enabled
    assert channel.flag("send_to_last_chat") == "warn"

    chat = slave.chat_with_alias
    content = "test_master_master_quick_reply set cache with chat head"
    # Send a message to ``chat`` via chat head
    await client.send_message(bot_id, f"/chat {chat.uid}")
    message = await helper.wait_for_message(in_chats(bot_id) & has_button)
    await message.click(0)
    message = await helper.wait_for_message(in_chats(bot_id) & edited(message.id) & ~has_button)
    await message.reply(content)
    message = slave.messages.get(timeout=5)
    slave.messages.task_done()
    assert message.text == content
    assert message.chat == chat

    content = "test_master_master_quick_reply send new message with quick reply"
    await client.send_message(bot_id, content)
    text = await helper.wait_for_message_text(in_chats(bot_id))
    assert chat.display_name in text, f"{text!r} is not a warning message for {chat}"
    message = slave.messages.get(timeout=5)
    slave.messages.task_done()

    assert message.text == content
    assert message.chat == chat

    content = "test_master_master_quick_reply send another new message " \
              "with quick reply, should give no warning"
    await client.send_message(bot_id, content)
    message = slave.messages.get(timeout=5)
    slave.messages.task_done()
    assert message.text == content
    assert message.chat == chat
    # Error message shall not appear again
    with raises(asyncio.TimeoutError):
        await helper.wait_for_message_text(in_chats(bot_id) & regex(chat.display_name), timeout=3)

    # Clear destination with new message from slave channel
    chat_alt = slave.chat_without_alias
    message = slave.send_text_message(chat_alt, author=chat_alt.other)
    text = await helper.wait_for_message_text(in_chats(bot_id))
    assert message.text in text  # there might be message header in ``text``

    content = "test_master_master_quick_reply this shall not be sent due to cleared cache"
    await client.send_message(bot_id, content)
    message = await helper.wait_for_message(in_chats(bot_id))  # Error message
    assert slave.messages.empty()
    await cancel_destination_suggestion(helper, message)


async def test_master_master_quick_reply_cache_expiry(helper, client, bot_id, slave, channel):
    assert channel.chat_dest_cache.enabled
    slave.clear_messages()

    chat = slave.chat_with_alias
    content = "test_master_master_quick_reply_cache_expiry set cache with chat head"
    # slave.send_text_message(chat, author=chat)
    # Send a message to ``chat`` via chat head
    await client.send_message(bot_id, f"/chat {chat.uid}")
    message = await helper.wait_for_message(in_chats(bot_id) & has_button)
    await message.click(0)
    message = await helper.wait_for_message(in_chats(bot_id) & edited(message.id) & ~has_button)
    await message.reply(content)
    slave.messages.get(timeout=5)
    slave.messages.task_done()

    time_now = time.time()
    with patch("time.time", MagicMock(return_value=time_now + 24 * 60 * 60)):  # one day later
        content = "test_master_master_quick_reply_cache_expiry this shall not be sent due to expired cache"
        await client.send_message(bot_id, content)
        message = await helper.wait_for_message(in_chats(bot_id) & text)  # Error message
        assert slave.messages.empty()
    await cancel_destination_suggestion(helper, message)


async def test_master_master_destination_suggestion(helper, client, bot_id, slave, channel):
    with patch.dict(channel.flag.config, send_to_last_chat="disabled"), \
         patch.multiple(channel.chat_dest_cache, enabled=False):
        assert not channel.chat_dest_cache.enabled
        slave.clear_messages()
        chat = slave.chat_with_alias
        slave.send_text_message(chat, author=chat.other)
        await helper.wait_for_message_text(in_chats(bot_id) & regex(chat.display_name))

        content = "test_master_master_destination_suggestion this shall be replied with a list of candidates"
        sent_message: Message = await client.send_message(bot_id, content)
        message: Message = await helper.wait_for_message(in_chats(bot_id) & has_button)
        buttons: List[List[MessageButton]] = message.buttons
        first_button: MessageButton = buttons[0][0]
        assert chat.display_name in first_button.text  # The message from previous chat should come first in the list
        # await buttons[-1][0].click()  # Cancel the error message.

        await first_button.click()  # deliver the message
        slave.clear_messages()

        content = "test_master_master_destination_suggestion edited message shall be delivered without a prompt"
        await sent_message.edit(text=content)
        slave_message = slave.messages.get(timeout=5)
        assert slave_message.text == content



async def cancel_destination_suggestion(helper, message: Message):
    """Cancel chat destination suggestions if available."""
    with suppress(asyncio.TimeoutError):
        while not message.button_count:
            message = await helper.wait_for_message(in_chats(message.chat_id))
    if message.button_count:
        await message.buttons[-1][-1].click()
