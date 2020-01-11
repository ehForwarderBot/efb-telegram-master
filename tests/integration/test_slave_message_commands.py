from pytest import mark
from telethon.tl.types.messages import BotCallbackAnswer

from tests.integration.helper.filters import in_chats, regex
from tests.integration.utils import link_chats

pytestmark = mark.asyncio

# Only testing text messages here, assuming all other message types shall follow suit.


async def test_slave_message_command(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias
    with link_chats(channel, (chat,), bot_group):
        # Ping / Pong
        efb_msg = slave.send_text_message(chat=chat, author=chat.other, commands=True)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        assert tg_msg.button_count == len(efb_msg.commands)
        assert tg_msg.buttons[0][0].text == "Ping!"
        assert tg_msg.buttons[1][0].text == "Bam"
        response: BotCallbackAnswer = await tg_msg.click(0)
        assert slave.command_ping() in response.message

        # Bam (None return value)
        efb_msg = slave.send_text_message(chat=chat, commands=True)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        response = await tg_msg.click(1)
        assert response.message is None
