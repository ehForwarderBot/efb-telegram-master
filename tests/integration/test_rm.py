from pytest import mark
from unittest.mock import patch

from ehforwarderbot.status import MessageRemoval
from tests.integration.helper.filters import in_chats, regex, deleted, has_button
from tests.integration.utils import link_chats

pytestmark = mark.asyncio


async def test_rm_command_help(helper, client, bot_id):
    await client.send_message(bot_id, "/rm")
    content = await helper.wait_for_message_text(in_chats(bot_id))
    assert "/rm" in content, f"{content!r} is not an error message for /rm."


async def test_rm_command_removal(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_group):
        message = slave.send_text_message(chat, chat.other)
        with slave.set_message_removal(False):
            tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(message.text))
            await tg_msg.reply("/rm")
            # wait for error message
            await helper.wait_for_message(in_chats(bot_group))
            assert slave.statuses.empty(), "Message removal should be failed."

        await tg_msg.reply("/rm")
        # wait for message removal prompt
        await helper.wait_for_message(in_chats(bot_group))
        removal_status = slave.statuses.get(timeout=5)
        assert isinstance(removal_status, MessageRemoval)
        assert removal_status.message.chat == message.chat
        assert removal_status.message.uid == message.uid


async def test_rm_edit(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_group):
        content = "test_rm_edit message to be removed"
        tg_msg = await client.send_message(bot_group, content)
        message = slave.messages.get(timeout=5)
        await tg_msg.edit(text=f"rm`{tg_msg.text}")

        # wait for message removal prompt
        await helper.wait_for_message(in_chats(bot_group))
        removal_status = slave.statuses.get(timeout=5)
        assert isinstance(removal_status, MessageRemoval)
        assert removal_status.message.chat == message.chat
        assert removal_status.message.uid == message.uid


async def test_rm_command_delete(helper, client, bot_id, bot_group, slave, channel):
    chat = slave.chat_with_alias
    with patch.dict(channel.flag.config, prevent_message_removal=False):
        # successful case: send to private chat

        # get chat head
        await client.send_message(bot_id, f"/chat {chat.uid}")
        tg_msg = await helper.wait_for_message(in_chats(bot_id) & has_button)
        await tg_msg.click(0)
        tg_msg = await helper.wait_for_message(in_chats(bot_id) & ~has_button)
        content = "test_rm_command_delete message to be removed from Telegram in private chat"
        tg_msg = await tg_msg.reply(content)
        assert slave.messages.get(timeout=5)
        await tg_msg.edit(text=f"rm`{tg_msg.text}")
        await helper.wait_for_event(deleted(tg_msg))

        # Failure case: send prompt
        with link_chats(channel, (chat,), bot_group):
            content = "test_rm_command_delete message to be removed from Telegram but failed"
            tg_msg = await client.send_message(bot_group, content)
            assert slave.messages.get(timeout=5)
            await tg_msg.edit(text=f"rm`{tg_msg.text}")
            await helper.wait_for_message(in_chats(bot_group))
