import asyncio
from unittest.mock import patch

from pytest import mark, raises

from ehforwarderbot.chat import ChatNotificationState
from tests.integration.helper.filters import in_chats, regex
from tests.integration.utils import link_chats

pytestmark = mark.asyncio

# Only testing text messages here, assuming all other message types shall follow suit.


@mark.parametrize("notification_state",
                  [ChatNotificationState.NONE,
                   ChatNotificationState.MENTIONS,
                   ChatNotificationState.ALL],
                  ids=lambda x: x.name)
@mark.parametrize("mentioned", [True, False], ids=["mentioned", "not mentioned"])
async def test_slave_message_notification(helper, client, bot_group, slave, channel, notification_state, mentioned):
    chat = slave.get_chat_by_criteria(chat_type="PrivateChat", notification=notification_state)
    with link_chats(channel, (chat,), bot_group), \
            patch.dict(channel.flag.config, message_muted_on_slave="silent"):
        efb_msg = slave.send_text_message(chat=chat, author=chat.other, substitution=mentioned)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        if notification_state == ChatNotificationState.NONE:
            should_be_silent = True
        elif notification_state == ChatNotificationState.MENTIONS:
            should_be_silent = not mentioned
        else:  # ChatNotificationState.ALL
            should_be_silent = False
        assert tg_msg.silent == should_be_silent


@mark.parametrize("chat_caller,mention", [
    (lambda slave: slave.chat_with_alias, False),
    (lambda slave: slave.get_chat_by_criteria(chat_type="PrivateChat", notification=ChatNotificationState.NONE), True),
    (lambda slave: slave.get_chat_by_criteria(chat_type="PrivateChat", notification=ChatNotificationState.MENTIONS), False)
], ids=["normal chat", "NONE notification with mention", "MENTION notification without mention"])
async def test_slave_message_notification_your_normal(helper, client, bot_group, slave, channel, chat_caller, mention):
    chat = chat_caller(slave)
    with link_chats(channel, (chat,), bot_group), \
            patch.dict(channel.flag.config, your_message_on_slave="normal"):
        efb_msg = slave.send_text_message(chat=chat, substitution=mention)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        assert not tg_msg.silent


@mark.parametrize("chat_caller,mention", [
    (lambda slave: slave.chat_with_alias, False),
    (lambda slave: slave.get_chat_by_criteria(chat_type="PrivateChat", notification=ChatNotificationState.NONE), True),
    (lambda slave: slave.get_chat_by_criteria(chat_type="PrivateChat", notification=ChatNotificationState.MENTIONS), False)
], ids=["normal chat", "NONE notification with mention", "MENTION notification without mention"])
async def test_slave_message_notification_your_silent(helper, client, bot_group, slave, channel, chat_caller, mention):
    chat = chat_caller(slave)
    with link_chats(channel, (chat,), bot_group), \
            patch.dict(channel.flag.config, your_message_on_slave="silent"):
        efb_msg = slave.send_text_message(chat=chat, substitution=mention)
        tg_msg = await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text))
        assert tg_msg.silent


@mark.parametrize("chat_caller,mention", [
    (lambda slave: slave.chat_with_alias, False),
    (lambda slave: slave.get_chat_by_criteria(chat_type="PrivateChat", notification=ChatNotificationState.NONE), True),
    (lambda slave: slave.get_chat_by_criteria(chat_type="PrivateChat", notification=ChatNotificationState.MENTIONS), False)
], ids=["normal chat", "NONE notification with mention", "MENTION notification without mention"])
async def test_slave_message_notification_your_mute(helper, client, bot_group, slave, channel, chat_caller, mention):
    chat = chat_caller(slave)
    with link_chats(channel, (chat,), bot_group), \
            patch.dict(channel.flag.config, your_message_on_slave="mute"):
        efb_msg = slave.send_text_message(chat=chat, substitution=mention)
        with raises(asyncio.TimeoutError):
            await helper.wait_for_message(in_chats(bot_group) & regex(efb_msg.text), timeout=3)
