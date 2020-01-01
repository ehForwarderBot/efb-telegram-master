from pytest import mark

from tests.integration.helper.filters import in_chats, regex, edited
from tests.integration.utils import link_chats

pytestmark = mark.asyncio


async def test_slave_message_reactions(helper, client, bot_group, slave, channel):
    chat = slave.group
    with link_chats(channel, (chat,), bot_group):
        efb_msg = slave.send_text_message(chat=chat, reactions=True)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        reactions_status = slave.send_reactions_update(efb_msg)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & edited(tg_msg.id))
        for reaction, members in reactions_status.reactions.items():
            assert reaction in tg_msg.text
