import pytest
from pathlib import Path

from ruamel.yaml import YAML
from typing import List

from telegram.error import TimedOut, NetworkError

import ehforwarderbot.utils
import ehforwarderbot.coordinator

from .mocks.slave import MockSlaveChannel
from .bot import get_bot
from efb_telegram_master import TelegramChannel

pytestmark = [pytest.mark.xfail(raises=TimedOut), pytest.mark.xfail(raises=NetworkError)]


@pytest.fixture('session')
def bot_info():
    return get_bot()


@pytest.fixture('session')
def bot_token(bot_info) -> str:
    return bot_info['token']


@pytest.fixture('session')
def bot_id(bot_token) -> int:
    return int(bot_token.split(":")[0])


@pytest.fixture('session')
def bot_admins(bot_info) -> List[int]:
    return bot_info['admins']


@pytest.fixture('session')
def bot_admin(bot_admins) -> int:
    return bot_admins[0]


@pytest.fixture('session')
def bot_groups(bot_info) -> List[int]:
    return bot_info['groups']


@pytest.fixture('session')
def bot_group(bot_groups) -> int:
    return bot_groups[0]


@pytest.fixture('session')
def bot_channels(bot_info) -> List[int]:
    return bot_info['channels']


@pytest.fixture('session')
def bot_channel(bot_channels) -> int:
    return bot_channels[0]


def dump_config(file_path: Path, data):
    """Dump YAML config to a file."""
    yaml = YAML()
    if not file_path.parent.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open('w') as file:
        yaml.dump(data, file)


@pytest.fixture(scope="module")
def monkey_class():
    from _pytest.monkeypatch import MonkeyPatch
    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
def channel(coordinator) -> TelegramChannel:
    return coordinator.master


@pytest.fixture(scope="module")
def slave(coordinator) -> MockSlaveChannel:
    return coordinator.slaves[MockSlaveChannel.channel_id]


# Isolation of unit tests and integration tests

def pytest_addoption(parser):
    parser.addoption(
        "--mode",
        action="store",
        metavar="MODE",
        default='unit',
        choices=['unit', 'integration', 'both'],
        help="run test of mode 'unit', 'integration', or 'both' (default: 'unit').",
    )


def pytest_configure(config):
    # register an additional marker
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")


def pytest_runtest_setup(item):
    is_unit = item.module.__name__.startswith('tests.unit')
    is_integration = item.module.__name__.startswith('tests.integration')
    mode = item.config.getoption("--mode")
    if mode == 'unit' and not is_unit:
        pytest.skip("test is a unit test", allow_module_level=True)
    elif mode == 'integration' and not is_integration:
        pytest.skip("test is an integration test", allow_module_level=True)

    if is_integration:
        item.fixturenames.append('poll_bot')
