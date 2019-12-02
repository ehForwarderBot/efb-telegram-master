import pytest
from pathlib import Path

from ruamel.yaml import YAML

import ehforwarderbot.utils
import ehforwarderbot.coordinator

from .mocks.slave import MockSlaveChannel
from .bot import get_bot
from efb_telegram_master import TelegramChannel


@pytest.fixture('session')
def bot_info():
    return get_bot()


@pytest.fixture('session')
def bot_token(bot_info):
    return bot_info['token']


@pytest.fixture('session')
def bot_admins(bot_info):
    return bot_info['admins']


@pytest.fixture('session')
def bot_admin(bot_admins):
    return bot_admins[0]


@pytest.fixture('session')
def bot_groups(bot_info):
    return bot_info['groups']


@pytest.fixture('session')
def bot_group(bot_groups):
    return bot_groups[0]


@pytest.fixture('session')
def bot_channels(bot_info):
    return bot_info['channels']


def dump_config(file_path: Path, data):
    """Dump YAML config to a file."""
    yaml = YAML()
    if not file_path.parent.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open('w') as file:
        yaml.dump(data, file)


@pytest.fixture(scope='class')
def monkey_class():
    from _pytest.monkeypatch import MonkeyPatch
    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="class")
def coordinator(tmp_path_factory, monkey_class, bot_token, bot_admins) -> ehforwarderbot.coordinator:
    """Loaded coordinator with ETM and mock modules"""
    tmp_path = tmp_path_factory.mktemp("etm_test")
    monkey_class.setenv("EFB_DATA_PATH", str(tmp_path))

    # Framework configs
    config_path = ehforwarderbot.utils.get_config_path()
    dump_config(config_path, {
        "master_channel": TelegramChannel.channel_id,
        "slave_channels": ["tests.mocks.slave"],
        "middlewares": []
    })

    # Load mock slave channel
    ehforwarderbot.coordinator.add_channel(MockSlaveChannel())
    # TODO: load another slave channel

    channel_config_path = ehforwarderbot.utils.get_config_path(TelegramChannel.channel_id)
    dump_config(channel_config_path, {
        'token': bot_token,
        'admins': bot_admins
    })

    ehforwarderbot.coordinator.add_channel(TelegramChannel())

    yield ehforwarderbot.coordinator

    ehforwarderbot.coordinator.master.stop_polling()
    for i in ehforwarderbot.coordinator.slaves.values():
        i.stop_polling()


@pytest.fixture(scope="class")
def channel(coordinator) -> TelegramChannel:
    return coordinator.master


@pytest.fixture(scope="class")
def slave(coordinator) -> MockSlaveChannel:
    return coordinator.slaves[MockSlaveChannel.channel_id]
