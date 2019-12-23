from typing import Iterable
from contextlib import contextmanager

from telethon import TelegramClient
from telethon.tl.types import ChatParticipantAdmin, ChannelParticipantsAdmins
from telethon.tl.types.messages import ChatFull

from efb_telegram_master import TelegramChannel
from efb_telegram_master.utils import chat_id_to_str
from ehforwarderbot import EFBChat


@contextmanager
def link_chats(channel: TelegramChannel,
               slave_chats: Iterable[EFBChat],
               telegram_chat_id: str):
    """Link a list of remote chats to a Telegram chat and revert the changes
    upon finishing.
    """
    # Link the chats
    db = channel.db
    slave_ids = [
        chat_id_to_str(chat=i) for i in slave_chats
    ]
    master_str = chat_id_to_str(channel.channel_id, telegram_chat_id)
    backup = db.get_chat_assoc(master_uid=master_str)

    db.remove_chat_assoc(master_uid=master_str)
    for i in slave_ids:
        db.add_chat_assoc(master_str, i, multiple_slave=True)
    yield
    # Unlink the chats and revert back
    db.remove_chat_assoc(master_uid=master_str)
    for i in backup:
        db.add_chat_assoc(master_str, i, multiple_slave=True)


async def is_bot_admin(client: TelegramClient, bot_id: int, group):

    async for admin in client.iter_participants(group, filter=ChannelParticipantsAdmins()):
        if admin.id == bot_id:
            return True

    return False
