# coding=utf-8


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
    SUGGEST_RECIPIENTS = 0x32


class Emoji:
    GROUP = "👥"
    USER = "👤"
    SYSTEM = "💻"
    UNKNOWN = "❓"
    LINK = "🔗"
    MUTED = "🔇"
    MULTI_LINKED = "🖇️"
