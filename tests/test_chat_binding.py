import string
import random
from unittest.mock import patch, Mock

from telegram import Message, Chat, User, Bot, Update, CallbackQuery

from efb_telegram_master.constants import Flags
from .base_test import StandardChannelTest
from efb_telegram_master import utils


class ChatBindingTest(StandardChannelTest):
    @classmethod
    def setUpClass(cls):
        # Monkey patch message senders
        patch('efb_telegram_master.TelegramBotManager').start()

        super().setUpClass()

        cls.private = Chat(1, 'private')
        cls.group = Chat(2, 'group')
        cls.user = User(1, '', False)
        cls.message = Message(1, cls.user, None, cls.private, text='test')

        cls.bot = Mock(spec=Bot)

    @patch('efb_telegram_master.chat_binding.ChatBindingManager.link_chat_gen_list')
    def test_link_channel(self, mock_gen_list: Mock):
        self.message.text = "/link"
        with self.subTest('Private /link'):
            self.message.chat = self.private
            self.master.chat_binding.link_chat_show_list(self.bot, Update(0, self.message))
            mock_gen_list.assert_called_with(1, pattern='')

        with self.subTest('Private /link with pattern'):
            self.message.chat = self.private
            self.master.chat_binding.link_chat_show_list(self.bot, Update(1, self.message), ['test', 'pattern'])
            mock_gen_list.assert_called_with(1, pattern='test pattern')

        with self.subTest('Group /link'):
            self.message.chat = self.group
            update = Update(2, self.message)
            self.master.chat_binding.link_chat_show_list(self.bot, update)
            mock_gen_list.assert_called_with(1, pattern='')

        # TODO: Add test for linked group

    def test_chat_pagination(self):
        with self.subTest('Full channel pagination'):
            legend, buttons = self.master.chat_binding.slave_chats_pagination((0, 1))
            self.assertIn(self.slave.channel_emoji, "\n".join(legend))
            self.assertIn(self.slave.channel_name, "\n".join(legend))
            self.assertEqual(min(self.master.flag("chats_per_page"), len(self.slave.get_chats())), len(buttons) - 1)

        with self.subTest('Pagination with filter'):
            legend, buttons = self.master.chat_binding.slave_chats_pagination((0, 2), pattern="wonderland")
            self.assertIn(self.slave.channel_emoji, "\n".join(legend))
            self.assertIn(self.slave.channel_name, "\n".join(legend))
            self.assertEqual(2, len(buttons))

        with self.subTest('Pagination with list'):
            source_chats = [utils.chat_id_to_str(chat=self.slave.get_chat('wonderland001'))]
            legend, buttons = self.master.chat_binding.slave_chats_pagination((0, 3), source_chats=source_chats)
            self.assertIn(self.slave.channel_emoji, "\n".join(legend))
            self.assertIn(self.slave.channel_name, "\n".join(legend))
            self.assertEqual(2, len(buttons))

    @patch('efb_telegram_master.chat_binding.ChatBindingManager.slave_chats_pagination',
           return_value=([], []))
    def test_link_chat_gen_list(self, mock_pagination: Mock):
        with self.subTest('New message'):
            self.master.chat_binding.link_chat_gen_list(0)
            mock_pagination.assert_called()
            self.master.bot_manager.send_message.assert_called()
            self.master.bot_manager.edit_message_text.assert_called()
            self.master.bot_manager.reset_mock()

        with self.subTest('Edit message'):
            self.master.chat_binding.link_chat_gen_list(0, message_id=1)
            mock_pagination.assert_called()
            self.master.bot_manager.send_message.assert_not_called()
            self.master.bot_manager.edit_message_text.assert_called()

    def test_chat_confirm(self):
        with self.subTest("Cancel"):
            self.master.chat_binding.link_chat_gen_list(1, 1)
            c = CallbackQuery(1, self.user, None, message=self.message, data=Flags.CANCEL_PROCESS)
            self.master.chat_binding.link_chat_confirm(self.bot, Update(0, callback_query=c))
            self.master.bot_manager.edit_message_text.assert_called()
            self.assertNotIn("reply_markup", self.master.bot_manager.edit_message_text.call_args[1])
            self.master.bot_manager.reset_mock()

        with self.subTest("Unknown command"):
            self.master.chat_binding.link_chat_gen_list(1, 1)
            c = CallbackQuery(1, self.user, None, message=self.message, data="__unknown_command__")
            self.master.chat_binding.link_chat_confirm(self.bot, Update(0, callback_query=c))
            self.master.bot_manager.edit_message_text.assert_called()
            self.assertNotIn("reply_markup", self.master.bot_manager.edit_message_text.call_args[1])
            self.master.bot_manager.reset_mock()

        with self.subTest("Chat choice: non-linked"):
            self.master.chat_binding.link_chat_gen_list(1, 1)
            c = CallbackQuery(1, self.user, None, message=self.message, data="chat 0")
            self.master.chat_binding.link_chat_confirm(self.bot, Update(0, callback_query=c))
            self.master.bot_manager.edit_message_text.assert_called()
            state_buttons = self.master.bot_manager.edit_message_text.call_args[1]['reply_markup'].inline_keyboard[0]
            self.assertEqual(len(state_buttons), 2)
            self.master.bot_manager.reset_mock()

    # TODO: write test for the rest of the class
