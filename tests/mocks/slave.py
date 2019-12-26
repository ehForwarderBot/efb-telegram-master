import threading
import time
from logging import getLogger
from queue import Queue
from typing import Set, Optional, List, IO, Dict, TypeVar

from ehforwarderbot import EFBChannel, EFBMsg, EFBStatus, ChannelType, MsgType, EFBChat, ChatType, coordinator
from ehforwarderbot.chat import EFBChatNotificationState
from ehforwarderbot.exceptions import EFBChatNotFound
from ehforwarderbot.types import ModuleID, ChatID, MessageID
from ehforwarderbot.utils import extra

_T = TypeVar("_T")


class MockSlaveChannel(EFBChannel):
    channel_name: str = "Mock Slave"
    channel_emoji: str = "➖"
    channel_id: ModuleID = ModuleID("tests.mocks.slave")
    channel_type: ChannelType = ChannelType.Slave
    supported_message_types: Set[MsgType] = {MsgType.Text, MsgType.Link}
    __version__: str = '0.0.2'

    logger = getLogger(channel_id)

    polling = threading.Event()

    __picture_dict: Dict[str, str] = {}

    # fields: name, type, notification, avatar, alias
    __chat_templates = [
        ("A", ChatType.User, EFBChatNotificationState.NONE, "A.png", "Alice"),
        ("B", ChatType.User, EFBChatNotificationState.MENTIONS, "B.png", "Bob"),
        ("C", ChatType.User, EFBChatNotificationState.ALL, "C.png", "Carol"),
        ("D", ChatType.System, EFBChatNotificationState.NONE, "D.png", "Dave"),
        ("E", ChatType.System, EFBChatNotificationState.MENTIONS, "E.png", "Eve"),
        ("F", ChatType.System, EFBChatNotificationState.ALL, "F.png", "Frank"),
        ("G", ChatType.User, EFBChatNotificationState.NONE, "G.png", None),
        ("H", ChatType.User, EFBChatNotificationState.MENTIONS, "H.png", None),
        ("I", ChatType.User, EFBChatNotificationState.ALL, "I.png", None),
        ("J", ChatType.System, EFBChatNotificationState.NONE, "J.png", None),
        ("K", ChatType.System, EFBChatNotificationState.MENTIONS, "K.png", None),
        ("L", ChatType.System, EFBChatNotificationState.ALL, "L.png", None),
        ("U", ChatType.Group, EFBChatNotificationState.NONE, "U.png", "Uranus"),
        ("V", ChatType.Group, EFBChatNotificationState.MENTIONS, "V.png", "Venus"),
        ("W", ChatType.Group, EFBChatNotificationState.ALL, "W.png", "Wonderland"),
        ("X", ChatType.Group, EFBChatNotificationState.NONE, "X.png", None),
        ("Y", ChatType.Group, EFBChatNotificationState.MENTIONS, "Y.png", None),
        ("Z", ChatType.Group, EFBChatNotificationState.ALL, "Z.png", None),
        ("あ", ChatType.User, EFBChatNotificationState.NONE, None, "あべ"),
        ("い", ChatType.User, EFBChatNotificationState.MENTIONS, None, "いとう"),
        ("う", ChatType.User, EFBChatNotificationState.ALL, None, "うえだ"),
        ("え", ChatType.System, EFBChatNotificationState.NONE, None, "えのもと"),
        ("お", ChatType.System, EFBChatNotificationState.MENTIONS, None, "おがわ"),
        ("か", ChatType.System, EFBChatNotificationState.ALL, None, "かとう"),
        ("き", ChatType.User, EFBChatNotificationState.NONE, None, None),
        ("く", ChatType.User, EFBChatNotificationState.MENTIONS, None, None),
        ("け", ChatType.User, EFBChatNotificationState.ALL, None, None),
        ("こ", ChatType.System, EFBChatNotificationState.NONE, None, None),
        ("さ", ChatType.System, EFBChatNotificationState.MENTIONS, None, None),
        ("し", ChatType.System, EFBChatNotificationState.ALL, None, None),
        ("ら", ChatType.Group, EFBChatNotificationState.NONE, None, "ランド"),
        ("り", ChatType.Group, EFBChatNotificationState.MENTIONS, None, "リゾート"),
        ("る", ChatType.Group, EFBChatNotificationState.ALL, None, "ルートディレクトリ"),
        ("れ", ChatType.Group, EFBChatNotificationState.NONE, None, None),
        ("ろ", ChatType.Group, EFBChatNotificationState.MENTIONS, None, None),
        ("わ", ChatType.Group, EFBChatNotificationState.ALL, None, None),
    ]

    __group_member_templates = [
        ("A", ChatType.User, EFBChatNotificationState.NONE, "A.png", "安"),
        ("B", ChatType.User, EFBChatNotificationState.MENTIONS, "B.png", "柏"),
        ("C", ChatType.User, EFBChatNotificationState.ALL, "C.png", "陈"),
        ("D", ChatType.User, EFBChatNotificationState.NONE, "D.png", None),
        ("E", ChatType.User, EFBChatNotificationState.MENTIONS, "E.png", None),
        ("F", ChatType.User, EFBChatNotificationState.ALL, "F.png", None),
        ("Ал", ChatType.User, EFBChatNotificationState.NONE, None, "Александра"),
        ("Бэ", ChatType.User, EFBChatNotificationState.MENTIONS, None, "Борис"),
        ("Вэ", ChatType.User, EFBChatNotificationState.ALL, None, "Владислав"),
        ("Э", ChatType.User, EFBChatNotificationState.NONE, None, None),
        ("Ю", ChatType.User, EFBChatNotificationState.MENTIONS, None, None),
        ("Я", ChatType.User, EFBChatNotificationState.ALL, None, None),
    ]

    def __init__(self, instance_id=None):
        super().__init__(instance_id)
        self.generate_chats()

        self.chat_with_alias = self.chats_by_alias[True][0]
        self.chat_without_alias = self.chats_by_alias[False][0]
        self.group = self.chats_by_chat_type[ChatType.Group][0]

        self.messages: "Queue[EFBMsg]" = Queue()
        self.statuses: "Queue[EFBStatus]" = Queue()

    def clear_messages(self):
        self._clear_queue(self.messages)

    def clear_statuses(self):
        self._clear_queue(self.statuses)

    @staticmethod
    def _clear_queue(q: Queue):
        """Safely clear all items in a queue.
        Written by Niklas R on StackOverflow
        https://stackoverflow.com/a/31892187/1989455
        """
        with q.mutex:
            unfinished = q.unfinished_tasks - len(q.queue)
            if unfinished <= 0:
                if unfinished < 0:
                    raise ValueError('task_done() called too many times')
                q.all_tasks_done.notify_all()
            q.unfinished_tasks = unfinished
            q.queue.clear()
            q.not_full.notify_all()

    def generate_chats(self):
        """Generate a list of chats per the chat templates, and categorise
        them accordingly.
        """
        self.chats: List[EFBChat] = []

        self.chats_by_chat_type: Dict[ChatType, List[EFBChat]] = {
            ChatType.User: [],
            ChatType.Group: [],
            ChatType.System: [],
        }
        self.chats_by_notification_state: Dict[EFBChatNotificationState, List[EFBChat]] = {
            EFBChatNotificationState.ALL: [],
            EFBChatNotificationState.MENTIONS: [],
            EFBChatNotificationState.NONE: [],
        }
        self.chats_by_profile_picture: Dict[bool, List[EFBChat]] = {
            True: [], False: []
        }
        self.chats_by_alias: Dict[bool, List[EFBChat]] = {
            True: [], False: []
        }

        for name, chat_type, notification, avatar, alias in self.__chat_templates:
            chat = EFBChat(self)
            chat.chat_name = name
            chat.chat_alias = alias
            chat.chat_uid = ChatID(f"__chat_{hash(name)}__")
            chat.chat_type = chat_type
            chat.notification = notification
            self.__picture_dict[chat.chat_uid] = avatar

            if chat_type == ChatType.Group:
                self.fill_group(chat)

            self.chats_by_chat_type[chat_type].append(chat)
            self.chats_by_notification_state[notification].append(chat)
            self.chats_by_profile_picture[avatar is not None].append(chat)
            self.chats_by_alias[alias is not None].append(chat)
            self.chats.append(chat)

        self.unknown_chat = EFBChat(self)
        self.unknown_chat.chat_name = "Unknown Chat"
        self.unknown_chat.chat_alias = "不知道"
        self.unknown_chat.chat_uid = ChatID(f"__chat_{hash(self.unknown_chat.chat_name)}__")
        self.unknown_chat.chat_type = ChatType.User
        self.unknown_chat.notification = EFBChatNotificationState.ALL

        self.unknown_channel = EFBChat()
        self.unknown_channel.module_id = "__this_is_not_a_channel__"
        self.unknown_channel.module_name = "Unknown Channel"
        self.unknown_channel.channel_emoji = "‼️"
        self.unknown_channel.chat_name = "Unknown Chat @ unknown channel"
        self.unknown_channel.chat_alias = "知らんでぇ"
        self.unknown_channel.chat_uid = ChatID(f"__chat_{hash(self.unknown_channel.chat_name)}__")
        self.unknown_channel.chat_type = ChatType.User
        self.unknown_channel.notification = EFBChatNotificationState.ALL

    def fill_group(self, group: EFBChat):
        """Populate members into a group per membership template."""
        members = []
        for name, chat_type, notification, avatar, alias in self.__group_member_templates:
            chat = EFBChat(self)
            chat.chat_name = name
            if alias is not None:
                chat.chat_alias = f"{alias} @ {group.chat_name}"
            chat.chat_uid = ChatID(f"__chat_{hash(name)}__")
            chat.chat_type = chat_type
            chat.notification = notification
            chat.group = group
            chat.is_chat = False
            members.append(chat)
        group.members = members

    def poll(self):
        self.polling.wait()

    def send_status(self, status: EFBStatus):
        self.logger.debug("Received status: %r", status)
        self.statuses.put(status)

    def send_message(self, msg: EFBMsg) -> EFBMsg:
        self.logger.debug("Received message: %r", msg)
        self.messages.put(msg)
        msg.uid = MessageID(str(time.time_ns()))
        return msg

    def stop_polling(self):
        self.polling.set()

    def get_chat(self, chat_uid: str, member_uid: Optional[str] = None) -> EFBChat:
        for i in self.chats:
            if chat_uid == i.chat_uid:
                if member_uid:
                    if i.chat_type == ChatType.Group:
                        for j in i.members:
                            if j.chat_uid == member_uid:
                                return j
                        raise EFBChatNotFound()
                    else:
                        raise EFBChatNotFound()
                return i
        raise EFBChatNotFound()

    def get_chats(self) -> List[EFBChat]:
        return self.chats.copy()

    def get_chat_picture(self, chat: EFBChat) -> Optional[IO[bytes]]:
        if self.__picture_dict.get(chat.chat_uid):
            return open(f'tests/mocks/{self.__picture_dict[chat.chat_uid]}', 'rb')

    def get_chats_by_criteria(self,
                              chat_type: Optional[ChatType] = None,
                              notification: Optional[EFBChatNotificationState] = None,
                              avatar: Optional[bool] = None,
                              alias: Optional[bool] = None) -> List[EFBChat]:
        """Find a list of chats that satisfy a criteria. Leave a value
        unset (None) to pick all possible values of the criteria.
        """
        s = self.chats.copy()
        if chat_type is not None:
            s = [i for i in s if i in self.chats_by_chat_type[chat_type]]
        if notification is not None:
            s = [i for i in s if i in self.chats_by_notification_state[notification]]
        if avatar is not None:
            s = [i for i in s if i in self.chats_by_profile_picture[avatar]]
        if alias is not None:
            s = [i for i in s if i in self.chats_by_alias[alias]]
        return s

    def get_chat_by_criteria(self, chat_type: Optional[ChatType] = None,
                             notification: Optional[EFBChatNotificationState] = None,
                             avatar: Optional[bool] = None,
                             alias: Optional[bool] = None) -> EFBChat:
        """Alias of ``get_chats_by_criteria(*args)[0]``."""
        return self.get_chats_by_criteria(chat_type=chat_type,
                                          notification=notification,
                                          avatar=avatar,
                                          alias=alias)[0]

    @extra(name="Echo",
           desc="Echo back the input.\n"
                "Usage:\n"
                "    {function_name} text")
    def echo(self, args):
        return args

    # TODO: Send types of messages and statuses to slave channels

    def send_text_message(self, chat: EFBChat,
                          author: Optional[EFBChat] = None,
                          target: Optional[EFBMsg] = None) -> EFBMsg:
        """Send a text message to master channel.
        Leave author blank to use “self” of the chat.

        Returns the message sent.
        """
        timestamp = time.time_ns()
        if author is None:
            author = EFBChat(self).self()
            if chat.chat_type is ChatType.Group:
                author.is_chat = False
                author.group = chat
        message = EFBMsg()
        message.chat = chat
        message.author = author
        message.type = MsgType.Text
        message.target = target
        message.uid = f"__msg_id_{timestamp}__"
        message.text = f"Content of message with ID {message.uid}"
        message.deliver_to = coordinator.master

        coordinator.send_message(message)

        return message
