import html
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Dict, List, IO, TYPE_CHECKING

import requests
import pydub
import base64
import uuid
import tempfile

from ehforwarderbot import MsgType
import telegram.ext

if TYPE_CHECKING:
    from . import TelegramChannel
    from .bot_manager import TelegramBotManager


class VoiceRecognitionManager:
    """
    Methods related to voice recognition function of ETM.
    """

    voice_engines = []

    def __init__(self, channel: 'TelegramChannel'):
        """
        Load voice recognition engine objects with tokens into ``self.voice_engines``.

        Override this method with ``super`` to support other engines.

        Args:
             channel: The channel.
        """
        self.channel: 'TelegramChannel' = channel
        self.bot_manager: 'TelegramBotManager' = self.channel.bot_manager

        self.bot_manager.dispatcher.add_handler(
            telegram.ext.CommandHandler("recog", self.recognize_speech, pass_args=True))

        tokens: Dict[str, Any] = self.channel.config.get("speech_api", dict())
        self.voice_engines = []
        if "bing" in tokens:
            self.voice_engines.append(BingSpeech(tokens['bing']))
        if "baidu" in tokens:
            self.voice_engines.append(BaiduSpeech(tokens['baidu']))

    def recognize_speech(self, bot, update, args=[]):
        """
        Recognise voice message. Triggered by `/recog`.

        Args:
            bot: Telegram Bot instance
            update: Message update
            args: Arguments from message
        """

        if not getattr(update.message, "reply_to_message", None):
            text = "/recog lang_code\n" \
                   "Reply to a voice with this command to recognize it.\n" \
                   "examples:\n/recog zh\n/recog en-US\n\nSupported languages:\n"
            text += "\n".join("%s: %r" % (i.engine_name, i.lang_list) for i in self.voice_engines)
            return self._reply_error(bot, update, text)
        if not getattr(update.message.reply_to_message, "voice"):
            return self._reply_error(bot, update,
                                     "Reply only to a voice with this command to recognize it. (RS02)")

        if update.message.reply_to_message.voice.duration > 60:
            return self._reply_error(bot, update, "Only voice shorter than 60s is supported. (RS04)")

        file, _, _ = self._download_file(update.message, update.message.reply_to_message.voice, MsgType.Audio)

        results = OrderedDict()
        for i in self.voice_engines:
            results["%s (%s)" % (i.engine_name, args[0])] = i.recognise(file.name, args[0])

        msg = ""
        for i in results:
            msg += "\n<b>%s</b>:\n" % html.escape(i)
            for j in results[i]:
                msg += "%s\n" % html.escape(j)
        msg = "Results:\n%s" % msg
        self.bot_send_message(update.message.reply_to_message.chat.id, msg,
                              reply_to_message_id=update.message.reply_to_message.message_id,
                              parse_mode=telegram.ParseMode.HTML)

        file.close()


class SpeechEngine(ABC):
    """Name of the speech recognition engine"""
    engine_name: str = __name__
    """List of languages codes supported"""
    lang_list: List[str] = []

    @abstractmethod
    def recognize(self, file: IO[bytes], lang: str):
        raise NotImplementedError()


class BaiduSpeech(SpeechEngine):
    key_dict = None
    access_token = None
    full_token = None
    engine_name = "Baidu"
    lang_list = ['zh', 'ct', 'en']

    def __init__(self, key_dict):
        self.key_dict = key_dict
        d = {
            "grant_type": "client_credentials",
            "client_id": key_dict['api_key'],
            "client_secret": key_dict['secret_key']
        }
        r = requests.post("https://openapi.baidu.com/oauth/2.0/token", data=d).json()
        self.access_token = r['access_token']
        self.full_token = r

    def recognize(self, file, lang):
        if hasattr(file, 'read'):
            pass
        elif isinstance(file, str):
            file = open(file, 'rb')
        else:
            return ["ERROR!", "File must by a path string or a file object in `rb` mode."]
        if lang.lower() not in self.lang_list:
            return ["ERROR!", "Invalid language."]

        audio = pydub.AudioSegment.from_file(file)
        audio = audio.set_frame_rate(16000)
        d = {
            "format": "pcm",
            "rate": 16000,
            "channel": 1,
            "cuid": "testing_user",
            "token": self.access_token,
            "lan": lang,
            "len": len(audio.raw_data),
            "speech": base64.b64encode(audio.raw_data).decode()
        }
        r = requests.post("http://vop.baidu.com/server_api", json=d)
        rjson = r.json()
        if rjson['err_no'] == 0:
            return rjson['result']
        else:
            return ["ERROR!", rjson['err_msg']]


class BingSpeech(SpeechEngine):
    keys = None
    access_token = None
    engine_name = "Bing"
    lang_list = ['ar-EG', 'de-DE', 'en-US', 'es-ES', 'fr-FR',
                 'it-IT', 'ja-JP', 'pt-BR', 'ru-RU', 'zh-CN']

    @staticmethod
    def first(data, key):
        """
        Look for first element in a list that matches a criteria.

        Args:
            data (list): List of elements
            key (function with one argument that returns Boolean value):
                Function to decide if an element matches the criteria.

        Returns:
            The first element found, or ``None``.
        """
        for i in data:
            if key(i):
                return i
        return None

    def __init__(self, keys):
        self.keys = keys

    def recognize(self, path, lang):
        if isinstance(path, str):
            file = open(path, 'rb')
        else:
            return ["ERROR!", "File must by a path string."]
        if lang not in self.lang_list:
            lang = self.first(self.lang_list, lambda a: a.split('-')[0] == lang.split('-')[0])
            if lang not in self.lang_list:
                return ["ERROR!", "Invalid language."]

        with tempfile.NamedTemporaryFile() as f:
            audio = pydub.AudioSegment.from_file(file)
            audio = audio.set_frame_rate(16000)
            audio.export(f.name, format="wav")
            header = {
                "Ocp-Apim-Subscription-Key": self.keys,
                "Content-Type": "audio/wav; samplerate=16000"
            }
            d = {
                "language": lang,
                "format": "detailed",
            }
            f.seek(0)
            r = requests.post("https://speech.platform.bing.com/speech/recognition/conversation/cognitiveservices/v1",
                              params=d, data=f.read(), headers=header)

            try:
                rjson = r.json()
            except ValueError:
                return ["ERROR!", r.text]

            if r.status_code == 200:
                return [i['Display'] for i in rjson['NBest']]
            else:
                return ["ERROR!", r.text]
