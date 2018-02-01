import string
import random
from unittest.mock import patch, Mock

import telegram

from .base_test import StandardChannelTest


class BotManagerTest(StandardChannelTest):
    @classmethod
    def setUpClass(cls):
        # Monkey patch message senders
        super().setUpClass()

    @patch('telegram.Bot.send_message')
    @patch('telegram.Bot.send_document')
    def test_prefix_suffix(self, mock_send_document: Mock,  mock_send_message: Mock):
        self.master.bot_manager.send_message('0', 'Message', prefix='Prefix', suffix='Suffix')
        mock_send_message.assert_called_with('0', text='Prefix\nMessage\nSuffix')
        mock_send_message.reset_mock()

        msg_body = ''.join(random.choice(string.printable) for _ in range(100000))
        self.master.bot_manager.send_message('0', msg_body, prefix='Prefix')
        mock_send_message.assert_called()
        self.assertEqual(mock_send_message.call_args[0][0], '0')
        self.assertTrue(mock_send_message.call_args[1]['text'].startswith('Prefix\n' + msg_body[:50]))
        self.assertTrue(len(mock_send_message.call_args[1]['text']) <=
                        telegram.constants.MAX_MESSAGE_LENGTH)
        mock_send_document.assert_called()
