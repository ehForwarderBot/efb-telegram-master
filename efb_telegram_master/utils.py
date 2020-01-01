# coding=utf-8

import base64
import logging
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING, IO

from telegram.ext import BaseFilter
from typing_extensions import NewType

import telegram

from ehforwarderbot import EFBChat, EFBChannel
from ehforwarderbot.types import ChatID, ModuleID
from .locale_mixin import LocaleMixin

if TYPE_CHECKING:
    from . import TelegramChannel


TelegramChatID = NewType('TelegramChatID', str)
TelegramMessageID = NewType('TelegramMessageID', str)
TgChatMsgIDStr = NewType('TgChatMsgIDStr', str)
EFBChannelChatIDStr = NewType('EFBChannelChatIDStr', str)
OldMsgID = Tuple[TelegramChatID, TelegramMessageID]
# TelegramChatID = Union[str, int]
# TelegramMessageID = Union[str, int]
# TgChatMsgIDStr = str
# EFBChannelChatIDStr = str


class ExperimentalFlagsManager(LocaleMixin):

    DEFAULT_VALUES = {
        "chats_per_page": 10,
        "multiple_slave_chats": True,
        "network_error_prompt_interval": 100,
        "prevent_message_removal": True,
        "auto_locale": True,
        "retry_on_error": False,
        "send_image_as_file": False,
        "message_muted_on_slave": "normal",
        "your_message_on_slave": "silent",
        "animated_stickers": False,
        "send_to_last_chat": "warn",
    }

    def __init__(self, channel: 'TelegramChannel'):
        self.channel = channel
        self.config: Dict[str, Any] = ExperimentalFlagsManager.DEFAULT_VALUES.copy()
        self.config.update(channel.config.get('flags', dict()))

    def __call__(self, flag_key: str) -> Any:
        if flag_key not in self.config:
            raise ValueError(self._("{0} is not a valid experimental flag").format(flag_key))
        return self.config[flag_key]


def b64en(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().replace("=", "~")


def b64de(s: str) -> str:
    return base64.urlsafe_b64decode(s.replace("~", "=").encode()).decode()


def message_id_to_str(chat_id: Optional[TelegramChatID] = None,
                      message_id: Optional[TelegramMessageID] = None,
                      update: Optional[telegram.Update] = None) -> TgChatMsgIDStr:
    """
    Convert an unique identifier of Telegram message to a string.

    Args:
        update: PTB update object, provide either this or the other 2 below
        chat_id: Chat ID
        message_id: Message ID

    Returns:
        String representation of the message ID
    """
    if update and (chat_id or message_id):
        raise ValueError("update and (chat_id, message_id) is mutual exclusive.")
    if not update and not (chat_id and message_id):
        raise ValueError("Either update or (chat_id, message_id) is to be provided.")
    if update:
        chat_id = update.effective_chat.id
        message_id = update.effective_message.message_id
    return TgChatMsgIDStr(f"{chat_id}.{message_id}")


def message_id_str_to_id(s: TgChatMsgIDStr) -> Tuple[TelegramChatID, TelegramMessageID]:
    """
    Reverse of message_id_to_str.
    Returns:
        chat_id, message_id
    """
    msg_ids = s.split(".", 1)
    return TelegramChatID(msg_ids[0]), TelegramMessageID(msg_ids[1])


def chat_id_to_str(channel_id: Optional[ModuleID] = None, chat_uid: Optional[ChatID] = None,
                   group_id: Optional[ChatID] = None,
                   chat: Optional[EFBChat] = None, channel: Optional[EFBChannel] = None) -> EFBChannelChatIDStr:
    """
    Convert an unique identifier to EFB chat to a string.

    (chat|((channel|channel_id), chat_uid)) must be provided.

    Returns:
        String representation of the chat
    """

    if not chat and not chat_uid:
        raise ValueError("Either chat or the other set must be provided.")
    if chat and chat_uid:
        raise ValueError("Either chat or the other set must be provided, but not both.")
    if chat_uid and channel_id and channel:
        raise ValueError("channel_id and channel is mutual exclusive.")

    if chat:
        channel_id = chat.module_id
        chat_uid = chat.chat_uid
        if chat.group:
            group_id = chat.group.chat_uid or group_id
    if channel:
        channel_id = channel.channel_id
    if group_id is None:
        return EFBChannelChatIDStr(f"{channel_id} {chat_uid}")

    return EFBChannelChatIDStr(f"{channel_id} {chat_uid} {group_id}")


def chat_id_str_to_id(s: EFBChannelChatIDStr) -> Tuple[ModuleID, ChatID, Optional[ChatID]]:
    """
    Reverse of chat_id_to_str.
    Returns:
        channel_id, chat_uid, group_id
    """
    ids = s.split(" ", 2)
    channel_id = ModuleID(ids[0])
    chat_uid = ChatID(ids[1])
    if len(ids) < 3:
        group_id = None
    else:
        group_id = ChatID(ids[2])
    return channel_id, chat_uid, group_id


def convert_tgs_to_gif(tgs_file: IO[bytes], gif_file: IO[bytes]) -> bool:
    # Import only upon calling the method due to added binary dependencies
    # (libcairo)
    from tgs.parsers.tgs import parse_tgs
    from tgs.exporters.gif import export_gif

    # noinspection PyBroadException
    try:
        animation = parse_tgs(tgs_file)
        # heavy_strip(animation)
        # heavy_strip(animation)
        # animation.tgs_sanitize()
        export_gif(animation, gif_file, skip_frames=1)
        return True
    except Exception:
        logging.exception("Error occurred while converting TGS to GIF.")
        return False


class PollFilter(BaseFilter):
    """python-telegram-bot filter for poll messages.
    TODO: remove this when PTB#1673 is merged and uploaded to PyPI

    https://github.com/python-telegram-bot/python-telegram-bot/pull/1673
    """
    name = 'Filters.poll'

    def filter(self, message):
        return bool(message.poll)
