# coding=utf-8

import base64
from typing import Any, Dict, Optional, Tuple, Union, TYPE_CHECKING

import telegram

from ehforwarderbot import EFBChat, EFBChannel
from .locale_mixin import LocaleMixin

if TYPE_CHECKING:
    from . import TelegramChannel


class ExperimentalFlagsManager(LocaleMixin):

    DEFAULT_VALUES = {
        "no_conversion": False,
        "chats_per_page": 10,
        "multiple_slave_chats": True,
        "network_error_prompt_interval": 100,
        "prevent_message_removal": True,
        "auto_locale": True,
        'retry_on_error': False,
    }

    def __init__(self, channel: 'TelegramChannel'):
        self.config: Dict[str, Any] = ExperimentalFlagsManager.DEFAULT_VALUES.copy()
        self.config.update(channel.config.get('flags', dict()))

    def __call__(self, flag_key: str) -> Any:
        if flag_key not in self.config:
            raise ValueError(self._("{0} is not a valid experimental flag").format(flag_key))
        return self.config[flag_key]


def b64en(s):
    return base64.b64encode(s.encode(), b"-_").decode().rstrip("=")


def b64de(s):
    return base64.b64decode((s + '=' * (- len(s) % 4)).encode(), b"-_").decode()


def message_id_to_str(chat_id: Optional[Union[int, str]] = None,
                      message_id: Optional[Union[int, str]] = None,
                      update: Optional[telegram.Update] = None) -> str:
    """
    Convert an unique identifier to telegram message to a string.

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
    return "%s.%s" % (chat_id, message_id)


def message_id_str_to_id(s: str) -> Tuple[str, str]:
    """
    Reverse of message_id_to_str.
    Returns:
        chat_id, message_id
    """
    return tuple(s.split(".", 1))[:2]


def chat_id_to_str(channel_id: Optional[str] = None, chat_uid: Optional[str] = None,
                   chat: Optional[EFBChat] = None, channel: Optional[EFBChannel] = None) -> str:
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
        channel_id = chat.channel_id
        chat_uid = chat.chat_uid
    if channel:
        channel_id = channel.channel_id

    return "%s %s" % (channel_id, chat_uid)


def chat_id_str_to_id(s: str) -> Tuple[str, str]:
    """
    Reverse of chat_id_to_str.
    Returns:
        channel_id, chat_uid
    """
    return tuple(s.split(" ", 1))[:2]
