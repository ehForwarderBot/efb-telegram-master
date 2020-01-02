import platform
import time

from pytest import fixture, mark

from efb_telegram_master import chat_destination_cache
from efb_telegram_master.utils import EFBChannelChatIDStr


@fixture(scope="function")
def destination_cache():
    return chat_destination_cache.ChatDestinationCache("enabled", 2)


@mark.xfail(platform.python_implementation() == "PyPy", reason="GC behaves differently in PyPy.")
def test_destination_pop_out(destination_cache):
    destination_cache.set("key_1", EFBChannelChatIDStr("Value 1"))
    destination_cache.set("key_2", EFBChannelChatIDStr("Value 2"))
    destination_cache.set("key_3", EFBChannelChatIDStr("Value 3"))
    assert destination_cache.get("key_3") is not None
    assert destination_cache.get("key_2") is not None
    assert destination_cache.get("key_1") is None


def test_destination_expired(destination_cache):
    destination_cache.set("key_1", EFBChannelChatIDStr("Value 1"), timeout=1)
    assert destination_cache.get("key_1") is not None
    time.sleep(1.5)
    assert destination_cache.get("key_1") is None


def test_destination_is_warned(destination_cache):
    destination_cache.set("key_1", EFBChannelChatIDStr("Value 1"))
    assert not destination_cache.is_warned("key_1")
    destination_cache.set_warned("key_1")
    assert destination_cache.is_warned("key_1")


def test_destination_is_removed(destination_cache):
    destination_cache.set("key_1", EFBChannelChatIDStr("Value 1"))
    assert destination_cache.get("key_1") is not None
    destination_cache.remove("key_1")
    assert destination_cache.get("key_1") is None
