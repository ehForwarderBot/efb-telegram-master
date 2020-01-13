from unittest.mock import patch

from pytest import fixture

from efb_telegram_master.chat_object_cache import ChatObjectCacheManager
from ehforwarderbot import Chat
from ehforwarderbot.chat import PrivateChat


@fixture(scope="function")
def chat_manager(channel):
    # Prevent the manager to get a list of available chats in the list
    with patch.dict('ehforwarderbot.coordinator.slaves', {}, clear=True):
        yield ChatObjectCacheManager(channel)


def test_chat_manager_enrol_single(chat_manager, slave):
    chat = slave.chat_with_alias
    assert chat_manager.get_chat(chat.module_id, chat.uid) is None
    chat_manager.compound_enrol(chat)
    cached = chat_manager.get_chat(chat.module_id, chat.uid)
    assert cached == chat  # checking module ID and chat ID


def test_chat_manager_enrol_group(chat_manager, slave):
    group = slave.group
    assert chat_manager.get_chat(group.module_id, group.uid) is None
    chat_manager.compound_enrol(group)
    assert chat_manager.get_chat(group.module_id, group.uid) is not None
    for i in group.members:
        assert chat_manager.get_chat_member(i.module_id, group.uid, i.uid) is not None


def test_chat_manager_build_dummy(chat_manager):
    module_id = "__module_id__"
    id = "__chat_id__"
    assert chat_manager.get_chat(module_id, id) is None
    generated = chat_manager.get_chat(module_id, id, build_dummy=True)
    assert generated is not None
    assert generated.module_id == module_id
    assert generated.uid == id


def test_chat_manager_update_chat_obj(chat_manager, slave):
    chat = PrivateChat(channel=slave, uid="unique_id", name="Chat name")
    chat_manager.compound_enrol(chat)
    chat.alias = "Alias"
    assert chat_manager.get_chat(chat.module_id, chat.uid).alias != chat.alias
    chat_manager.update_chat_obj(chat)
    assert chat_manager.get_chat(chat.module_id, chat.uid).alias == chat.alias


def test_chat_manager_delete_chat_object(chat_manager, slave):
    chat = slave.chat_with_alias
    assert chat_manager.get_chat(chat.module_id, chat.uid) is None
    chat_manager.compound_enrol(chat)
    assert chat_manager.get_chat(chat.module_id, chat.uid) is not None
    chat_manager.delete_chat_object(chat.module_id, chat.uid)
    assert chat_manager.get_chat(chat.module_id, chat.uid) is None


def test_chat_manager_all_chats(channel, slave):
    """The chat object cache manager in channel should be initialized with
    only the chats in the slave channel.
    """
    chat_manager = channel.chat_manager
    assert len(tuple(chat_manager.all_chats)) == len(slave.get_chats())
