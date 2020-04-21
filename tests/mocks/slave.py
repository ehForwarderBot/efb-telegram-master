import random
import threading
import time
from contextlib import contextmanager
from logging import getLogger
from pathlib import Path
from queue import Queue
from typing import Set, Optional, List, IO, Dict, TypeVar, Tuple, BinaryIO
from typing_extensions import Literal
from uuid import uuid4

from ehforwarderbot import Message, Status, MsgType, Chat, coordinator
from ehforwarderbot.channel import SlaveChannel
from ehforwarderbot.chat import ChatNotificationState, PrivateChat, SystemChat, GroupChat, ChatMember, SelfChatMember
from ehforwarderbot.exceptions import EFBChatNotFound, EFBOperationNotSupported, EFBMessageReactionNotPossible
from ehforwarderbot.message import MessageCommands, MessageCommand, StatusAttribute, LinkAttribute, \
    Substitutions, LocationAttribute
from ehforwarderbot.status import MessageRemoval, ReactToMessage, MessageReactionsUpdate, ChatUpdates, \
    MemberUpdates
from ehforwarderbot.types import ModuleID, ChatID, MessageID, ReactionName, Reactions
from ehforwarderbot.utils import extra

_T = TypeVar("_T")
ChatTypeName = Literal['PrivateChat', 'GroupChat', 'SystemChat']


class MockSlaveChannel(SlaveChannel):

    channel_name: str = "Mock Slave"
    channel_emoji: str = "➖"
    channel_id: ModuleID = ModuleID("tests.mocks.slave")
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
        ("A", PrivateChat, ChatNotificationState.NONE, "A.png", "Alice"),
        ("B", PrivateChat, ChatNotificationState.MENTIONS, "B.png", "Bob"),
        ("C", PrivateChat, ChatNotificationState.ALL, "C.png", "Carol"),
        ("D", SystemChat, ChatNotificationState.NONE, "D.png", "Dave"),
        ("E", SystemChat, ChatNotificationState.MENTIONS, "E.png", "Eve"),
        ("F", SystemChat, ChatNotificationState.ALL, "F.png", "Frank"),
        ("G", PrivateChat, ChatNotificationState.NONE, "G.png", None),
        ("H", PrivateChat, ChatNotificationState.MENTIONS, "H.png", None),
        ("I", PrivateChat, ChatNotificationState.ALL, "I.png", None),
        ("J", SystemChat, ChatNotificationState.NONE, "J.png", None),
        ("K", SystemChat, ChatNotificationState.MENTIONS, "K.png", None),
        ("L", SystemChat, ChatNotificationState.ALL, "L.png", None),
        ("Ur", GroupChat, ChatNotificationState.NONE, "U.png", "Uranus"),
        ("Ve", GroupChat, ChatNotificationState.MENTIONS, "V.png", "Venus"),
        ("Wo", GroupChat, ChatNotificationState.ALL, "W.png", "Wonderland"),
        ("Xe", GroupChat, ChatNotificationState.NONE, "X.png", None),
        ("Yb", GroupChat, ChatNotificationState.MENTIONS, "Y.png", None),
        ("Zn", GroupChat, ChatNotificationState.ALL, "Z.png", None),
        ("あ", PrivateChat, ChatNotificationState.NONE, None, "あべ"),
        ("い", PrivateChat, ChatNotificationState.MENTIONS, None, "いとう"),
        ("う", PrivateChat, ChatNotificationState.ALL, None, "うえだ"),
        ("え", SystemChat, ChatNotificationState.NONE, None, "えのもと"),
        ("お", SystemChat, ChatNotificationState.MENTIONS, None, "おがわ"),
        ("か", SystemChat, ChatNotificationState.ALL, None, "かとう"),
        ("き", PrivateChat, ChatNotificationState.NONE, None, None),
        ("く", PrivateChat, ChatNotificationState.MENTIONS, None, None),
        ("け", PrivateChat, ChatNotificationState.ALL, None, None),
        ("こ", SystemChat, ChatNotificationState.NONE, None, None),
        ("さ", SystemChat, ChatNotificationState.MENTIONS, None, None),
        ("し", SystemChat, ChatNotificationState.ALL, None, None),
        ("らん", GroupChat, ChatNotificationState.NONE, None, "ランド"),
        ("りぞ", GroupChat, ChatNotificationState.MENTIONS, None, "リゾート"),
        ("るう", GroupChat, ChatNotificationState.ALL, None, "ルートディレクトリ"),
        ("れつ", GroupChat, ChatNotificationState.NONE, None, None),
        ("ろく", GroupChat, ChatNotificationState.MENTIONS, None, None),
        ("われ", GroupChat, ChatNotificationState.ALL, None, None),
    ]

    __group_member_templates = [
        ("A", ChatNotificationState.NONE, "A.png", "安"),
        ("B & S", ChatNotificationState.MENTIONS, "B.png", "柏"),
        ("C", ChatNotificationState.ALL, "C.png", "陈"),
        ("D", ChatNotificationState.NONE, "D.png", None),
        ("E", ChatNotificationState.MENTIONS, "E.png", None),
        ("F", ChatNotificationState.ALL, "F.png", None),
        ("Ал", ChatNotificationState.NONE, None, "Александра"),
        ("Бэ", ChatNotificationState.MENTIONS, None, "Борис"),
        ("Вэ", ChatNotificationState.ALL, None, "Владислав"),
        ("Э", ChatNotificationState.NONE, None, None),
        ("Ю", ChatNotificationState.MENTIONS, None, None),
        ("Я", ChatNotificationState.ALL, None, None),
    ]

    # endregion [Chat data]

    def __init__(self, instance_id=None):
        super().__init__(instance_id)
        self.generate_chats()

        self.chat_with_alias: PrivateChat = self.chats_by_alias[True][0]
        self.chat_without_alias: PrivateChat = self.chats_by_alias[False][0]
        self.group: GroupChat = self.chats_by_chat_type['GroupChat'][0]

        self.messages: "Queue[Message]" = Queue()
        self.statuses: "Queue[Status]" = Queue()
        self.messages_sent: Dict[str, Message] = dict()

        # flags
        self.message_removal_possible: bool = True
        self.accept_message_reactions: str = "accept"

        # chat/member changes
        self.chat_to_toggle: PrivateChat = self.get_chat(self.CHAT_ID_FORMAT.format(hash=hash("I")))
        self.chat_to_edit: PrivateChat = self.get_chat(self.CHAT_ID_FORMAT.format(hash=hash("われ")))
        self.member_to_toggle: ChatMember = self.get_chat(self.group.uid).get_member(self.CHAT_ID_FORMAT.format(hash=hash("Ю")))
        self.member_to_edit: ChatMember = self.get_chat(self.group.uid).get_member(self.CHAT_ID_FORMAT.format(hash=hash("Я")))

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
        self.chats: List[Chat] = []

        self.chats_by_chat_type: Dict[ChatTypeName, List[Chat]] = {
            'PrivateChat': [],
            'GroupChat': [],
            'SystemChat': [],
        }
        self.chats_by_notification_state: Dict[ChatNotificationState, List[Chat]] = {
            ChatNotificationState.ALL: [],
            ChatNotificationState.MENTIONS: [],
            ChatNotificationState.NONE: [],
        }
        self.chats_by_profile_picture: Dict[bool, List[Chat]] = {
            True: [], False: []
        }
        self.chats_by_alias: Dict[bool, List[Chat]] = {
            True: [], False: []
        }

        for name, chat_type, notification, avatar, alias in self.__chat_templates:
            chat = chat_type(
                channel=self,
                name=name,
                alias=alias,
                uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
                notification=notification
            )
            self.__picture_dict[chat.uid] = avatar

            if chat_type == GroupChat:
                self.fill_group(chat)

            self.chats_by_chat_type[chat_type.__name__].append(chat)
            self.chats_by_notification_state[notification].append(chat)
            self.chats_by_profile_picture[avatar is not None].append(chat)
            self.chats_by_alias[alias is not None].append(chat)
            self.chats.append(chat)

        name = "Unknown Chat"
        self.unknown_chat: PrivateChat = PrivateChat(
            channel=self,
            name=name,
            alias="不知道",
            uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
            notification=ChatNotificationState.ALL
        )

        name = "Unknown Chat @ unknown channel"
        self.unknown_channel: PrivateChat = PrivateChat(
            module_id="__this_is_not_a_channel__",
            module_name="Unknown Channel",
            channel_emoji="‼️",
            name=name,
            alias="知らんでぇ",
            uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
            notification=ChatNotificationState.ALL
        )

        name = "backup_chat"
        self.backup_chat: PrivateChat = PrivateChat(
            channel=self,
            name=name,
            uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
            notification=ChatNotificationState.ALL
        )

        name = "backup_member"
        self.backup_member: ChatMember = ChatMember(
            self.chats_by_chat_type['GroupChat'][0],
            name=name,
            uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name)))
        )

    def fill_group(self, group: Chat):
        """Populate members into a group per membership template."""
        for name, notification, avatar, alias in self.__group_member_templates:
            group.add_member(
                name=name,
                alias=f"{alias} @ {group.name[::-1]}" if alias is not None else None,
                uid=ChatID(self.CHAT_ID_FORMAT.format(hash=hash(name))),
            )

    # endregion [Populate chats]
    # region [Necessities]

    def poll(self):
        self.polling.wait()

    def send_status(self, status: Status):
        self.logger.debug("Received status: %r", status)
        if isinstance(status, MessageRemoval):
            self.message_removal_status(status)
        elif isinstance(status, ReactToMessage):
            self.react_to_message_status(status)
        self.statuses.put(status)

    def send_message(self, msg: Message) -> Message:
        self.logger.debug("Received message: %r", msg)
        self.messages.put(msg)
        msg.uid = MessageID(str(uuid4()))
        self.messages_sent[msg.uid] = msg
        return msg

    def stop_polling(self):
        self.polling.set()

    def get_chat(self, chat_uid: str) -> Chat:
        for i in self.chats:
            if chat_uid == i.uid:
                return i
        raise EFBChatNotFound()

    def get_chats(self) -> List[Chat]:
        return self.chats.copy()

    def get_chat_picture(self, chat: Chat) -> Optional[BinaryIO]:
        if self.__picture_dict.get(chat.uid):
            return open(f'tests/mocks/{self.__picture_dict[chat.uid]}', 'rb')

    # endregion [Necessities]

    def get_chats_by_criteria(self,
                              chat_type: Optional[ChatTypeName] = None,
                              notification: Optional[ChatNotificationState] = None,
                              avatar: Optional[bool] = None,
                              alias: Optional[bool] = None) -> List[Chat]:
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

    def get_chat_by_criteria(self, chat_type: Optional[ChatTypeName] = None,
                             notification: Optional[ChatNotificationState] = None,
                             avatar: Optional[bool] = None,
                             alias: Optional[bool] = None) -> Chat:
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

    # region [Reactions]

    def build_reactions(self, group: Chat) -> Reactions:
        possible_reactions = self.suggested_reactions[:-1] + [None]
        chats = group.members
        reactions: Dict[ReactionName, List[Chat]] = {}
        for i in chats:
            reaction = random.choice(possible_reactions)
            if reaction is None:
                continue
            elif reaction not in reactions:
                reactions[reaction] = [i]
            else:
                reactions[reaction].append(i)
        return reactions

    def send_reactions_update(self, message: Message) -> MessageReactionsUpdate:
        reactions = self.build_reactions(message.chat)
        message.reactions = reactions
        status = MessageReactionsUpdate(
            chat=message.chat,
            msg_id=message.uid,
            reactions=reactions
        )
        coordinator.send_status(status)
        return status

    # endregion [Reactions]
    # region [Commands]

    @staticmethod
    def build_message_commands() -> MessageCommands:
        return MessageCommands([
            MessageCommand("Ping!", "command_ping"),
            MessageCommand("Bam", "command_bam"),
        ])

    @staticmethod
    def command_ping() -> Optional[str]:
        return "Pong!"

    @staticmethod
    def command_bam():
        return None

    # endregion [Commands]

    @staticmethod
    def build_substitutions(text: str, chat: Chat) -> Substitutions:
        size = len(text)
        a_0, a_1, b_0, b_1 = sorted(random.sample(range(size + 1), k=4))
        a = chat.self
        b = getattr(chat, 'other', random.choice(chat.members))
        if random.randrange(2) == 1:  # randomly swap a and b
            a, b = b, a
        return Substitutions({
            (a_0, a_1): a,
            (b_0, b_1): b,
        })

    def attach_message_properties(self, message: Message, reactions: bool, commands: bool,
                                  substitutions: bool) -> Message:
        reactions_val = self.build_reactions(message.chat) if reactions else {}
        commands_val = self.build_message_commands() if commands else None
        substitutions_val = self.build_substitutions(message.text, message.chat) if substitutions else None
        message.reactions = reactions_val
        message.commands = commands_val
        message.substitutions = substitutions_val
        return message

    def send_text_message(self, chat: Chat,
                          author: Optional[ChatMember] = None,
                          target: Optional[Message] = None,
                          reactions: bool = False,
                          commands: bool = False,
                          substitution: bool = False,
                          unsupported: bool = False) -> Message:
        """Send a text message to master channel.
        Leave author blank to use “self” of the chat.

        Returns the message sent.
        """
        author = author or chat.self
        uid = f"__msg_id_{uuid4()}__"
        msg_type = MsgType.Unsupported if unsupported else MsgType.Text
        message = Message(
            chat=chat,
            author=author,
            type=msg_type,
            target=target,
            uid=uid,
            text=f"Content of {msg_type.name} message with ID {uid}",
            deliver_to=coordinator.master
        )
        message = self.attach_message_properties(message, reactions, commands, substitution)

        coordinator.send_message(message)
        self.messages_sent[uid] = message

        return message

    def edit_text_message(self, message: Message, reactions: bool = False, commands: bool = False,
                          substitution: bool = False) -> Message:
        message.edit = True
        message.text = f"Edited {message.type.name} message {message.uid} @ {time.time_ns()}"
        message = self.attach_message_properties(message, reactions, commands, substitution)
        self.messages_sent[message.uid] = message
        coordinator.send_message(message)
        return message

    def send_link_message(self, chat: Chat,
                          author: Optional[ChatMember] = None,
                          target: Optional[Message] = None,
                          reactions: bool = False,
                          commands: bool = False,
                          substitution: bool = False) -> Message:
        author = author or chat.self
        uid = f"__msg_id_{uuid4()}__"
        message = Message(
            chat=chat, author=author,
            type=MsgType.Link,
            target=target, uid=uid,
            text=f"Content of link message with ID {uid}",
            attributes=LinkAttribute(
                title="EH Forwarder Bot",
                description="EH Forwarder Bot project site.",
                url="https://efb.1a23.studio"
            ),
            deliver_to=coordinator.master
        )
        message = self.attach_message_properties(message, reactions, commands, substitution)
        self.messages_sent[uid] = message
        coordinator.send_message(message)
        return message

    def edit_link_message(self, message: Message,
                          reactions: bool = False,
                          commands: bool = False,
                          substitution: bool = False) -> Message:

        message.text = f"Content of edited link message with ID {message.uid}"
        message.edit = True
        message.attributes = LinkAttribute(
            title="EH Forwarder Bot (edited)",
            description="EH Forwarder Bot project site. (edited)",
            url="https://efb.1a23.studio/#edited"
        )
        message = self.attach_message_properties(message, reactions, commands, substitution)
        self.messages_sent[message.uid] = message
        coordinator.send_message(message)
        return message

    def send_location_message(self, chat: Chat,
                              author: Optional[ChatMember] = None,
                              target: Optional[Message] = None,
                              reactions: bool = False,
                              commands: bool = False,
                              substitution: bool = False) -> Message:
        author = author or chat.self
        uid = f"__msg_id_{uuid4()}__"
        message = Message(
            chat=chat, author=author,
            type=MsgType.Location,
            target=target, uid=uid,
            text=f"Content of location message with ID {uid}",
            attributes=LocationAttribute(
                latitude=random.uniform(0.0, 90.0),
                longitude=random.uniform(0.0, 90.0)
            ),
            deliver_to=coordinator.master
        )
        message = self.attach_message_properties(message, reactions, commands, substitution)
        self.messages_sent[uid] = message
        coordinator.send_message(message)
        return message

    def edit_location_message(self, message: Message,
                              reactions: bool = False,
                              commands: bool = False,
                              substitution: bool = False) -> Message:
        message.text = f"Content of edited location message with ID {message.uid}"
        message.edit = True
        message.attributes = LocationAttribute(
            latitude=random.uniform(0.0, 90.0),
            longitude=random.uniform(0.0, 90.0)
        )
        message = self.attach_message_properties(message, reactions, commands, substitution)
        self.messages_sent[message.uid] = message
        coordinator.send_message(message)
        return message

    def send_file_like_message(self,
                               msg_type: MsgType,
                               file_path: Path,
                               mime: str,
                               chat: Chat,
                               author: Optional[ChatMember] = None,
                               target: Optional[Message] = None,
                               reactions: bool = False,
                               commands: bool = False,
                               substitution: bool = False) -> Message:
        author = author or chat.self
        uid = f"__msg_id_{uuid4()}__"
        message = Message(
            chat=chat, author=author,
            type=msg_type, target=target, uid=uid,
            file=file_path.open('rb'), filename=file_path.name,
            path=file_path, mime=mime,
            text=f"Content of {msg_type.name} message with ID {uid}",
            deliver_to=coordinator.master
        )
        message = self.attach_message_properties(message, reactions, commands, substitution)
        self.messages_sent[uid] = message
        coordinator.send_message(message)
        return message

    def edit_file_like_message_text(self, message: Message,
                                    reactions: bool = False,
                                    commands: bool = False,
                                    substitution: bool = False) -> Message:
        message.text = f"Content of edited {message.type.name} message with ID {message.uid}"
        message.edit = True
        message.edit_media = False
        message = self.attach_message_properties(message, reactions, commands, substitution)
        self.messages_sent[message.uid] = message
        coordinator.send_message(message)
        return message

    def edit_file_like_message(self, message: Message,
                               file_path: Path,
                               mime: str,
                               reactions: bool = False,
                               commands: bool = False,
                               substitution: bool = False) -> Message:
        message.text = f"Content of edited {message.type.name} media with ID {message.uid}"
        message.edit = True
        message.edit_media = True
        message.file = file_path.open('rb')
        message.filename = file_path.name
        message.path = file_path
        message.mime = mime
        message = self.attach_message_properties(message, reactions, commands, substitution)
        self.messages_sent[message.uid] = message
        coordinator.send_message(message)
        return message

    def send_status_message(self, status: StatusAttribute,
                            chat: Chat,
                            author: Optional[ChatMember] = None,
                            target: Optional[Message] = None) -> Message:
        """Send a status message to master channel.
        Leave author blank to use “self” of the chat.

        Returns the message sent.
        """
        author = author or chat.self
        uid = f"__msg_id_{uuid4()}__"
        message = Message(
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

    def message_removal_status(self, status: MessageRemoval):
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
    def react_to_message_status(self, status: ReactToMessage):
        if self.accept_message_reactions == "reject_one":
            raise EFBMessageReactionNotPossible("Message reaction is rejected by flag.")
        if self.accept_message_reactions == "reject_all":
            raise EFBOperationNotSupported("All message reactions are rejected by flag.")
        message = self.messages_sent.get(status.msg_id)
        if message is None:
            raise EFBOperationNotSupported("Message is not found.")

        if status.reaction is None:
            for idx, i in message.reactions.items():
                message.reactions[idx] = [j for j in i if not isinstance(j, SelfChatMember)]
        else:
            if status.reaction not in message.reactions:
                message.reactions[status.reaction] = []
            message.reactions[status.reaction].append(message.chat.self)

        coordinator.send_status(MessageReactionsUpdate(
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

    def send_chat_update_status(self) -> Tuple[Chat, Chat, Chat]:
        """
        Returns:
            chat added, chat edited, chat removed
        """
        keyword = " (Edited)"
        if self.backup_chat not in self.chats:
            to_add, to_remove = self.backup_chat, self.chat_to_toggle
            self.chat_to_edit.name += keyword
        else:
            to_add, to_remove = self.chat_to_toggle, self.backup_chat
            self.chat_to_edit.name = self.chat_to_edit.name.replace(keyword, '')
        self.chats.append(to_add)
        self.chats.remove(to_remove)
        coordinator.send_status(ChatUpdates(
            self,
            new_chats=[to_add.uid],
            modified_chats=[self.chat_to_edit.uid],
            removed_chats=[to_remove.uid],
        ))
        return to_add, self.chat_to_edit, to_remove

    # noinspection PyUnresolvedReferences
    def send_member_update_status(self) -> Tuple[ChatMember, ChatMember, ChatMember]:
        """
        Returns:
            member added, member edited, member removed
        """
        keyword = " (Edited)"
        if self.backup_member not in self.group.members:
            to_add, to_remove = self.backup_member, self.member_to_toggle
            self.member_to_edit.name += keyword
        else:
            to_add, to_remove = self.member_to_toggle, self.backup_member
            self.member_to_edit.name = self.member_to_edit.name.replace(keyword, '')
        self.group.members.append(to_add)
        self.group.members.remove(to_remove)
        coordinator.send_status(MemberUpdates(
            self, self.group.uid,
            new_members=[to_add.uid],
            modified_members=[self.member_to_edit.uid],
            removed_members=[to_remove.uid],
        ))
        return to_add, self.member_to_edit, to_remove

    # endregion [Chat/Member updates]

    def get_message_by_id(self, chat: 'Chat', msg_id: MessageID) -> Optional['Message']:
        raise NotImplementedError
