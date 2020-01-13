from pytest import mark

from tests.integration.helper.filters import in_chats, regex
from tests.integration.utils import link_chats

pytestmark = mark.asyncio

# Only testing text messages here, assuming all other message types shall follow suit.


async def test_slave_message_author_external(helper, client, bot_group, slave, channel):
    chat = slave.chat_with_alias
    author = chat.make_system_member(uid="member_from_middleware",
                                     name="Middleware Member")
    author.module_id = "unknown.middleware"
    author.module_name = "Unknown middleware"
    author.channel_emoji = ""
    with link_chats(channel, (chat,), bot_group):
        # Ping / Pong
        efb_msg = slave.send_text_message(chat=chat, author=author, commands=True)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        assert author.name in tg_msg.text
