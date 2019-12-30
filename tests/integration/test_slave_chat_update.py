from pytest import mark

from ehforwarderbot import EFBChat


def compare_chats(self: EFBChat, other: EFBChat):
    assert self.module_id == other.module_id
    assert self.module_name == other.module_name
    assert self.channel_emoji == other.channel_emoji
    assert self.chat_uid == other.chat_uid
    assert self.chat_type == other.chat_type
    assert self.chat_name == other.chat_name
    assert self.chat_alias == other.chat_alias
    assert self.notification == other.notification
    assert self.is_chat == other.is_chat
    if self.group:
        assert self.group.chat_uid == other.group.chat_uid


@mark.parametrize("method", ["send_chat_update_status", "send_member_update_status"])
def test_slave_chat_update(bot_group, slave, channel, method):
    added, edited, removed = getattr(slave, method)()
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
