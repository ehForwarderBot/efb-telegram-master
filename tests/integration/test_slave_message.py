"""
Planned workflow
================
Send a message
Assert if it is send
Check if content is correct

Edit the message (if possible)
    Assert message ID is the same
    Assert content updated
Edit the message media (if possible)
    Assert message ID is the same
    Assert content updated
Send another message of same kind, quoting the previous one
    Assert message is sent
    Assert message target is correct.
"""
from abc import abstractmethod, ABC
from itertools import chain
from pathlib import Path
from typing import Optional, List, Tuple

from pytest import mark, approx
from telethon.tl.custom import Message
from telethon.tl.types import MessageEntityMentionName, MessageEntityCode

from ehforwarderbot import Chat
from ehforwarderbot import Message as EFBMessage
from ehforwarderbot.chat import SelfChatMember
from ehforwarderbot.message import LinkAttribute, LocationAttribute, MsgType
from tests.integration.helper.filters import in_chats, edited, reply_to
from tests.integration.utils import link_chats
from tests.mocks.slave import MockSlaveChannel

pytestmark = mark.asyncio


class MessageFactory(ABC):
    """Interface of factory to generate messages."""

    content_editable = True
    """If the message content is editable in Telegram."""

    media_editable = True
    """If the message media is editable in Telegram."""

    @abstractmethod
    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        """Build an initial message to send with."""

    @abstractmethod
    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        """Compare if the Telegram message matches with what is processed by ETM.

        This method should raises ``AssertionError`` if a mismatch is found.
        Otherwise this shall return nothing (i.e. ``None``).
        """

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        """Issue an edit of the message if applicable.

        Returns the edited message, or none if no edit is needed."""
        return

    def edit_message_media(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        """Issue a media edit of the message if applicable.

        Returns the edited message, or none if no edit is needed."""
        return

    def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        """Finalize the message before discarding if needed."""
        pass

    @staticmethod
    def compare_substitutions(tg_msg: Message, efb_msg: EFBMessage) -> None:
        """Compare application of substitution in message text."""
        if not efb_msg.substitutions:
            return
        self_subs: List[Tuple[MessageEntityMentionName, str]] = tg_msg.get_entities_text(cls=MessageEntityMentionName)
        other_subs: List[Tuple[MessageEntityCode, str]] = tg_msg.get_entities_text(cls=MessageEntityCode)
        for coord, chat in efb_msg.substitutions.items():
            size = coord[1] - coord[0]
            if isinstance(chat, SelfChatMember):
                assert any(ent.length == size for ent, _ in self_subs), (
                    f"string of size {size} is not found in self_subs: "
                    f"{[(x.to_dict(), y) for x, y in self_subs]}"
                )
            else:
                assert any(ent.length == size for ent, _ in other_subs), (
                    f"string of size {size} is not found in other_subs: "
                    f"{[(x.to_dict(), y) for x, y in self_subs]}"
                )

    @staticmethod
    def assert_metadata_in_buttons(tg_msg: Message, efb_msg: EFBMessage):
        """Compare metadata (text, reactions and commands) in the case
        when sent in buttons.
        """
        assert any(efb_msg.text in btn.text
                   for btn in chain.from_iterable(tg_msg.buttons))
        for r_name in efb_msg.reactions:
            assert any(r_name in btn.text
                       for btn in chain.from_iterable(tg_msg.buttons))
        if efb_msg.commands:
            assert tg_msg.button_count >= len(efb_msg.commands)

    def __str__(self):
        return self.__class__.__name__


class TextMessageFactory(MessageFactory):
    def __init__(self, unsupported=False):
        self.unsupported = unsupported

    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        return slave.send_text_message(
            chat, target=target, reactions=True, commands=True,
            substitution=True, unsupported=self.unsupported)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.text in tg_msg.raw_text
        if self.unsupported:
            assert "unsupported" in tg_msg.raw_text.lower()
        for i in efb_msg.reactions:
            assert i in tg_msg.raw_text
        if efb_msg.commands:
            assert tg_msg.button_count == len(efb_msg.commands)
        self.compare_substitutions(tg_msg, efb_msg)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        slave.edit_text_message(message, reactions=True, commands=True, substitution=True)

    def __str__(self):
        if self.unsupported:
            return "UnsupportedMessage"
        return super().__str__()


class LinkMessageFactory(MessageFactory):

    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        return slave.send_link_message(chat, target=target, reactions=True, commands=True, substitution=True)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert efb_msg.text in tg_msg.raw_text
        for i in efb_msg.reactions:
            assert i in tg_msg.raw_text
        if efb_msg.commands:
            assert tg_msg.button_count == len(efb_msg.commands)
        assert isinstance(efb_msg.attributes, LinkAttribute)
        if efb_msg.attributes.title:
            assert efb_msg.attributes.title in tg_msg.raw_text
        if efb_msg.attributes.description:
            assert efb_msg.attributes.description in tg_msg.raw_text
        if efb_msg.attributes.image:
            assert efb_msg.attributes.image in tg_msg.text
        if efb_msg.attributes.url:
            assert efb_msg.attributes.url in tg_msg.text
        self.compare_substitutions(tg_msg, efb_msg)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_link_message(message, reactions=True, commands=True, substitution=True)


class LocationMessageFactory(MessageFactory):

    content_editable = False

    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        return slave.send_location_message(chat, target=target, reactions=True, commands=True, substitution=True)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        self.assert_metadata_in_buttons(tg_msg, efb_msg)
        assert isinstance(efb_msg.attributes, LocationAttribute)
        assert tg_msg.geo
        assert efb_msg.attributes.latitude == approx(tg_msg.geo.lat, abs=1e-3)
        assert efb_msg.attributes.longitude == approx(tg_msg.geo.long, abs=1e-3)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_location_message(message, reactions=True, commands=True, substitution=True)


class ImageMessageFactory(MessageFactory):
    def __init__(self, large: bool = False):
        """
        Args:
            large: If the picture to be sent is large in dimension.
        """
        self.large = large

    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        if self.large:
            path = Path("tests/mocks/large_image_0.png")
        else:
            path = Path("tests/mocks/image.png")
        return slave.send_file_like_message(
            MsgType.Image, path, "image/png",
            chat, target=target, reactions=True, commands=True, substitution=True)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        if self.large:
            assert tg_msg.file
            assert tg_msg.file.name == efb_msg.filename
            size = efb_msg.path.stat().st_size
            assert tg_msg.file.size == size
        else:
            assert tg_msg.photo
            # Cannot do further assertion here as Telegram has compressed the
            # pictures sent out
        assert efb_msg.text in tg_msg.raw_text
        for i in efb_msg.reactions:
            assert i in tg_msg.raw_text
        if efb_msg.commands:
            assert tg_msg.button_count == len(efb_msg.commands)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message_text(
            message, reactions=True, commands=True, substitution=True)

    def edit_message_media(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        if self.large:
            path = Path("tests/mocks/large_image_1.png")
        else:
            path = Path("tests/mocks/image_1.png")
        return slave.edit_file_like_message(
            message, path, mime="image/png",
            reactions=True, commands=True, substitution=True)

    def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()

    def __str__(self):
        return f"{self.__class__.__name__}(large={self.large})"


class StickerMessageFactory(MessageFactory):

    media_editable = False

    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        return slave.send_file_like_message(
            MsgType.Sticker, Path("tests/mocks/sticker_0.png"), "image/png",
            chat, target=target, reactions=True, commands=True, substitution=True)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert tg_msg.sticker is not None
        # Cannot do further assertion here as Telegram has converted the
        # pictures sent out
        self.assert_metadata_in_buttons(tg_msg, efb_msg)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message_text(
            message, reactions=True, commands=True, substitution=True)

    def edit_message_media(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message(
            message, Path("tests/mocks/sticker_1.png"), mime="image/png",
            reactions=True, commands=True, substitution=True)

    def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class FileMessageFactory(MessageFactory):
    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        return slave.send_file_like_message(
            MsgType.File, Path("tests/mocks/document_0.txt.gz"), "application/gzip",
            chat, target=target, reactions=True, commands=True, substitution=True)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert tg_msg.file
        assert tg_msg.file.name == efb_msg.filename
        size = efb_msg.path.stat().st_size
        assert tg_msg.file.size == size
        assert efb_msg.text in tg_msg.raw_text
        for i in efb_msg.reactions:
            assert i in tg_msg.raw_text
        if efb_msg.commands:
            assert tg_msg.button_count == len(efb_msg.commands)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message_text(
            message, reactions=True, commands=True, substitution=True)

    def edit_message_media(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message(
            message, Path("tests/mocks/document_1.txt.gz"), mime="application/gzip",
            reactions=True, commands=True, substitution=True)

    def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class AnimationMessageFactory(MessageFactory):

    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        return slave.send_file_like_message(
            MsgType.Animation, Path("tests/mocks/animation_0.gif"), "image/gif",
            chat, target=target, reactions=True, commands=True, substitution=True)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert tg_msg.gif
        # Cannot do further assertion here as Telegram has converted the GIF
        # to MP4
        assert efb_msg.text in tg_msg.raw_text
        for i in efb_msg.reactions:
            assert i in tg_msg.raw_text
        if efb_msg.commands:
            assert tg_msg.button_count == len(efb_msg.commands)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message_text(
            message, reactions=True, commands=True, substitution=True)

    def edit_message_media(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message(
            message, Path("tests/mocks/animation_1.gif"), "image/gif",
            reactions=True, commands=True, substitution=True)

    def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class VideoMessageFactory(MessageFactory):

    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        return slave.send_file_like_message(
            MsgType.Video, Path("tests/mocks/video_0.mp4"), "video/mp4",
            chat, target=target, reactions=True, commands=True, substitution=True)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert tg_msg.video
        # Cannot do further assertion here as Telegram has re-encoded the
        # video sent out
        assert efb_msg.text in tg_msg.raw_text
        for i in efb_msg.reactions:
            assert i in tg_msg.raw_text
        if efb_msg.commands:
            assert tg_msg.button_count == len(efb_msg.commands)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message_text(
            message, reactions=True, commands=True, substitution=True)

    def edit_message_media(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message(
            message, Path("tests/mocks/video_1.mp4"), "video/mp4",
            reactions=True, commands=True, substitution=True)

    def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


class VoiceMessageFactory(MessageFactory):

    media_editable = False

    def send_message(self, slave: MockSlaveChannel, chat: Chat,
                     target: Optional[Message] = None) -> Message:
        return slave.send_file_like_message(
            MsgType.Voice, Path("tests/mocks/audio_0.mp3"), "audio/mpeg",
            chat, target=target, reactions=True, commands=True, substitution=True)

    def compare_message(self, tg_msg: Message, efb_msg: EFBMessage) -> None:
        assert tg_msg.voice
        # Cannot do further assertion here as Telegram has converted the voice
        # file to OGG OPUS
        assert efb_msg.text in tg_msg.raw_text
        for i in efb_msg.reactions:
            assert i in tg_msg.raw_text
        if efb_msg.commands:
            assert tg_msg.button_count == len(efb_msg.commands)

    def edit_message(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message_text(
            message, reactions=True, commands=True, substitution=True)

    def edit_message_media(self, slave: MockSlaveChannel, message: Message) -> Optional[Message]:
        return slave.edit_file_like_message(
            message, Path("tests/mocks/audio_0.mp3"), "audio/mpeg",
            reactions=True, commands=True, substitution=True)

    def finalize_message(self, tg_msg: Message, efb_msg: EFBMessage):
        if efb_msg.file and not efb_msg.file.closed:
            efb_msg.file.close()


@mark.parametrize("factory", [
    TextMessageFactory(), LinkMessageFactory(), LocationMessageFactory(),
    ImageMessageFactory(large=False), ImageMessageFactory(large=True),
    StickerMessageFactory(), FileMessageFactory(), AnimationMessageFactory(),
    VideoMessageFactory(), VoiceMessageFactory(),
    TextMessageFactory(unsupported=True)
], ids=str)
async def test_slave_message(helper, client, bot_group, slave, channel, factory: MessageFactory):
    chat = slave.group

    with link_chats(channel, (chat,), bot_group):
        message_ids = []
        efb_msg = factory.send_message(slave, chat)
        tg_msg = await helper.wait_for_message(in_chats(bot_group))
        message_ids.append(tg_msg.id)
        factory.compare_message(tg_msg, efb_msg)

        edited_efb_msg = factory.edit_message(slave, efb_msg)
        if edited_efb_msg is not None:
            filters = in_chats(bot_group)
            if factory.content_editable:
                filters &= edited(*message_ids)
            tg_msg = await helper.wait_for_message(filters)
            if not factory.content_editable:
                message_ids.append(tg_msg.id)
            factory.compare_message(tg_msg, edited_efb_msg)

        edited_media_efb_msg = factory.edit_message_media(slave, efb_msg)
        if edited_media_efb_msg is not None:
            filters = in_chats(bot_group)
            if factory.media_editable:
                filters &= edited(*message_ids)
                await helper.wait_for_message(filters)
                # Get only the second message as editing media with caption takes 2 steps
            tg_msg = await helper.wait_for_message(filters)
            if not factory.media_editable:
                message_ids.append(tg_msg.id)
            factory.compare_message(tg_msg, edited_media_efb_msg)

        targeted_message = factory.send_message(slave, chat, target=efb_msg)
        targeted_tg_msg = await helper.wait_for_message(in_chats(bot_group) & reply_to(*message_ids))
        factory.compare_message(targeted_tg_msg, targeted_message)
