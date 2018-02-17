# coding=utf-8

from ehforwarderbot.constants import ChatType


class Flags:
    # General Flags
    CANCEL_PROCESS = "cancel"
    # Chat linking
    LINK_CONFIRM = 0x11
    LINK_EXEC = 0x12
    # Start a chat
    CHAT_HEAD_CONFIRM = 0x21
    # Command
    COMMAND_PENDING = 0x31
    # Message recipient suggestions
    SUGGEST_RECIPIENT = 0x32


class Emoji:
    GROUP = "👥"
    USER = "👤"
    SYSTEM = "💻"
    UNKNOWN = "❓"
    LINK = "🔗"
    MUTED = "🔇"
    MULTI_LINKED = "🖇️"

    @staticmethod
    def get_source_emoji(t: ChatType) -> str:
        """
        Get the Emoji for the corresponding chat type.

        Args:
            t (ChatType): The chat type.

        Returns:
            str: Emoji string.
        """
        if t == ChatType.User:
            return Emoji.USER
        elif t == ChatType.Group:
            return Emoji.GROUP
        elif t == ChatType.System:
            return Emoji.SYSTEM
        else:
            return Emoji.UNKNOWN
