import re
from pytest import fixture
from efb_telegram_master.chat import ETMChat
from ehforwarderbot import ChatType


@fixture(scope="module")
def db(channel):
    return channel.db


def test_etm_chat_name(db, slave):
    with_alias = ETMChat(db, chat=slave.chat_with_alias)
    with_alias_full_name = with_alias.full_name
    assert with_alias.chat_name in with_alias_full_name
    assert with_alias.chat_alias in with_alias_full_name
    assert slave.channel_emoji in with_alias_full_name
    assert slave.channel_name in with_alias_full_name

    without_alias = ETMChat(db, chat=slave.chat_without_alias)
    without_alias_full_name = without_alias.full_name
    assert without_alias.chat_name in without_alias_full_name
    assert str(without_alias.chat_alias) not in without_alias_full_name
    assert slave.channel_emoji in without_alias_full_name
    assert slave.channel_name in without_alias_full_name


def test_etm_chat_type_title_differ(db, slave):
    chat_name = "Chat Name"

    user = ETMChat(db, channel=slave)
    user.chat_uid = "c_user"
    user.chat_name = chat_name
    user.chat_type = ChatType.User
    user_title = user.chat_title

    group = user.copy()
    group.chat_type = ChatType.Group
    group_title = group.chat_title

    sys = user.copy()
    sys.chat_type = ChatType.System
    sys_title = sys.chat_title

    unknown = user.copy()
    unknown.chat_type = ChatType.Unknown
    unknown_title = unknown.chat_title

    assert len({user_title, group_title, sys_title, unknown_title}) == 4


def test_etm_chat_instance_title_differ(db, slave):
    chat_name = "Chat Name"

    default_instance = ETMChat(db, channel=slave)
    default_instance.chat_uid = "c_user"
    default_instance.chat_name = chat_name
    default_instance.chat_type = ChatType.User
    default_title = default_instance.chat_title

    custom_instance = default_instance.copy()
    custom_instance.module_id += "#custom"
    custom_title = custom_instance.chat_title

    assert default_title != custom_title


def test_etm_chat_match(db, slave):
    chat = ETMChat(db, chat=slave.chat_with_alias)
    assert chat.match(chat.chat_name)
    assert chat.match(chat.chat_alias)
    assert chat.match(chat.module_name)
    assert chat.match(chat.chat_uid)
    assert chat.match(re.compile("Channel ID: .+mock"))
    assert chat.match("Mode: \n")

    no_alias = ETMChat(db, chat=slave.chat_without_alias)
    assert no_alias.match("Alias: None")


def test_etm_chat_group_id(db, slave):
    group_chat = ETMChat(db, chat=slave.group)
    member = slave.group.members[0]
    member_chat = group_chat.members[0]
    assert member_chat.group_id == slave.group.chat_uid

    assert group_chat.group_id is None


def test_etm_chat_pickle(db, slave):
    chat = ETMChat(db, chat=slave.chat_with_alias)
    recovered = ETMChat.unpickle(chat.pickle, db)
    attributes = ('module_id', 'module_name', 'channel_emoji', 'chat_uid', 'chat_name', 'chat_alias', 'notification',
                  'vendor_specific', 'chat_type', 'full_name', 'long_name', 'chat_title', 'group_id')
    for i in attributes:
        assert getattr(chat, i) == getattr(recovered, i)
