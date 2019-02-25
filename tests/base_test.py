import tempfile
import unittest
import os
from pathlib import PurePath
from unittest.mock import patch

import yaml
from typing import Union

import ehforwarderbot
import ehforwarderbot.utils
import ehforwarderbot.__main__
from ehforwarderbot import coordinator

from .mocks.slave import MockSlaveChannel
from efb_telegram_master import TelegramChannel


class StandardChannelTest(unittest.TestCase):
    temp_dir = None

    @classmethod
    def setUpClass(cls):
        # Set up environment
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ['EFB_DATA_PATH'] = cls.temp_dir.name

        # Config the framework
        config_path = ehforwarderbot.utils.get_config_path()
        config = yaml.dump({
            "master_channel": "blueset.telegram",
            "slave_channels": ["tests.mocks.slave"],
            "middlewares": []
        })
        if not os.path.exists(os.path.dirname(config_path)):
            os.makedirs(os.path.dirname(config_path))
        with open(config_path, 'w') as conf_file:
            conf_file.write(config)

        # Include the slave channel
        cls.slave = MockSlaveChannel()
        coordinator.add_channel(cls.slave)

        # Config the master channel
        channel_config = yaml.dump({
            'token': '100:test',
            'admins': [1]
        })

        channel_config_path = ehforwarderbot.utils.get_config_path('blueset.telegram')
        with open(channel_config_path, 'w') as f:
            f.write(channel_config)

        # Monkey patch python-telegram-bot
        patch('telegram.Bot.get_updates', return_value=True).start()
        patch('telegram.Bot.set_webhook', return_value=True).start()
        patch('telegram.Bot.delete_webhook', return_value=True).start()
        patch('telegram.Bot.get_me', return_value=True).start()
        patch('telegram.ext.Dispatcher.process_update').start()

        # Include the master channel
        coordinator.add_channel(TelegramChannel())

        cls.master: TelegramChannel = coordinator.master

    @classmethod
    def tearDownClass(cls):
        del os.environ['EFB_DATA_PATH']
        cls.temp_dir.cleanup()
        patch.stopall()
