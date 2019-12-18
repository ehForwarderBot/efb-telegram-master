# coding=utf-8

import datetime
import logging
import pickle
import time
from functools import partial
from queue import Queue
from threading import Thread
from typing import List, Optional, Tuple, Callable, Sequence, Any, Dict, Collection

from peewee import Model, TextField, DateTimeField, CharField, SqliteDatabase, DoesNotExist, fn, BlobField, \
    OperationalError
from playhouse.migrate import SqliteMigrator, migrate
from telegram import Message
from typing_extensions import TypedDict

from ehforwarderbot import utils, EFBChannel, EFBChat, EFBMsg, ChatType, coordinator, MsgType
from ehforwarderbot.types import ModuleID, ChatID, MessageID, ReactionName
from ehforwarderbot.message import EFBMsgSubstitutions, EFBMsgCommands, EFBMsgAttribute
from . import ETMChat
from .chat_object_cache import ChatObjectCacheManager
from .message import ETMMsg
from .msg_type import TGMsgType
from .utils import TelegramChatID, EFBChannelChatIDStr, TgChatMsgIDStr, message_id_to_str, \
    chat_id_to_str, OldMsgID, chat_id_str_to_id

database = SqliteDatabase(None)

PickledDict = TypedDict('PickledDict', {
    "target": EFBChannelChatIDStr,
    "is_system": bool,
    "attributes": EFBMsgAttribute,
    "commands": EFBMsgCommands,
    "substitutions": Dict[Tuple[int, int], EFBChannelChatIDStr],
    "reactions": Dict[ReactionName, Collection[EFBChannelChatIDStr]]
}, total=False)
"""
Dict entries for ``pickle`` field of ``msglog`` log.

- ``target``: ``master_msg_id`` of the target message
- ``is_system``
- ``attributes``
- ``commands``
- ``substitutions``: ``Dict[Tuple[int, int], SlaveChatID]``
- ``reactions``: ``Dict[str, Collection[SlaveChatID]]``
"""


class BaseModel(Model):
    class Meta:
        database = database


class ChatAssoc(BaseModel):
    master_uid = TextField()
    slave_uid = TextField()


class MsgLog(BaseModel):
    master_msg_id = TextField(unique=True, primary_key=True)
    """Message ID from Telegram."""
    master_msg_id_alt = TextField(null=True)
    """Editable message ID from Telegram if ``master_msg_id`` is not editable
    and a separate one is sent.
    """
    slave_message_id = TextField()
    """Message from slave channel."""
    text = TextField()
    """Text in the message."""
    slave_origin_uid = TextField()
    """Channel + chat ID of chat the message is sent to."""
    slave_origin_display_name = TextField(null=True)
    """Deprecated."""
    slave_member_uid = TextField(null=True)
    """Module + chat ID of the user that sent the message in slave channel.
    Can be ``blueset.telegram __self__``."""
    slave_member_display_name = TextField(null=True)
    """Deprecated."""
    media_type = TextField(null=True)
    """Message type in Telegram."""
    mime = TextField(null=True)
    """MIME type of attachment."""
    file_id = TextField(null=True)
    """File ID of attachment in Telegram."""
    msg_type = TextField()
    """Message type in EFB framework."""
    pickle = BlobField(null=True)
    """Miscellaneous data serialized with ``pickle``, per spec in
    ``DatabaseManager.pickle_misc_msg()``.
    """
    sent_to = TextField()
    """Module ID of the message sent to."""
    time = DateTimeField(default=datetime.datetime.now, null=True)
    """Time of the message sent."""

    def build_etm_msg(self, chat_manager: ChatObjectCacheManager,
                      recur: bool = True) -> ETMMsg:
        msg = ETMMsg()
        c_module, c_id, _ = chat_id_str_to_id(self.slave_origin_uid)
        a_module, a_id, a_grp = chat_id_str_to_id(self.slave_member_uid)
        msg.uid = self.slave_message_id
        msg.chat = chat_manager.get_chat(c_module, c_id, build_dummy=True)
        if a_module == c_module and a_id == c_id:
            msg.author = msg.chat
        elif msg.chat and msg.chat.chat_type == ChatType.Group:
            msg.author = chat_manager.get_chat(a_module, a_id, c_id, build_dummy=True)
        else:
            msg.author = chat_manager.get_chat(a_module, a_id, a_grp, build_dummy=True)
        msg.text = self.text
        try:
            to_module = coordinator.get_module_by_id(self.sent_to)
            if isinstance(to_module, EFBChannel):
                msg.deliver_to = to_module
        except NameError:
            pass
        msg.type = MsgType(self.msg_type)
        msg.type_telegram = TGMsgType(self.media_type)
        msg.mime = self.mime or None
        msg.file_id = self.file_id or None

        """
        - ``target``: ``master_msg_id`` of the target message
        - ``is_system``
        - ``attributes``
        - ``commands``
        - ``substitutions``: ``Dict[Tuple[int, int], SlaveChatID]``
        - ``reactions``: ``Dict[str, Collection[SlaveChatID]]``
        """
        if self.pickle:
            misc_data: PickledDict = pickle.loads(self.pickle)

            if 'target' in misc_data and recur:
                target_row = self.get_or_none(MsgLog.master_msg_id == misc_data['target'])
                if target_row:
                    msg.target = target_row.build_etm_msg(chat_manager, recur=False)
            if 'is_system' in misc_data:
                msg.is_system = misc_data['is_system']
            if 'attributes' in misc_data:
                msg.attributes = misc_data['attributes']
            if 'commands' in misc_data:
                msg.commands = misc_data['commands']
            if 'substitutions' in misc_data:
                msg.substitutions = EFBMsgSubstitutions({
                    k: chat_manager.get_chat(*chat_id_str_to_id(v), build_dummy=True)
                    for k, v in misc_data['substitutions'].items()
                })
            if 'reactions' in misc_data:
                msg.reactions = {
                    k: [chat_manager.get_chat(*chat_id_str_to_id(i), build_dummy=True)
                        for i in v]
                    for k, v in misc_data['reactions'].items()
                }

        return msg


class SlaveChatInfo(BaseModel):
    slave_channel_id = TextField()
    slave_channel_emoji = CharField()
    slave_chat_uid = TextField()
    slave_chat_group_id = TextField(null=True)
    slave_chat_name = TextField()
    slave_chat_alias = TextField(null=True)
    slave_chat_type = CharField()
    pickle = BlobField(null=True)


class DatabaseManager:
    logger = logging.getLogger(__name__)
    FAIL_FLAG = '__fail__'

    def __init__(self, channel: EFBChannel):
        base_path = utils.get_data_path(channel.channel_id)

        database.init(str(base_path / 'tgdata.db'))
        database.connect()

        self.task_queue: 'Queue[Optional[Tuple[Callable, Sequence[Any], Dict[str, Any]]]]' = Queue()
        self.worker_thread = Thread(target=self.task_worker, name="ETM database worker thread")
        self.worker_thread.start()

        if not ChatAssoc.table_exists():
            self._create()
        else:
            msg_log_columns = {i.name for i in database.get_columns("msglog")}
            slave_chat_info_columns = {i.name for i in database.get_columns("slavechatinfo")}
            if "file_id" not in msg_log_columns:
                self._migrate(0)
            elif "pickle" not in msg_log_columns:
                self._migrate(1)
            elif "slave_chat_group_id" not in slave_chat_info_columns:
                self._migrate(2)

    def task_worker(self):
        while True:
            task = self.task_queue.get()
            if task is None:
                self.task_queue.task_done()
                break
            method, args, kwargs = task
            try:
                method(*args, **kwargs)
            except OperationalError as e:
                self.logger.exception("Operational error occurred when running %s(%s, %s): %r", method.__name__, args, kwargs, e)
            self.task_queue.task_done()

    def stop_worker(self):
        self.task_queue.put(None)
        self.worker_thread.join()

    def add_task(self, method: Callable, args: Sequence[Any], kwargs: Dict[str, Any]):
        self.task_queue.put((method, args, kwargs))

    @staticmethod
    def _create():
        """
        Initializing tables.
        """
        database.execute_sql("PRAGMA journal_mode = OFF")
        database.create_tables([ChatAssoc, MsgLog, SlaveChatInfo])

    @staticmethod
    def _migrate(i: int):
        """
        Run migrations.

        Args:
            i: Migration ID
        """
        migrator = SqliteMigrator(database)

        if i <= 0:
            # Migration 0: Add media file ID and editable message ID
            # 2019JAN08
            migrate(
                migrator.add_column("msglog", "file_id", MsgLog.file_id),
                migrator.add_column("msglog", "media_type", MsgLog.media_type),
                migrator.add_column("msglog", "mime", MsgLog.mime),
                migrator.add_column("msglog", "master_msg_id_alt", MsgLog.master_msg_id_alt)
            )
        if i <= 1:
            # Migration 1: Add pickle objects to MsgLog and SlaveChatInfo
            # 2019JUL24
            migrate(
                migrator.add_column("msglog", "pickle", MsgLog.pickle),
                migrator.add_column("slavechatinfo", "pickle", SlaveChatInfo.pickle)
            )
        if i <= 2:
            # Migration 2: Add column for group ID to slave chat info table
            # 2019NOV18
            migrate(
                migrator.add_column("slavechatinfo", "slave_chat_group_id", SlaveChatInfo.slave_chat_group_id)
            )

    def add_chat_assoc(self, master_uid: EFBChannelChatIDStr,
                       slave_uid: EFBChannelChatIDStr,
                       multiple_slave: bool = False):
        """
        Add chat associations (chat links).
        One Master channel with many Slave channel.

        Args:
            master_uid (str): Master chat UID ("%(chat_id)s")
            slave_uid (str): Slave channel UID ("%(channel_id)s.%(chat_id)s")
            multiple_slave: Allow linking to multiple slave channels.
        """
        if not multiple_slave:
            self.remove_chat_assoc(master_uid=master_uid)
        self.remove_chat_assoc(slave_uid=slave_uid)
        return ChatAssoc.create(master_uid=master_uid, slave_uid=slave_uid)

    @staticmethod
    def remove_chat_assoc(master_uid: Optional[EFBChannelChatIDStr] = None,
                          slave_uid: Optional[EFBChannelChatIDStr] = None):
        """
        Remove chat associations (chat links).
        Only one parameter is to be provided.

        Args:
            master_uid (str): Master chat UID ("%(chat_id)s")
            slave_uid (str): Slave channel UID ("%(channel_id)s.%(chat_id)s")
        """
        try:
            if bool(master_uid) == bool(slave_uid):
                raise ValueError("Only one parameter is to be provided.")
            elif master_uid:
                return ChatAssoc.delete().where(ChatAssoc.master_uid == master_uid).execute()
            elif slave_uid:
                return ChatAssoc.delete().where(ChatAssoc.slave_uid == slave_uid).execute()
        except DoesNotExist:
            return 0

    @staticmethod
    def get_master_msg_id(message: EFBMsg) -> Optional[EFBChannelChatIDStr]:
        """Get master message ID from a message object."""
        log: Optional[MsgLog] = MsgLog.get_or_none(
            MsgLog.slave_origin_uid == chat_id_to_str(chat=message.chat),
            MsgLog.slave_message_id == message.uid
        )
        if log:
            return log.master_msg_id
        return None

    def pickle_misc_msg(self, message: EFBMsg) -> Optional[bytes]:
        """Pickle miscellaneous information of a message.

        Since 2.0.0b34, this would be a dict that reflects the following
        attributes of an ``EFBMsg``/``ETMMsg`` object.

        - ``target``: ``master_msg_id`` of the target message
        - ``is_system``
        - ``attributes``
        - ``commands``
        - ``substitutions``: ``Dict[Tuple[int, int], SlaveChatID]``
        - ``reactions``: ``Dict[str, Collection[SlaveChatID]]``
        """

        data: PickledDict = {}
        if message.is_system:
            data['is_system'] = message.is_system
        if message.attributes:
            data['attributes'] = message.attributes
        if message.commands:
            data['commands'] = message.commands
        if message.substitutions:
            data['substitutions'] = {
                k: chat_id_to_str(chat=v)
                for k, v in message.substitutions.items()
            }
        if message.reactions:
            data['reactions'] = {
                k: tuple(chat_id_to_str(chat=i) for i in v)
                for k, v in message.reactions.items()
            }
        if message.target:
            target_id = self.get_master_msg_id(message.target)
            if target_id:
                data['target'] = target_id

        if data:
            return pickle.dumps(data)
        return None

    @staticmethod
    def get_chat_assoc(master_uid: Optional[EFBChannelChatIDStr] = None,
                       slave_uid: Optional[EFBChannelChatIDStr] = None
                       ) -> List[EFBChannelChatIDStr]:
        """
        Get chat association (chat link) information.
        Only one parameter is to be provided.

        Args:
            master_uid (str): Master channel UID ("%(chat_id)s")
            slave_uid (str): Slave channel UID ("%(channel_id)s.%(chat_id)s")

        Returns:
            list: The counterpart ID.
        """
        try:
            if bool(master_uid) == bool(slave_uid):
                raise ValueError("Only one parameter is to be provided.")
            elif master_uid:
                slaves = ChatAssoc.select().where(ChatAssoc.master_uid == master_uid)
                if len(slaves) > 0:
                    return [i.slave_uid for i in slaves]
                else:
                    return []
            elif slave_uid:
                masters = ChatAssoc.select().where(ChatAssoc.slave_uid == slave_uid)
                if len(masters) > 0:
                    return [i.master_uid for i in masters]
                else:
                    return []
            else:
                return []
        except DoesNotExist:
            return []

    def add_or_update_message_log(self,
                                  msg: ETMMsg,
                                  master_message: Message,
                                  old_message_id: Optional[OldMsgID] = None):
        """Add or update a message into the database."""
        master_msg_id = message_id_to_str(master_message.chat_id, master_message.message_id)
        master_msg_id_alt = None

        if old_message_id is not None:
            old_message_id_str = message_id_to_str(*old_message_id)
            if master_msg_id != old_message_id_str:
                master_msg_id, master_msg_id_alt = old_message_id_str, master_msg_id

        row: MsgLog
        r = MsgLog.get_or_none(MsgLog.master_msg_id == master_msg_id)
        if r is not None:
            row = r
            save = row.save
        else:
            row = MsgLog()
            save = partial(row.save, force_insert=True)

        row.master_msg_id = master_msg_id
        row.master_msg_id_alt = master_msg_id_alt
        row.text = msg.text
        row.slave_origin_uid = chat_id_to_str(chat=msg.chat)
        row.slave_member_uid = chat_id_to_str(chat=msg.author)
        row.msg_type = msg.type.name
        row.sent_to = msg.deliver_to.channel_id
        row.slave_message_id = msg.uid or f"{self.FAIL_FLAG}.{time.time()}"
        row.media_type = msg.type_telegram.value
        row.file_id = msg.file_id
        row.mime = msg.mime
        pickle_data = self.pickle_misc_msg(msg)
        if pickle_data:
            row.pickle = pickle_data

        save()

    @staticmethod
    def get_msg_log(master_msg_id: Optional[TgChatMsgIDStr] = None,
                    slave_msg_id: Optional[MessageID] = None,
                    slave_origin_uid: Optional[EFBChannelChatIDStr] = None) -> Optional[MsgLog]:
        """Get message log by message ID.

        Args:
            master_msg_id: Telegram message ID in string
            slave_msg_id: Slave message identifier in string
            slave_origin_uid: Slave chat identifier in string

        Returns:
            Optional[MsgLog]: The queried entry, None if not exist.
        """
        if (master_msg_id and (slave_msg_id or slave_origin_uid)) \
                or not (master_msg_id or (slave_msg_id or slave_origin_uid)):
            raise ValueError('master_msg_id and slave_msg_id is mutual exclusive')
        if not master_msg_id and not (slave_msg_id and slave_origin_uid):
            raise ValueError('slave_msg_id and slave_origin_uid must exists together.')
        try:
            if master_msg_id:
                return MsgLog.select().where(MsgLog.master_msg_id == master_msg_id) \
                    .order_by(MsgLog.time.desc()).first()
            else:
                return MsgLog.select().where((MsgLog.slave_message_id == slave_msg_id) &
                                             (MsgLog.slave_origin_uid == slave_origin_uid)
                                             ).order_by(MsgLog.time.desc()).first()
        except DoesNotExist:
            return None

    @staticmethod
    def delete_msg_log(master_msg_id: Optional[TgChatMsgIDStr] = None,
                       slave_msg_id: Optional[EFBChannelChatIDStr] = None,
                       slave_origin_uid: Optional[EFBChannelChatIDStr] = None):
        """Remove a message log by message ID.

        Args:
            master_msg_id: Telegram message ID in string
            slave_msg_id: Slave message identifier in string
            slave_origin_uid: Slave chat identifier in string
        """
        if (master_msg_id and (slave_msg_id or slave_origin_uid)) \
                or not (master_msg_id or (slave_msg_id or slave_origin_uid)):
            raise ValueError('master_msg_id and slave_msg_id is mutual exclusive')
        if not master_msg_id and not (slave_msg_id and slave_origin_uid):
            raise ValueError('slave_msg_id and slave_origin_uid must exists together.')
        try:
            if master_msg_id:
                MsgLog.delete().where(MsgLog.master_msg_id == master_msg_id).execute()
            else:
                MsgLog.delete().where((MsgLog.slave_message_id == slave_msg_id) &
                                      (MsgLog.slave_origin_uid == slave_origin_uid)
                                      ).execute()
        except DoesNotExist:
            return

    @staticmethod
    def get_slave_chat_info(slave_channel_id: Optional[ModuleID] = None,
                            slave_chat_uid: Optional[ChatID] = None,
                            slave_chat_group_id: Optional[ChatID] = None
                            ) -> Optional[SlaveChatInfo]:
        """
        Get cached slave chat info from database.

        Returns:
            SlaveChatInfo|None: The matching slave chat info, None if not exist.
        """
        if slave_channel_id is None or slave_chat_uid is None:
            raise ValueError("Both slave_channel_id and slave_chat_id should be provided.")
        try:
            return SlaveChatInfo.select() \
                .where((SlaveChatInfo.slave_channel_id == slave_channel_id) &
                       (SlaveChatInfo.slave_chat_uid == slave_chat_uid) &
                       (SlaveChatInfo.slave_chat_group_id == slave_chat_group_id)).first()
        except DoesNotExist:
            return None

    def set_slave_chat_info(self, chat_object: EFBChat) -> SlaveChatInfo:
        """
        Insert or update slave chat info entry

        Args:
            chat_object (EFBChat): Chat object for pickling

        Returns:
            SlaveChatInfo: The inserted or updated row
        """
        slave_channel_id = chat_object.module_id
        slave_channel_name = chat_object.module_name
        slave_channel_emoji = chat_object.channel_emoji
        slave_chat_uid = chat_object.chat_uid
        slave_chat_name = chat_object.chat_name
        slave_chat_alias = chat_object.chat_alias
        slave_chat_type = chat_object.chat_type.value
        if chat_object.group is None:
            slave_chat_group_id = None
        else:
            slave_chat_group_id = chat_object.group.chat_uid

        chat_info = self.get_slave_chat_info(slave_channel_id=slave_channel_id,
                                             slave_chat_uid=slave_chat_uid,
                                             slave_chat_group_id=slave_chat_group_id)
        if chat_info is not None:
            chat_info.slave_channel_name = slave_channel_name
            chat_info.slave_channel_emoji = slave_channel_emoji
            chat_info.slave_chat_name = slave_chat_name
            chat_info.slave_chat_alias = slave_chat_alias
            if slave_chat_type is not None:
                chat_info.slave_chat_type = slave_chat_type
            if chat_object is not None:
                if not isinstance(chat_object, ETMChat):
                    chat_object = ETMChat(db=self, chat=chat_object)
                chat_info.pickle = chat_object.pickle
            chat_info.save()
            return chat_info
        else:
            return SlaveChatInfo.create(slave_channel_id=slave_channel_id,
                                        slave_channel_name=slave_channel_name,
                                        slave_channel_emoji=slave_channel_emoji,
                                        slave_chat_uid=slave_chat_uid,
                                        slave_chat_group_id=slave_chat_group_id,
                                        slave_chat_name=slave_chat_name,
                                        slave_chat_alias=slave_chat_alias,
                                        slave_chat_type=slave_chat_type,
                                        pickle=pickle.dumps(chat_object))

    @staticmethod
    def delete_slave_chat_info(slave_channel_id: ModuleID, slave_chat_uid: ChatID, slave_chat_group_id: ChatID = None):
        return SlaveChatInfo.delete() \
            .where((SlaveChatInfo.slave_channel_id == slave_channel_id) &
                   (SlaveChatInfo.slave_chat_uid == slave_chat_uid) &
                   (SlaveChatInfo.slave_chat_group_id == slave_chat_group_id)).execute()

    @staticmethod
    def get_recent_slave_chats(master_chat_id: TelegramChatID, limit=5) -> List[EFBChannelChatIDStr]:
        query = MsgLog \
            .select(MsgLog.slave_origin_uid, fn.MAX(MsgLog.time)) \
            .where(MsgLog.master_msg_id.startswith("{}.".format(master_chat_id))) \
            .group_by(MsgLog.slave_origin_uid) \
            .order_by(fn.MAX(MsgLog.time).desc()) \
            .limit(limit)

        return [EFBChannelChatIDStr(i.slave_origin_uid) for i in query]

    @staticmethod
    def get_last_message(slave_chat_id: EFBChannelChatIDStr) -> Optional[MsgLog]:
        try:
            return MsgLog.select().where(
                MsgLog.slave_origin_uid == slave_chat_id
            ).order_by(MsgLog.time.desc()).limit(1).first()
        except DoesNotExist:
            return None
