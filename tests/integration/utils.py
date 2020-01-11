from contextlib import contextmanager
from typing import Iterable

from telethon import TelegramClient
from telethon.tl.types import ChannelParticipantsAdmins

from efb_telegram_master import TelegramChannel
from efb_telegram_master.utils import chat_id_to_str
from ehforwarderbot import Chat


@contextmanager
def link_chats(channel: TelegramChannel,
               slave_chats: Iterable[Chat],
               telegram_chat_id: int):
    """Link a list of remote chats to a Telegram chat and revert the changes
    upon finishing.
    """
    # Link the chats
    db = channel.db
    slave_ids = [
        chat_id_to_str(chat=i) for i in slave_chats
    ]
    master_str = chat_id_to_str(channel.channel_id, str(telegram_chat_id))
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


def assert_is_linked(channel: TelegramChannel,
                     slave_chats: Iterable[Chat],
                     telegram_chat_id: int):
    master_str = chat_id_to_str(channel.channel_id, str(telegram_chat_id))
    chats_str = set(channel.db.get_chat_assoc(master_uid=master_str))
    slave_ids = {
        chat_id_to_str(chat=i) for i in slave_chats
    }
    # print("ASSERT_IS_LINKED", chats_str, slave_ids)
    assert chats_str == slave_ids, f"expecting {slave_ids} linked, found {chats_str}"


def unlink_all_chats(channel: TelegramChannel, telegram_chat_id: int):
    master_str = chat_id_to_str(channel.channel_id, str(telegram_chat_id))
    channel.db.remove_chat_assoc(master_uid=master_str)
