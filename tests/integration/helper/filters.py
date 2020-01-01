"""
Useful filters to use with :meth:`TelegramIntegrationTestHelper.wait_for_update`.

Code structure inspired by Filters in python-telegram-bot_, which is licensed
under GPL v3.

.. _python-telegram-bot: https://github.com/python-telegram-bot/python-telegram-bot
"""
import re
from typing import Optional, cast, Set

from telethon.events import NewMessage, ChatAction, MessageEdited, MessageDeleted, UserUpdate
from telethon.events.common import EventCommon
from telethon.tl.custom import Message
from telethon.tl.types import MessageMediaWebPage

__all__ = ["BaseFilter", "MergedFilter", "InvertedFilter",
           "everything", "in_chats",
           "message", "text", "has_button", "edited", "regex",
           "chat_action", "new_photo", "new_title",
           "deleted", "reply_to", "typing"]


class BaseFilter:
    """
    Examples:

        And operation:

            >>> in_chats(1234) & text

        Or operation:

            >>> has_button | text

        Not operation:

            >>> ~ text
    """

    def __call__(self, event):
        return self.filter(event)

    def __and__(self, other):
        return MergedFilter(self, and_filter=other)

    def __or__(self, other):
        return MergedFilter(self, or_filter=other)

    def __invert__(self):
        return InvertedFilter(self)

    def filter(self, event) -> bool:
        raise NotImplementedError

    def __repr__(self):
        return f"{self.__class__.__name__}()"


class MergedFilter(BaseFilter):
    def __init__(self, base: BaseFilter,
                 and_filter: Optional[BaseFilter] = None,
                 or_filter: Optional[BaseFilter] = None):
        self.base = base
        self.and_filter = and_filter
        self.or_filter = or_filter

    def filter(self, event) -> bool:
        if self.and_filter is not None:
            return self.base(event) and self.and_filter(event)
        elif self.or_filter is not None:
            return self.base(event) or self.or_filter(event)
        else:
            raise ValueError("and_filter and or_filter is both None.")

    def __repr__(self):
        if self.and_filter:
            symbol = "&"
            other = self.and_filter
        else:
            symbol = "|"
            other = self.or_filter
        return f"<{self.base} {symbol} {other}>"


class InvertedFilter(BaseFilter):
    def __init__(self, base: BaseFilter):
        self.base = base

    def filter(self, event) -> bool:
        return not self.base(event)

    def __repr__(self):
        return f"<! {self.base}>"


class _Everything(BaseFilter):
    def filter(self, _):
        return True

    def __repr__(self):
        return "Everything"


everything = _Everything()
"""Filter that allow everything to pass through."""


class _InChats(BaseFilter):
    def __init__(self, *args: int):
        """
        Examples:

            >>> filter_a = in_chats(12345)
            >>> filter_b = in_chats(12345, 67890)

        Args:
            chats: chat ID or a set of chat IDs
        """
        self.chats: Set[int] = set(args)

    def filter(self, event: EventCommon) -> bool:
        return event.chat_id in self.chats

    def __repr__(self):
        return f"InChats({self.chats})"


in_chats = _InChats
"""Update in chat IDs."""


class _Typing(BaseFilter):
    def filter(self, event: EventCommon):
        return isinstance(event, UserUpdate.Event)

    def __repr__(self):
        return "Message"


typing = _Typing()
"""User typing."""


class _Message(BaseFilter):
    def filter(self, event: EventCommon):
        return isinstance(event, NewMessage.Event)
        # or isinstance(event, MessageEdited.Event)
        # Not needed for now as MessageEdited.Event is a subclass of
        # NewMessage.Event

    def __repr__(self):
        return "Message"


message = _Message()


class _EditedMessage(_Message):
    def __init__(self, message_id: Optional[int]):
        self.message_id = message_id

    def filter(self, event: EventCommon):
        if not super().filter(event):
            return False
        if not isinstance(event, MessageEdited.Event):
            return False
        if self.message_id is not None:
            message = cast(MessageEdited.Event, event).message
            return message.id == self.message_id
        return True

    def __repr__(self):
        return f"EditedMessage({self.message_id})"


edited = _EditedMessage
"""Edited message"""


class _ReplyToMessage(_Message):
    def __init__(self, *message_ids: Optional[int]):
        self.message_ids = message_ids

    def filter(self, event: EventCommon):
        if not super().filter(event):
            return False
        message = cast(MessageEdited.Event, event).message
        if message.reply_to_msg_id is None:
            # print("reply_to_msg_id IS NONE")
            return False
        if self.message_ids:
            # print(f"COMPARING {message.reply_to_msg_id!r} AND {self.message_id!r}")
            return message.reply_to_msg_id in self.message_ids
        return True

    def __repr__(self):
        return f"ReplyTo({self.message_ids})"


reply_to = _ReplyToMessage
"""Replied message"""


class _TextMessage(_Message):
    def filter(self, event: EventCommon):
        if not super().filter(event):
            return False
        message: Message = cast(NewMessage.Event, event).message
        return (bool(message.raw_text) and
                message.action is None and
                (message.media is None or isinstance(message.media, MessageMediaWebPage))
                )

    def __repr__(self):
        return "Text"


text = _TextMessage()
"""Text message"""


class _RegexText(_TextMessage):
    def __init__(self, pattern: str):
        self.pattern = re.compile(pattern)

    def filter(self, event: EventCommon):
        if not super().filter(event):
            return False
        message: Message = cast(NewMessage.Event, event).message
        return bool(self.pattern.search(message.raw_text) or self.pattern.search(message.text))

    def __repr__(self):
        return f"RegexText({self.pattern})"


regex = _RegexText
"""Match message text with regular expression"""


class _HasButton(_Message):
    def filter(self, event: EventCommon):
        if not super().filter(event):
            return False
        message: Message = cast(NewMessage.Event, event).message
        return message.button_count > 0

    def __repr__(self):
        return "HasButton"


has_button = _HasButton()
"""Message has at least one button."""


class _ChatAction(BaseFilter):
    def filter(self, event) -> bool:
        return isinstance(event, ChatAction.Event)

    def __repr__(self):
        return "ChatAction"


chat_action = _ChatAction()


class _NewTitle(_ChatAction):
    def filter(self, event) -> bool:
        if not super().filter(event):
            return False
        event = cast(ChatAction.Event, event)
        return event.new_title is not None

    def __repr__(self):
        return "NewTitle"


new_title = _NewTitle()


class _NewPhoto(_ChatAction):
    def filter(self, event) -> bool:
        if not super().filter(event):
            return False
        event = cast(ChatAction.Event, event)
        return event.new_photo is not None

    def __repr__(self):
        return "NewPhoto"


new_photo = _NewPhoto()


class _DeletedMessage(BaseFilter):
    def __init__(self, message: Optional[Message] = None):
        self.message = message

    def filter(self, event: EventCommon):
        if not isinstance(event, MessageDeleted.Event):
            return False
        if self.message is None:
            return True
        return self.message.id in event.deleted_ids

    def __repr__(self):
        return "DeletedMessage"


deleted = _DeletedMessage
