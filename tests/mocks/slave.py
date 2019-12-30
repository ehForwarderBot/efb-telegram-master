import random
import threading
from contextlib import contextmanager
from logging import getLogger
from queue import Queue
from typing import Set, Optional, List, IO, Dict, TypeVar, Tuple
from uuid import uuid4

from ehforwarderbot import EFBChannel, EFBMsg, EFBStatus, ChannelType, MsgType, EFBChat, ChatType, coordinator
from ehforwarderbot.chat import EFBChatNotificationState
from ehforwarderbot.exceptions import EFBChatNotFound, EFBOperationNotSupported, EFBMessageReactionNotPossible
from ehforwarderbot.message import EFBMsgCommands, EFBMsgCommand, EFBMsgStatusAttribute
from ehforwarderbot.status import EFBMessageRemoval, EFBReactToMessage, EFBMessageReactionsUpdate, EFBChatUpdates, \
    EFBMemberUpdates
from ehforwarderbot.types import ModuleID, ChatID, MessageID, ReactionName, Reactions
from ehforwarderbot.utils import extra

_T = TypeVar("_T")


class MockSlaveChannel(EFBChannel):
    channel_name: str = "Mock Slave"
    channel_emoji: str = "➖"
    channel_id: ModuleID = ModuleID("tests.mocks.slave")
    channel_type: ChannelType = ChannelType.Slave
    supported_message_types: Set[MsgType] = {
        MsgType.Text, MsgType.Image, MsgType.Voice, MsgType.Animation,
        MsgType.Video, MsgType.File, MsgType.Location, MsgType.Link,
        MsgType.Sticker, MsgType.Status, MsgType.Unsupported
    }
    __version__: str = '0.0.2'

    logger = getLogger(channel_id)

    CHAT_ID_FORMAT = "__chat_{hash}__"

    polling = threading.Event()

    __picture_dict: Dict[str, str] = {}

    suggested_reactions: List[ReactionName] = [
        ReactionName("R0"),
        ReactionName("R1"),
        ReactionName("R2"),
        ReactionName("R3"),
        ReactionName("R4")
    ]

    # region [Chat data]
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

    # endregion [Chat data]

    def __init__(self, instance_id=None):
        super().__init__(instance_id)
        self.generate_chats()

        self.chat_with_alias = self.chats_by_alias[True][0]
        self.chat_without_alias = self.chats_by_alias[False][0]
        self.group = self.chats_by_chat_type[ChatType.Group][0]

        self.messages: "Queue[EFBMsg]" = Queue()
        self.statuses: "Queue[EFBStatus]" = Queue()
        self.messages_sent: Dict[str, EFBMsg] = dict()

        # flags
        self.message_removal_possible: bool = True
        self.accept_message_reactions: str = "accept"

        # chat/member changes
        self.chat_to_toggle = self.get_chat(self.CHAT_ID_FORMAT.format(hash=hash("I")))
        self.chat_to_edit = self.get_chat(self.CHAT_ID_FORMAT.format(hash=hash("わ")))
        self.member_to_toggle = self.get_chat(self.group.chat_uid, self.CHAT_ID_FORMAT.format(hash=hash("Ю")))
        self.member_to_edit = self.get_chat(self.group.chat_uid, self.CHAT_ID_FORMAT.format(hash=hash("Я")))

    # region [Clear queues]

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

    # endregion [Clear queues]
    # region [Populate chats]

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
            chat = EFBChat(
                channel=self,
                chat_name=name,
                chat_alias=alias,
                chat_uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
                chat_type=chat_type,
                notification=notification
            )
            self.__picture_dict[chat.chat_uid] = avatar

            if chat_type == ChatType.Group:
                self.fill_group(chat)

            self.chats_by_chat_type[chat_type].append(chat)
            self.chats_by_notification_state[notification].append(chat)
            self.chats_by_profile_picture[avatar is not None].append(chat)
            self.chats_by_alias[alias is not None].append(chat)
            self.chats.append(chat)

        name = "Unknown Chat"
        self.unknown_chat = EFBChat(
            channel=self,
            chat_name=name,
            chat_alias="不知道",
            chat_uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
            chat_type=ChatType.User,
            notification=EFBChatNotificationState.ALL
        )

        name = "Unknown Chat @ unknown channel"
        self.unknown_channel = EFBChat(
            module_id="__this_is_not_a_channel__",
            module_name="Unknown Channel",
            channel_emoji="‼️",
            chat_name=name,
            chat_alias="知らんでぇ",
            chat_uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
            chat_type=ChatType.User,
            notification=EFBChatNotificationState.ALL
        )

        name = "backup_chat"
        self.backup_chat = EFBChat(
            channel=self,
            chat_name=name,
            chat_uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
            chat_type=ChatType.User,
            notification=EFBChatNotificationState.ALL
        )

        name = "backup_member"
        self.backup_member = EFBChat(
            channel=self,
            chat_name=name,
            chat_uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
            chat_type=ChatType.User,
            notification=EFBChatNotificationState.ALL,
            group=self.chats_by_chat_type[ChatType.Group][0],
            is_chat=False
        )

    def fill_group(self, group: EFBChat):
        """Populate members into a group per membership template."""
        members = []
        for name, chat_type, notification, avatar, alias in self.__group_member_templates:
            chat = EFBChat(
                channel=self,
                chat_name=name,
                chat_alias=f"{alias} @ {group.chat_name}" if alias is not None else None,
                chat_uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
                chat_type=chat_type,
                notification=notification,
                group=group,
                is_chat=False
            )
            members.append(chat)
        group.members = members

    # endregion [Populate chats]
    # region [Necessities]

    def poll(self):
        self.polling.wait()

    def send_status(self, status: EFBStatus):
        self.logger.debug("Received status: %r", status)
        if isinstance(status, EFBMessageRemoval):
            self.message_removal_status(status)
        elif isinstance(status, EFBReactToMessage):
            self.react_to_message_status(status)
        self.statuses.put(status)

    def send_message(self, msg: EFBMsg) -> EFBMsg:
        self.logger.debug("Received message: %r", msg)
        self.messages.put(msg)
        msg.uid = MessageID(str(uuid4()))
        self.messages_sent[msg.uid] = msg
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

    # endregion [Necessities]

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

    def get_self_chat(self, base_chat: EFBChat) -> EFBChat:
        return EFBChat(
            channel=self,
            group=base_chat if base_chat.chat_type is ChatType.Group else None
        ).self()

    # TODO: Send types of messages and statuses to slave channels

    # region [Reactions]

    def build_reactions(self, group: EFBChat) -> Reactions:
        possible_reactions = self.suggested_reactions[:-1] + [None]
        chats = group.members
        reactions: Dict[ReactionName, List[EFBChat]] = {}
        for i in chats:
            reaction = random.choice(possible_reactions)
            if reaction is None:
                continue
            elif reaction not in reactions:
                reactions[reaction] = [i]
            else:
                reactions[reaction].append(i)
        return reactions

    def send_reactions_update(self, message: EFBMsg) -> EFBMessageReactionsUpdate:
        reactions = self.build_reactions(message.chat)
        message.reactions = reactions
        status = EFBMessageReactionsUpdate(
            chat=message.chat,
            msg_id=message.uid,
            reactions=reactions
        )
        coordinator.send_status(status)
        return status

    # endregion [Reactions]
    # region [Commands]

    @staticmethod
    def build_message_commands() -> EFBMsgCommands:
        return EFBMsgCommands([
            EFBMsgCommand("Ping!", "command_ping"),
            EFBMsgCommand("Bam", "command_bam"),
        ])

    @staticmethod
    def command_ping() -> Optional[str]:
        return "Pong!"

    @staticmethod
    def command_bam():
        return None

    # endregion [Commands]

    def send_text_message(self, chat: EFBChat,
                          author: Optional[EFBChat] = None,
                          target: Optional[EFBMsg] = None,
                          reactions: bool = False,
                          commands: bool = False) -> EFBMsg:
        """Send a text message to master channel.
        Leave author blank to use “self” of the chat.

        Returns the message sent.
        """
        if author is None:
            author = EFBChat(self).self()
            if chat.chat_type is ChatType.Group:
                author.is_chat = False
                author.group = chat
        uid = f"__msg_id_{uuid4()}__"
        reactions = self.build_reactions(chat) if reactions else None
        commands = self.build_message_commands() if commands else None
        message = EFBMsg(
            chat=chat,
            author=author,
            type=MsgType.Text,
            target=target,
            uid=uid,
            text=f"Content of message with ID {uid}",
            reactions=reactions,
            commands=commands,
            deliver_to=coordinator.master
        )

        coordinator.send_message(message)
        self.messages_sent[uid] = message

        return message

    def send_status_message(self, status: EFBMsgStatusAttribute,
                            chat: EFBChat,
                            author: Optional[EFBChat] = None,
                            target: Optional[EFBMsg] = None) -> EFBMsg:
        """Send a status message to master channel.
        Leave author blank to use “self” of the chat.

        Returns the message sent.
        """
        if author is None:
            author = EFBChat(self).self()
            if chat.chat_type is ChatType.Group:
                author.is_chat = False
                author.group = chat
        uid = f"__msg_id_{uuid4()}__"
        message = EFBMsg(
            chat=chat,
            author=author,
            type=MsgType.Status,
            target=target,
            uid=uid,
            text="",
            attributes=status,
            deliver_to=coordinator.master
        )

        coordinator.send_message(message)
        self.messages_sent[uid] = message

        return message

    # region [Message removal]

    def message_removal_status(self, status: EFBMessageRemoval):
        if not self.message_removal_possible:
            raise EFBOperationNotSupported("Message removal is not possible by flag.")

    @contextmanager
    def set_message_removal(self, value: bool):
        backup = self.message_removal_possible
        self.message_removal_possible = value
        try:
            yield
        finally:
            self.message_removal_possible = backup

    # endregion [Message removal]
    # region [Message reactions]

    # noinspection PyUnresolvedReferences
    def react_to_message_status(self, status: EFBReactToMessage):
        if self.accept_message_reactions == "reject_one":
            raise EFBMessageReactionNotPossible("Message reaction is rejected by flag.")
        if self.accept_message_reactions == "reject_all":
            raise EFBOperationNotSupported("All message reactions are rejected by flag.")
        message = self.messages_sent.get(status.msg_id)
        if message is None:
            raise EFBOperationNotSupported("Message is not found.")

        if status.reaction is None:
            for idx, i in message.reactions.items():
                message.reactions[idx] = [j for j in i if not j.is_self]
        else:
            if status.reaction not in message.reactions:
                message.reactions[status.reaction] = []
            message.reactions[status.reaction].append(self.get_self_chat(message.chat))

        coordinator.send_status(EFBMessageReactionsUpdate(
            chat=message.chat,
            msg_id=message.uid,
            reactions=message.reactions
        ))

    @contextmanager
    def set_react_to_message(self, value: bool):
        """
        Set reaction response status.

        Args:
            value:
                "reject_one": Reject with EFBMessageReactionNotPossible.
                "reject_all": Reject with EFBOperationNotSupported.
        """
        backup = self.accept_message_reactions
        self.accept_message_reactions = value
        try:
            yield
        finally:
            self.accept_message_reactions = backup

    # endregion [Message reactions]
    # region [Chat/Member updates]

    def send_chat_update_status(self) -> Tuple[EFBChat, EFBChat, EFBChat]:
        """
        Returns:
            chat added, chat edited, chat removed
        """
        keyword = " (Edited)"
        if self.backup_chat not in self.chats:
            to_add, to_remove = self.backup_chat, self.chat_to_toggle
            self.chat_to_edit.chat_name += keyword
        else:
            to_add, to_remove = self.chat_to_toggle, self.backup_chat
            self.chat_to_edit.chat_name = self.chat_to_edit.chat_name.replace(keyword, '')
        self.chats.append(to_add)
        self.chats.remove(to_remove)
        coordinator.send_status(EFBChatUpdates(
            self,
            new_chats=[to_add.chat_uid],
            modified_chats=[self.chat_to_edit.chat_uid],
            removed_chats=[to_remove.chat_uid],
        ))
        return to_add, self.chat_to_edit, to_remove

    # noinspection PyUnresolvedReferences
    def send_member_update_status(self) -> Tuple[EFBChat, EFBChat, EFBChat]:
        """
        Returns:
            member added, member edited, member removed
        """
        keyword = " (Edited)"
        if self.backup_member not in self.group.members:
            to_add, to_remove = self.backup_member, self.member_to_toggle
            self.member_to_edit.chat_name += keyword
        else:
            to_add, to_remove = self.member_to_toggle, self.backup_member
            self.member_to_edit.chat_name = self.member_to_edit.chat_name.replace(keyword, '')
        self.group.members.append(to_add)
        self.group.members.remove(to_remove)
        coordinator.send_status(EFBMemberUpdates(
            self, self.group.chat_uid,
            new_members=[to_add.chat_uid],
            modified_members=[self.member_to_edit.chat_uid],
            removed_members=[to_remove.chat_uid],
        ))
        return to_add, self.member_to_edit, to_remove

    # endregion [Chat/Member updates]
