from pytest import fixture
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from ehforwarderbot import EFBMsg, EFBChat
from ehforwarderbot.types import ReactionName
from efb_telegram_master.constants import Emoji
from efb_telegram_master.slave_message import SlaveMessageProcessor


def test_slave_message_reaction_footer(slave):
    # No content should be returned if no reaction is available
    assert not SlaveMessageProcessor.build_reactions_footer({})

    # Footer should contain the reaction name and number of reactors
    reactions = {
        ReactionName("__reaction_a__"):
            [slave.chat_with_alias, slave.chat_without_alias],
        ReactionName("__reaction_b__"):
            [slave.chat_with_alias],
        ReactionName("__reaction_c__"): []
    }
    footer = SlaveMessageProcessor.build_reactions_footer(reactions)
    assert "__reaction_a__" in footer
    assert "2" in footer
    assert "__reaction_b__" in footer
    assert "1" in footer
    assert "__reaction_c__" not in footer

    # Footer should be empty if no reaction name gives any value.
    footer = SlaveMessageProcessor.build_reactions_footer({
        ReactionName("__reaction_x__"): []
    })
    assert not footer


@fixture(scope="module")
def generate_message_template(channel):
    return channel.slave_messages.generate_message_template


@fixture(scope="module")
def private(slave):
    return slave.chat_with_alias


@fixture(scope="module")
def group(slave):
    return slave.group


@fixture(scope="module")
def group_member(slave):
    # Ensure the chat should have an alias
    for i in slave.group.members:
        if i.chat_alias:
            return i
    return slave.group.members[0]


@fixture(scope="module")
def self(channel):
    return channel.chat_manager.self


def build_dummy_message(chat: EFBChat, author: EFBChat) -> EFBMsg:
    message = EFBMsg()
    message.chat = chat
    message.author = author
    return message


def test_slave_message_generate_common_private(generate_message_template, private):
    message = build_dummy_message(private, private)
    header = generate_message_template(message, False)
    assert private.chat_name in header
    assert private.chat_alias in header
    assert private.channel_emoji in header
    assert Emoji.USER in header


def test_slave_message_generate_common_private_self(generate_message_template, private, self):
    message = build_dummy_message(private, self)
    header = generate_message_template(message, False)
    assert private.chat_name in header
    assert private.chat_alias in header
    assert private.channel_emoji in header
    assert self.chat_name in header
    assert Emoji.USER in header


def test_slave_message_generate_common_linked(generate_message_template, private):
    message = build_dummy_message(private, private)
    header = generate_message_template(message, True)
    assert not header


def test_slave_message_generate_common_linked_self(generate_message_template, private, self):
    message = build_dummy_message(private, self)
    header = generate_message_template(message, True)
    assert private.chat_name not in header
    assert private.chat_alias not in header
    assert private.channel_emoji not in header
    assert self.chat_name in header
    assert Emoji.USER not in header


def test_slave_message_generate_group_private(generate_message_template, group, group_member):
    message = build_dummy_message(group, group_member)
    header = generate_message_template(message, False)
    assert group.chat_name in header
    assert group.chat_alias in header
    assert group.channel_emoji in header
    assert group_member.chat_name in header
    assert group_member.chat_alias in header
    assert Emoji.GROUP in header


def test_slave_message_generate_group_private_self(generate_message_template, group, self):
    message = build_dummy_message(group, self)
    header = generate_message_template(message, False)
    assert group.chat_name in header
    assert group.chat_alias in header
    assert group.channel_emoji in header
    assert self.chat_name in header
    assert Emoji.GROUP in header


def test_slave_message_generate_group_linked(generate_message_template, group, group_member):
    message = build_dummy_message(group, group_member)
    header = generate_message_template(message, True)
    assert group.chat_name not in header
    assert group.chat_alias not in header
    assert group.channel_emoji not in header
    assert Emoji.GROUP not in header
    assert group_member.chat_name in header
    assert group_member.chat_alias in header


def test_slave_message_generate_group_linked_self(generate_message_template, group, self):
    message = build_dummy_message(group, self)
    header = generate_message_template(message, True)
    assert group.chat_name not in header
    assert group.chat_alias not in header
    assert group.channel_emoji not in header
    assert Emoji.GROUP not in header
    assert self.chat_name in header


@fixture(scope="module")
def build_inline_keyboard(channel):
    return channel.slave_messages.build_chat_info_inline_keyboard


def keyboard_to_sequence(markup: InlineKeyboardMarkup) -> str:
    x = []
    for row in markup.inline_keyboard:
        x.append(f"[{', '.join(button.text for button in row)}]")
    return f"[{', '.join(x)}]"


def test_build_inline_keyboard_empty(build_inline_keyboard, private):
    msg = build_dummy_message(private, private)
    keyboard = build_inline_keyboard(msg, "", "", None)
    seq = keyboard_to_sequence(keyboard)
    assert seq == '[]'


def test_build_inline_keyboard_full(build_inline_keyboard, private):
    msg = build_dummy_message(private, private)
    msg.text = "__text__"
    keyboard = build_inline_keyboard(msg, "__template__", "__reactions__", None)
    seq = keyboard_to_sequence(keyboard)
    assert "__text__" in seq
    assert "__template__" in seq
    assert "__reactions__" in seq


def test_build_inline_keyboard_existing_buttons(build_inline_keyboard, private):
    msg = build_dummy_message(private, private)
    msg.text = "__text__"
    markup = InlineKeyboardMarkup.from_row([
        InlineKeyboardButton("__button_a__"),
        InlineKeyboardButton("__button_b__"),
    ])
    keyboard = build_inline_keyboard(msg, "__template__", "__reactions__", markup)
    seq = keyboard_to_sequence(keyboard)
    assert "__button_a__" in seq
    assert "__button_b__" in seq
    assert "__text__" in seq
    assert "__template__" in seq
    assert "__reactions__" in seq
