from pytest import mark
from telethon.events import UserUpdate
from telethon.tl.types import SendMessageTypingAction, SendMessageRecordAudioAction, SendMessageUploadPhotoAction, \
    SendMessageUploadVideoAction, SendMessageUploadDocumentAction

from ehforwarderbot.message import StatusAttribute
from tests.integration.helper.filters import in_chats, typing

pytestmark = mark.asyncio


@mark.parametrize("efb_status,tg_status", [
    (StatusAttribute.Types.TYPING, SendMessageTypingAction),
    (StatusAttribute.Types.UPLOADING_VOICE, SendMessageRecordAudioAction),
    (StatusAttribute.Types.UPLOADING_IMAGE, SendMessageUploadPhotoAction),
    (StatusAttribute.Types.UPLOADING_VIDEO, SendMessageUploadVideoAction),
    (StatusAttribute.Types.UPLOADING_FILE, SendMessageUploadDocumentAction),
])
async def test_slave_message_statuses(helper, client, bot_id, slave, channel, efb_status, tg_status):
    chat = slave.chat_with_alias
    slave.send_status_message(StatusAttribute(efb_status), chat)
    event = await helper.wait_for_event(in_chats(bot_id) & typing)
    assert isinstance(event, UserUpdate.Event)
    assert isinstance(event.action, tg_status)
