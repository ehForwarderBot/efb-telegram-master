from pytest import raises

from ehforwarderbot import Chat
from ehforwarderbot.chat import BaseChat, ChatMember


def compare_base_chat(self: BaseChat, other: BaseChat):
    assert self.module_id == other.module_id
    assert self.module_name == other.module_name
    assert self.channel_emoji == other.channel_emoji
    assert self.uid == other.uid
    assert self.name == other.name
    assert self.alias == other.alias
    assert self.vendor_specific == other.vendor_specific
    assert self.description == other.description


def compare_chats(self: Chat, other: Chat):
    compare_base_chat(self, other)
    assert self.notification == other.notification
    assert self.has_self == other.has_self
    assert len(self.members) == len(other.members)


def compare_members(self: ChatMember, other: ChatMember):
    compare_base_chat(self, other)
    assert self.chat == other.chat


def test_slave_chat_update_chat(bot_group, slave, channel):
    added, edited, removed = slave.send_chat_update_status()
    chat_manager = channel.chat_manager

    added_key = chat_manager.get_cache_key(added)
    edited_key = chat_manager.get_cache_key(edited)
    removed_key = chat_manager.get_cache_key(removed)

    assert added_key in chat_manager.cache
    assert removed_key not in chat_manager.cache
    added_cache = chat_manager.cache[added_key]
    edited_cache = chat_manager.cache[edited_key]
    compare_chats(added, added_cache)
    compare_chats(edited, edited_cache)


def test_slave_chat_update_member(bot_group, slave, channel):
    added, edited, removed = slave.send_member_update_status()
    group = added.chat
    chat_manager = channel.chat_manager

    group_key = chat_manager.get_cache_key(group)

    assert group_key in chat_manager.cache
    group_cache = chat_manager.cache[group_key]
    added_cache = group_cache.get_member(added.uid)
    edited_cache = group_cache.get_member(edited.uid)
    with raises(KeyError):
        group_cache.get_member(removed.uid)
    compare_members(added, added_cache)
    compare_members(edited, edited_cache)
