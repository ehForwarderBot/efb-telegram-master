from efb_telegram_master.chat_binding import ChatListStorage


def test_chat_list_storage(slave):
    chats = slave.get_chats()
    c = ChatListStorage(chats, 0)
    assert c.length == len(chats)
    assert c.chats == chats
    assert slave.channel_id in c.channels
    assert c.channels[slave.channel_id] is slave
