from unittest.mock import patch, Mock

from telegram import Message, Chat, User, Bot, Update, CallbackQuery

from efb_telegram_master.constants import Flags
from efb_telegram_master import utils
from efb_telegram_master.utils import TelegramChatID, TelegramMessageID


class ChatBindingTest:
    def setUpClass(cls):
        # Monkey patch message senders
        patch('efb_telegram_master.TelegramBotManager').start()

        cls.private = Chat(1, 'private')
        cls.group = Chat(2, 'group')
        cls.user = User(1, '', False)
        cls.message = Message(1, cls.user, None, cls.private, text='test')

        cls.bot = Mock(spec=Bot)


def test_full_chat_pagination(channel, slave):
    storage_id = (TelegramChatID(0), TelegramMessageID(1))
    legends, buttons = channel.chat_binding.slave_chats_pagination(storage_id)
    legend = "\n".join(legends)
    assert slave.channel_emoji in legend
    assert slave.channel_name in legend
    assert min(channel.flag("chats_per_page"), len(slave.get_chats())) == len(buttons) - 1


def test_filtered_chat_pagination(channel, slave):
    storage_id = (TelegramChatID(0), TelegramMessageID(2))
    legends, buttons = channel.chat_binding.slave_chats_pagination(storage_id, pattern="wonderland")
    legend = "\n".join(legends)
    assert slave.channel_emoji in legend
    assert slave.channel_name in legend
    assert len(buttons) == 2


def test_source_chat_pagination(channel, slave):
    storage_id = (TelegramChatID(0), TelegramMessageID(3))
    source_chats = [utils.chat_id_to_str(chat=slave.get_chat('wonderland001'))]
    legends, buttons = channel.chat_binding.slave_chats_pagination(storage_id, source_chats=source_chats)
    legend = "\n".join(legends)
    assert slave.channel_emoji in legend
    assert slave.channel_name in legend
    assert len(buttons) == 2

# TODO: write test for the rest of the class
