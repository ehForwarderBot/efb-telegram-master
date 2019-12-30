from unittest.mock import patch

from pytest import mark
from telethon.tl.custom import Message

from tests.integration.helper.filters import in_chats, regex, reply_to, edited
from tests.integration.utils import link_chats

pytestmark = mark.asyncio


async def test_react_help(helper, client, bot_id):
    await client.send_message(bot_id, "/react")
    content = await helper.wait_for_message_text(in_chats(bot_id))
    assert "/react" in content, f"{content!r} is not a help message for /react."


async def test_react_send_and_retract_reaction(helper, client, bot_group, slave, channel):
    chat = slave.group
    reaction = "ETM"
    with link_chats(channel, (chat,), bot_group):
        tg_msg: Message = await client.send_message(bot_group, "test_react_send_and_retract_reaction outgoing message to react on.")
        slave.messages.get(timeout=5)

        # Send reaction
        await tg_msg.reply(f"/react {reaction}")
        edited_tg_msg = await helper.wait_for_message(in_chats(bot_group) & reply_to(tg_msg.id))
        assert reaction in edited_tg_msg.text

        # Retract reaction
        await tg_msg.reply(f"/react -")
        edited_tg_msg = await helper.wait_for_message(in_chats(bot_group) & edited(edited_tg_msg.id))
        assert reaction not in edited_tg_msg.text


async def test_react_get_reactors_list(helper, client, bot_group, slave, channel):
    chat = slave.group
    with link_chats(channel, (chat,), bot_group):
        efb_msg = slave.send_text_message(chat=chat, reactions=True)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        await tg_msg.reply("/react")
        tg_msg_listing = await helper.wait_for_message(in_chats(bot_group))
        for reaction, members in efb_msg.reactions.items():
            assert reaction in tg_msg.text
            assert reaction in tg_msg_listing.text
            for member in members:
                assert member.display_name in tg_msg_listing.text


async def test_react_errors(helper, client, bot_group, slave, channel):
    chat = slave.group
    with link_chats(channel, (chat,), bot_group):
        efb_msg = slave.send_text_message(chat=chat, reactions=True)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))

        # Entire slave channel doesn’t support reactions
        with patch.multiple(slave, suggested_reactions=None):
            await tg_msg.reply("/react FullChannelFail")
            await helper.wait_for_message_text(in_chats(bot_group))
            # Arbitrary error message

        # Reaction value is invalid
        with slave.set_react_to_message("reject_one"):
            await tg_msg.reply("/react ReactionValueFail")
            text = await helper.wait_for_message_text(in_chats(bot_group))
            # Error message with suggestions
            for i in slave.suggested_reactions:
                assert i in text

        # Reaction target (chat/message) is invalid
        with slave.set_react_to_message("reject_all"):
            await tg_msg.reply("/react ReactionTargetFail")
            await helper.wait_for_message_text(in_chats(bot_group))
            # Arbitrary error message
