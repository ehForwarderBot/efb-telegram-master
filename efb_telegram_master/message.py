import mimetypes
import os
import subprocess
import tempfile
import logging
from typing import Optional, TYPE_CHECKING

import magic
import telegram
from PIL import Image
from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram.error import BadRequest
from typing.io import IO

from ehforwarderbot import EFBMsg, coordinator, MsgType
from . import utils
from .chat_object_cache import ChatObjectCacheManager
from .chat import ETMChat
from .msg_type import TGMsgType, get_msg_type

if TYPE_CHECKING:
    pass

logger = logging.Logger(__name__)

__all__ = ['ETMMsg']


class ETMMsg(EFBMsg):
    file_id: Optional[str] = None
    """File ID from Telegram Bot API"""
    type_telegram: TGMsgType
    """Type of message in Telegram Bot API"""
    chat: ETMChat
    author: ETMChat

    __file = None
    __path = None
    __filename = None

    def __init__(self):
        super().__init__()
        self.__initialized = False

    def _load_file(self):
        if self.file_id:
            # noinspection PyUnresolvedReferences
            bot = coordinator.master.bot_manager

            try:
                file_meta = bot.get_file(self.file_id)
            except BadRequest as e:
                logger.exception("Bad request while trying to get file metadata: %s", e)
                return
            if not self.mime:
                ext = os.path.splitext(file_meta.file_path)[1]
                mime = mimetypes.guess_type(file_meta.file_path, strict=False)[0]
            else:
                ext = mimetypes.guess_extension(self.mime, strict=False)
                mime = self.mime
            file = tempfile.NamedTemporaryFile(suffix=ext)
            full_path = file.name
            file_meta.download(out=file)
            file.seek(0)
            mime = mime or magic.from_file(full_path, mime=True)
            if type(mime) is bytes:
                mime = mime.decode()
            self.mime = mime

            self.__file = file
            self.__path = file.name
            self.__filename = self.__filename or os.path.basename(file.name)

            if self.type_telegram == TGMsgType.Animation:
                channel_id = self.deliver_to.channel_id

                gif_file = tempfile.NamedTemporaryFile(suffix='.gif')
                v = VideoFileClip(file.name)
                if channel_id == "blueset.wechat" and v.size[0] > 600:
                    # Workaround: Compress GIF for slave channel `blueset.wechat`
                    # TODO: Move this logic to `blueset.wechat` in the future
                    subprocess.Popen(
                        ["ffmpeg", "-y", "-i", file.name, '-vf', "scale=600:-2", gif_file.name],
                        bufsize=0
                    ).wait()
                else:
                    v.write_gif(gif_file.name, program="ffmpeg")
                file.close()
                gif_file.seek(0)

                self.__file = gif_file
                self.__path = gif_file.name
                self.__filename = self.__filename or os.path.basename(gif_file.name)
                self.mime = "image/gif"
            elif self.type_telegram == TGMsgType.Sticker:
                out_file = tempfile.NamedTemporaryFile(suffix=".png")
                Image.open(file).convert("RGBA").save(out_file, 'png')
                file.close()
                out_file.seek(0)
                self.mime = "image/png"
                self.__filename = (self.__filename or os.path.basename(file.name)) + ".png"
                self.__file = out_file
                self.__path = out_file.name
            elif self.type_telegram == TGMsgType.AnimatedSticker:
                out_file = tempfile.NamedTemporaryFile(suffix=".gif")
                if utils.convert_tgs_to_gif(file, out_file):
                    file.close()
                    out_file.seek(0)
                    self.mime = "image/gif"
                    self.__filename = (self.__filename or os.path.basename(file.name)) + ".gif"
                else:
                    # Conversion failed, send file as is.
                    out_file.close()
                    file.seek(0)
                    out_file = file
                    self.mime = "application/json"
                    self.__filename = (self.__filename or os.path.basename(file.name)) + ".json"
                self.__file = out_file
                self.__path = out_file.name

        self.__initialized = True

    def get_file(self) -> Optional[IO[bytes]]:
        if not self.__initialized:
            self._load_file()
        return self.__file

    def set_file(self, value: Optional[IO[bytes]]):
        # Stop initialization-on-demand as new file info is written
        # This is added for compatibility with middleware behaviors
        self.__initialized = True
        self.__file = value

    def get_path(self) -> Optional[str]:
        if not self.__initialized:
            self._load_file()
        return self.__path

    def set_path(self, value: Optional[str]):
        # Stop initialization-on-demand as new file info is written
        # This is added for compatibility with middleware behaviors
        self.__initialized = True
        self.__path = value

    def get_filename(self) -> Optional[str]:
        if not self.__initialized:
            self._load_file()
        return self.__filename

    def set_filename(self, value: Optional[str]):
        self.__filename = value

    # Override properties
    file: Optional[IO[bytes]] = property(get_file, set_file)  # type: ignore
    path: Optional[str] = property(get_path, set_path)  # type: ignore
    filename: Optional[str] = property(get_filename, set_filename)  # type: ignore

    @staticmethod
    def from_efbmsg(source: EFBMsg, chat_manager: ChatObjectCacheManager) -> 'ETMMsg':
        target = ETMMsg()
        target.__dict__.update(source.__dict__)
        if not isinstance(target.chat, ETMChat):
            target.chat = chat_manager.update_chat_obj(target.chat)
        if not isinstance(target.author, ETMChat):
            target.author = chat_manager.update_chat_obj(target.author)
        if isinstance(target.reactions, dict):
            for i in target.reactions:
                if any(not isinstance(j, ETMChat) for j in target.reactions[i]):
                    # noinspection PyTypeChecker
                    target.reactions[i] = list(map(lambda a: chat_manager.update_chat_obj(a), target.reactions[i]))
        return target

    def put_telegram_file(self, message: telegram.Message):
        # Store Telegram message type
        self.type_telegram = get_msg_type(message)

        is_common_file = False

        # Store media related information to local database
        for tg_media_type in ('animation', 'document', 'video', 'voice', 'video_note'):
            attachment = getattr(message, tg_media_type, None)
            if attachment:
                is_common_file = True
                self.file_id = attachment.file_id
                self.mime = attachment.mime_type
                break

        if not is_common_file:
            if self.type_telegram == TGMsgType.Audio:
                self.file_id = message.audio.file_id
                self.mime = message.audio.mime_type
                extension = mimetypes.guess_extension(message.audio.mime_type)
                self.filename = f"{message.audio.title} - {message.audio.performer}{extension}"
            elif self.type_telegram == TGMsgType.Sticker:
                self.file_id = message.sticker.file_id
                self.mime = 'image/webp'
            elif self.type_telegram == TGMsgType.AnimatedSticker:
                self.file_id = message.sticker.file_id
                self.mime = 'application/json+tgs'
                self.type = MsgType.Animation
            elif getattr(message, 'photo', None):
                attachment = message.photo[-1]
                self.file_id = attachment.file_id
                self.mime = 'image/jpeg'
