# coding=utf-8

import telegram


class TGMsgType:
    Text = "Text"
    Audio = "Audio"
    Document = "Document"
    Photo = "Photo"
    Sticker = "Sticker"
    Video = "Video"
    Voice = "Voice"
    Contact = "Contact"
    Location = "Location"
    Venue = "Venue"
    System = "System"
    Game = "Game"
    VideoNote = "Video_note"
    Animation = "Animation"


def get_msg_type(msg: telegram.Message):
    sys = ['new_chat_members',
           'left_chat_member',
           'new_chat_title',
           'new_chat_photo',
           'delete_chat_photo',
           'group_chat_created',
           'supergroup_chat_created',
           'migrate_to_chat_id',
           'migrate_from_chat_id',
           'channel_chat_created',
           'pinned_message']
    for i in sys:
        if getattr(msg, i, False):
            return TGMsgType.System
    types = ['animation',
             'audio',
             'document',
             'photo',
             'sticker',
             'video',
             'voice',
             'contact',
             'location',
             'venue',
             'game',
             'video_note']
    for i in types:
        if getattr(msg, i, False):
            return getattr(TGMsgType, i.capitalize())
    return TGMsgType.Text
