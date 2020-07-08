"""
Planned workflow
================
Send a message
Assert if it is send
Check if content is correct

Edit the message (if possible)
    Assert message ID is the same
    Assert edit flag and not edit_media flag
    Assert content updated
Edit the message media (if possible)
    Assert message ID is the same
    Assert edit and edit_media flag
    Assert content updated
Send another message of same kind, quoting the previous one
    Assert message is sent
    Assert message target is correct.
"""

import random
from abc import ABC, abstractmethod
from typing import Optional
from uuid import uuid4

from pytest import mark, approx, param
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.types import InputMediaGeoPoint, InputGeoPoint, InputMediaGeoLive, \
    InputMediaVenue, MessageMediaVenue, InputMediaContact, InputMediaDice, MessageMediaDice

from ehforwarderbot import Message as EFBMessage
from ehforwarderbot import MsgType
from ehforwarderbot.chat import SelfChatMember
from ehforwarderbot.message import LocationAttribute
from .utils import link_chats

pytestmark = mark.asyncio

# region Message factory classes


class MessageFactory(ABC):
    """Interface of factory to generate messages."""

    test_quote = True

    @abstractmethod
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        """Build an initial message to send with."""

    @abstractmethod
    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        """Compare if the Telegram message matches with what is processed by ETM.

        This method should raises ``AssertionError`` if a mismatch is found.
        Otherwise this shall return nothing (i.e. ``None``).
        """

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        """Issue an edit of the message if applicable.

        Returns the edited message, or none if no edit is needed."""
        return

    async def edit_message_media(self, client: TelegramClient, message: Message) -> Optional[Message]:
        """Issue a media edit of the message if applicable.

        Returns the edited message, or none if no edit is needed."""
        return

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        """Finalize the message before discarding if needed."""
        pass

    def __str__(self):
        return self.__class__.__name__


class TextMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            f"守ったものは、明るい未来幻想を見せながら消えてゆくヒカリ。\n"
            f"new message {uuid4()}, target: {target and target.id}",
            reply_to=target
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Text
        assert tg_msg.text == efb_msg.text

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(
            text=f"信じたものは、都合のいい妄想を繰り返し映し出す鏡。\n"
                 f"edited message {uuid4()}",
        )


class LocationMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            file=InputMediaGeoPoint(InputGeoPoint(0.0, 0.0)),
            reply_to=target
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Location
        assert isinstance(efb_msg.attributes, LocationAttribute)
        assert tg_msg.geo.lat == approx(efb_msg.attributes.latitude, abs=1e-3)
        assert tg_msg.geo.long == approx(efb_msg.attributes.longitude, abs=1e-3)


class LiveLocationMessageFactory(MessageFactory):

    test_quote = False

    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            file=InputMediaGeoLive(
                InputGeoPoint(random.uniform(0.0, 90.0), random.uniform(0.0, 90.0)), stopped=False, period=3600),
            reply_to=target
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Location
        assert isinstance(efb_msg.attributes, LocationAttribute)
        assert tg_msg.geo.lat == approx(efb_msg.attributes.latitude, abs=1e-3)
        assert tg_msg.geo.long == approx(efb_msg.attributes.longitude, abs=1e-3)

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(
            file=InputMediaGeoLive(
                InputGeoPoint(-random.uniform(0.0, 90.0), -random.uniform(0.0, 90.0)),
                stopped=True)
        )

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        """Only stop live location from the second message is to be closed."""
        if tg_msg.reply_to_msg_id:
            await self.edit_message(tg_msg.client, tg_msg)


class VenueMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            file=InputMediaVenue(InputGeoPoint(0.0, 0.0),
                                 "Location name", f"Address {uuid4()}", "", "", ""),
            reply_to=target
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Location
        assert isinstance(efb_msg.attributes, LocationAttribute)
        assert tg_msg.geo.lat == approx(efb_msg.attributes.latitude, abs=1e-3)
        assert tg_msg.geo.long == approx(efb_msg.attributes.longitude, abs=1e-3)
        assert isinstance(tg_msg.media, MessageMediaVenue)
        assert tg_msg.media.title in efb_msg.text
        assert tg_msg.media.address in efb_msg.text


class ContactMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            file=InputMediaContact("+424 3 14159", "Bot", "Support", ""),
            reply_to=target
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Text
        assert tg_msg.contact
        assert tg_msg.contact.phone_number in efb_msg.text
        assert tg_msg.contact.first_name in efb_msg.text
        assert tg_msg.contact.last_name in efb_msg.text


class StickerMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            file="tests/mocks/sticker.webp",
            reply_to=target
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Sticker
        assert efb_msg.file
        assert efb_msg.file.seek(0, 2)
        # Cannot compare file size as WebP pictures are converted to PNG here.

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class DocumentMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            f"Document caption {uuid4()}",
            file="tests/mocks/document_0.txt.gz",
            reply_to=target
        )

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(text=f"Edited document caption {uuid4()}")

    async def edit_message_media(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(
            text=f"Edited document file & caption {uuid4()}",
            file="tests/mocks/document_1.txt.gz"
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.File
        assert tg_msg.raw_text == efb_msg.text
        assert efb_msg.file
        file_size = efb_msg.file.seek(0, 2)
        assert file_size == tg_msg.file.size
        assert tg_msg.file.name == efb_msg.filename
        assert tg_msg.file.mime_type == efb_msg.mime

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class PhotoMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            f"Photo caption {uuid4()}",
            file="tests/mocks/image.png",
            reply_to=target
        )

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(text=f"Edited image caption {uuid4()}")

    async def edit_message_media(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(
            text=f"Edited image file & caption {uuid4()}",
            file="tests/mocks/image_1.png"
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Image
        assert tg_msg.raw_text == efb_msg.text
        assert efb_msg.file
        file_size = efb_msg.file.seek(0, 2)
        assert file_size == tg_msg.file.size

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class VoiceMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_file(
            chat_id,
            caption=f"Voice caption {uuid4()}",
            file="tests/mocks/voice_0.ogg",
            voice_note=True,
            reply_to=target
        )

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(text=f"Edited voice caption {uuid4()}")

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Voice
        assert tg_msg.text == efb_msg.text
        assert efb_msg.file
        file_size = efb_msg.file.seek(0, 2)
        assert file_size == tg_msg.file.size

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class AudioMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            f"Audio caption {uuid4()}",
            file="tests/mocks/audio_0.mp3",
            reply_to=target
        )

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(text=f"Edited audio caption {uuid4()}")

    async def edit_message_media(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(
            text=f"Edited audio file & caption {uuid4()}",
            file="tests/mocks/audio_1.mp3"
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.File
        assert tg_msg.raw_text in efb_msg.text
        assert efb_msg.file
        file_size = efb_msg.file.seek(0, 2)
        assert file_size == tg_msg.file.size
        assert efb_msg.filename.endswith(".mp3")
        assert tg_msg.file.performer in efb_msg.text
        assert tg_msg.file.title in efb_msg.text

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class VideoMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            f"Video caption {uuid4()}",
            file="tests/mocks/video_0.mp4",
            reply_to=target
        )

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(text=f"Edited video caption {uuid4()}")

    async def edit_message_media(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(
            text=f"Edited video file & caption {uuid4()}",
            file="tests/mocks/video_1.mp4"
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Video
        assert tg_msg.raw_text == efb_msg.text
        assert efb_msg.file
        file_size = efb_msg.file.seek(0, 2)
        assert file_size == tg_msg.file.size
        assert efb_msg.filename.endswith(".mp4")

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class VideoNoteMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_file(
            chat_id,
            file="tests/mocks/video_note_0.mp4",
            video_note=True,
            reply_to=target
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Video
        assert efb_msg.file
        file_size = efb_msg.file.seek(0, 2)
        assert file_size == tg_msg.file.size

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class AnimationMessageFactory(MessageFactory):
    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            f"Animation caption {uuid4()}",
            file="tests/mocks/animation_0.gif",
            reply_to=target
        )

    async def edit_message(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(text=f"Edited animation caption {uuid4()}")

    async def edit_message_media(self, client: TelegramClient, message: Message) -> Optional[Message]:
        return await message.edit(
            text=f"Edited animation file & caption {uuid4()}",
            file="tests/mocks/animation_1.gif"
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Animation
        assert tg_msg.raw_text == efb_msg.text
        assert efb_msg.file
        assert efb_msg.file.seek(0, 2)
        # Cannot compare file size due to format conversion
        assert efb_msg.filename.endswith(".gif")

    async def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class DiceMessageFactory(MessageFactory):
    def __init__(self, emoji: str):
        self.emoji = emoji

    async def send_message(self, client: TelegramClient, chat_id: int, target: Message = None) -> Message:
        return await client.send_message(
            chat_id,
            f"Dice caption {uuid4()}",
            file=InputMediaDice(self.emoji),
            reply_to=target
        )

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.type == MsgType.Text
        media = tg_msg.media
        assert isinstance(media, MessageMediaDice)
        assert str(media.emoticon) in efb_msg.text
        assert str(media.value) in efb_msg.text

    def __str__(self):
        return f"DiceMessageFactory({self.emoji})"


# endregion Message factory classes


@mark.parametrize("factory", [
    TextMessageFactory(), LocationMessageFactory(),
    LiveLocationMessageFactory(), ContactMessageFactory(),
    StickerMessageFactory(),
    DocumentMessageFactory(),
    PhotoMessageFactory(),
    VoiceMessageFactory(),
    AudioMessageFactory(),
    VideoMessageFactory(),
    VideoNoteMessageFactory(),
    AnimationMessageFactory(),
    DiceMessageFactory("🎲"),
    DiceMessageFactory("🎯"),
    DiceMessageFactory("🏀"),
], ids=str)
async def test_master_message(helper, client, bot_group, slave, channel, factory: MessageFactory):
    chat = slave.chat_without_alias

    with link_chats(channel, (chat, ), bot_group):
        # Send message
        tg_msg = await factory.send_message(client, bot_group)
        efb_msg = slave.messages.get(timeout=5)
        assert efb_msg.chat == chat
        assert isinstance(efb_msg.author, SelfChatMember)
        assert efb_msg.deliver_to is slave
        assert not efb_msg.edit
        assert not efb_msg.edit_media
        factory.compare_message(tg_msg, efb_msg)
        await factory.finalize_message(tg_msg, efb_msg)

        # Edit message
        edited_msg = await factory.edit_message(client, tg_msg)
        if edited_msg is not None:
            efb_msg = slave.messages.get(timeout=5)
            assert efb_msg.chat == chat
            assert isinstance(efb_msg.author, SelfChatMember)
            assert efb_msg.deliver_to is slave
            assert efb_msg.edit
            assert not efb_msg.edit_media
            factory.compare_message(edited_msg, efb_msg)
            await factory.finalize_message(edited_msg, efb_msg)

        # Edit media
        media_edited = await factory.edit_message_media(client, tg_msg)
        if media_edited is not None:
            efb_msg = slave.messages.get(timeout=5)
            assert efb_msg.chat == chat
            assert isinstance(efb_msg.author, SelfChatMember)
            assert efb_msg.deliver_to is slave
            assert efb_msg.edit
            assert efb_msg.edit_media
            factory.compare_message(media_edited, efb_msg)
            await factory.finalize_message(media_edited, efb_msg)

        # Quote reply
        if factory.test_quote:
            quoted_message = await factory.send_message(client, bot_group, target=tg_msg)
            quoted_efb_msg = slave.messages.get(timeout=5)
            assert quoted_efb_msg.chat == chat
            assert isinstance(quoted_efb_msg.author, SelfChatMember)
            assert quoted_efb_msg.deliver_to is slave
            assert not quoted_efb_msg.edit
            assert not quoted_efb_msg.edit_media
            assert quoted_efb_msg.target.uid == efb_msg.uid
            await factory.finalize_message(quoted_message, quoted_efb_msg)
