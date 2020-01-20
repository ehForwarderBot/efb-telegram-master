import re
from pytest import fixture
from efb_telegram_master.chat import convert_chat, ETMPrivateChat, ETMChatMember, ETMSelfChatMember, ETMSystemChat, \
    ETMSystemChatMember, ETMGroupChat, unpickle
from ehforwarderbot.chat import PrivateChat, SystemChat, GroupChat


@fixture(scope="module")
def db(channel):
    return channel.db


def test_etm_chat_name(db, slave):
    with_alias = convert_chat(db, slave.chat_with_alias)
    with_alias_full_name = with_alias.full_name
    assert with_alias.name in with_alias_full_name
    assert with_alias.alias in with_alias_full_name
    assert slave.channel_emoji in with_alias_full_name
    assert slave.channel_name in with_alias_full_name

    without_alias = convert_chat(db, slave.chat_without_alias)
    without_alias_full_name = without_alias.full_name
    assert without_alias.name in without_alias_full_name
    assert str(without_alias.alias) not in without_alias_full_name
    assert slave.channel_emoji in without_alias_full_name
    assert slave.channel_name in without_alias_full_name


def test_etm_chat_conversion_private(db, slave):
    private_chat = slave.get_chat_by_criteria(chat_type='PrivateChat')
    assert isinstance(private_chat, PrivateChat)
    etm_private_chat = convert_chat(db, private_chat)
    assert isinstance(etm_private_chat, ETMPrivateChat)
    assert isinstance(etm_private_chat.other, ETMChatMember)
    assert not isinstance(etm_private_chat.other, ETMSelfChatMember)
    assert isinstance(etm_private_chat.self, ETMSelfChatMember)
    assert etm_private_chat.other in etm_private_chat.members
    assert etm_private_chat.self in etm_private_chat.members
    assert all(isinstance(i, ETMChatMember) for i in etm_private_chat.members)
    assert len(etm_private_chat.members) == len(private_chat.members)


def test_etm_chat_conversion_system(db, slave):
    system_chat = slave.get_chat_by_criteria(chat_type='SystemChat')
    assert isinstance(system_chat, SystemChat)
    etm_system_chat = convert_chat(db, system_chat)
    assert isinstance(etm_system_chat, ETMSystemChat)
    assert isinstance(etm_system_chat.other, ETMSystemChatMember)
    assert isinstance(etm_system_chat.self, ETMSelfChatMember)
    assert etm_system_chat.other in etm_system_chat.members
    assert etm_system_chat.self in etm_system_chat.members
    assert all(isinstance(i, ETMChatMember) for i in etm_system_chat.members)
    assert len(etm_system_chat.members) == len(system_chat.members)


def test_etm_chat_conversion_group(db, slave):
    group_chat = slave.get_chat_by_criteria(chat_type='GroupChat')
    assert isinstance(group_chat, GroupChat)
    etm_group_chat = convert_chat(db, group_chat)
    assert isinstance(etm_group_chat, ETMGroupChat)
    assert isinstance(etm_group_chat.self, ETMSelfChatMember)
    assert etm_group_chat.self in etm_group_chat.members
    assert all(isinstance(i, ETMChatMember) for i in etm_group_chat.members)
    assert len(etm_group_chat.members) == len(group_chat.members)


def test_etm_chat_type_title_differ(db, slave):
    chat_name = "Chat Name"

    user = ETMPrivateChat(db, channel=slave, uid="__id__", name=chat_name)
    user_title = user.chat_title

    group = ETMGroupChat(db, channel=slave, uid="__id__", name=chat_name)
    group_title = group.chat_title

    sys = ETMSystemChat(db, channel=slave, uid="__id__", name=chat_name)
    sys_title = sys.chat_title

    assert len({user_title, group_title, sys_title}) == 3


def test_etm_chat_instance_title_differ(db, slave):
    chat_name = "Chat Name"

    default_instance = ETMSystemChat(db, channel=slave, uid="__id__", name=chat_name)
    default_title = default_instance.chat_title

    custom_instance = default_instance.copy()
    custom_instance.module_id += "#custom"
    custom_title = custom_instance.chat_title

    assert default_title != custom_title


def test_etm_chat_match(db, slave):
    chat = convert_chat(db, slave.chat_with_alias)
    assert chat.match(chat.name)
    assert chat.match(chat.alias)
    assert chat.match(chat.module_name)
    assert chat.match(chat.uid)
    assert chat.match("type: private"), "case insensitive search"
    assert chat.match(re.compile("Channel ID: .+mock")), "re compile object search"
    assert chat.match("Mode: \n")

    assert chat.match(re.compile(f"Channel: {slave.channel_name}.*Type: Private",
                                 re.DOTALL | re.IGNORECASE)), "docs example #0"
    assert not chat.match("Alias: None"), "docs example #1"
    assert chat.match(re.compile(r"(?=.*Chat)(?=.*Channel)",
                                 re.DOTALL | re.IGNORECASE)), "docs example #2"

    no_alias = convert_chat(db, slave.chat_without_alias)
    assert no_alias.match("Alias: None")


def test_etm_chat_pickle(db, slave):
    chat = convert_chat(db, chat=slave.chat_with_alias)
    recovered = unpickle(chat.pickle, db)
    attributes = ('module_id', 'module_name', 'channel_emoji', 'uid', 'name', 'alias', 'notification',
                  'vendor_specific', 'full_name', 'long_name', 'chat_title')
    for i in attributes:
        assert getattr(chat, i) == getattr(recovered, i)
    assert chat.db is recovered.db


def test_etm_chat_copy(db, slave):
    chat = convert_chat(db, chat=slave.chat_with_alias)
    copied = chat.copy()
    attributes = ('module_id', 'module_name', 'channel_emoji', 'uid', 'name', 'alias', 'notification',
                  'vendor_specific', 'full_name', 'long_name', 'chat_title')
    for i in attributes:
        assert getattr(chat, i) == getattr(copied, i)
    assert chat.db is copied.db
