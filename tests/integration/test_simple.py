from typing import cast

from pytest import mark
from telethon.events import NewMessage
from telethon.tl.custom import Message

from .helper.filters import text, in_chats


@mark.asyncio
async def test_start(helper, client, bot_id):
    await client.send_message(bot_id, "/start")
    event = await helper.wait_for_event(text & in_chats(bot_id))
    message: Message = cast(NewMessage.Event, event).message
    assert "EFB" in message.text
