
EFB Telegram Master Channel (ETM)
*********************************

.. image:: https://img.shields.io/pypi/v/efb-telegram-master.svg
   :target: https://pypi.org/project/efb-telegram-master/
   :alt: PyPI release

.. image:: https://d322cqt584bo4o.cloudfront.net/ehforwarderbot/localized.svg
   :target: https://crowdin.com/project/ehforwarderbot/
   :alt: Translate this project

`README in other languages <./readme_translations>`_.

**Channel ID**: ``blueset.telegram``

ETM is a Telegram Master Channel for EH Forwarder Bot, based on
Telegram Bot API, ``python-telegram-bot``.


Beta version
============

This is an unstable beta version, and its functionality may change at
any time.


Requirements
============

* Python >= 3.6

* EH Forwarder Bot >= 2.0.0

* ffmpeg

* libmagic

* libwebp


Getting Started
===============

1. Install all required binary dependencies

2. Install ETM

    ::
       pip3 install efb-telegram-master

3. Enable ETM in the profile’s ``config.yaml``

    The path of your profile storage directory depends on your
    configuration.

    **(As of EFB 2.0.0a1: Default profile storage directory is located
    at** ``~/.ehforwarderbot/profiles/default`` **)**

1. Configure the channel (described as follows)


Alternative installation methods
--------------------------------

ETM also has other alternative installation methods contributed by the
community, including:

* `AUR package
   <https://aur.archlinux.org/packages/python-efb-telegram-master-git>`_
   maintained by `KeLiu <https://github.com/specter119>`_
   (``python-efb-telegram-master-git``)

* Other `installation scripts and containers (e.g. Docker)
   <https://github.com/blueset/ehForwarderBot/wiki/Channels-Repository#scripts-and-containers-eg-docker>`_


Configuration
=============


Set up a bot
------------

Create a bot with `@BotFather <https://t.me/botfather>`_, give it a
name and a username. Then you'll get a token, which will be used
later. Keep this token secure, as it gives who owns it the full access
to the bot.

Use ``/setjoingroups`` to allow your bot to join groups. Use
``/setprivacy`` to disable the privacy restriction of the bot, so that
it can receive all messages in the group.


Complete configuration file
---------------------------

Configuration file is stored at ``<profile
directory>/blueset.telegram/config.yaml``.

A sample config file can be as follows:

::

   ##################
   # Required items #
   ##################
   # You are required to fill the option below,
   # or this channel will not work.

   # Telegram bot token.
   # This is the token you obtained from BotFather
   token: "12345678:1a2b3c4d5e6g7h8i9j"

   # List of Telegram User IDs of admins
   # ETM will only process messages and commands from users
   # listed below. This ID can be obtained from various ways
   # on Telegram.
   admins:
   - 102938475
   - 91827364

   # Experimental Flags
   # This section can be used to enable experimental functionality.
   # However, those features may be changed or removed at any time.
   # Options in this section is explained afterward.
   flags:
       option_one: 10
       option_two: false
       option_three: "foobar"


Usage
=====

At the beginning, messages from all senders will be sent to the user
directly, that means every message will be mixed in the same
conversation. By linking a chat, you can redirect messages from a
specific sender to an empty group for a more organized conversation.

In a nutshell, ETM offers the following commands, you can also send it
to BotFather for a command list:

::

   help - Show commands list.
   link - Link a remote chat to a group.
   unlink_all - Unlink all remote chats from a group.
   info - Display information of the current Telegram chat.
   chat - Generate a chat head.
   extra - Access additional features from Slave Channels.
   update_info - Update the group name and profile picture.
   react - Send a reaction to a message, or show a list of reactors.

Note: In case of multiple admins are assigned, they may all send message
   on your behalf, but only the 0th admin can receive direct message
   from the bot.


``/link``: Link a chat
----------------------

1. Create a new group, invite your bot to the group

2. Send ``/link`` directly to the bot, then select your preferred
    slave chat.

3. Tap “Link” and select your new group. *You can also choose to
    unlink or relink a linked chat from this menu.*

4. Tap “Start” at the bottom of your screen, and you should see a
    success message: “Chat linked.”

Note: You may introduce non-ETM admin users to the group, however, they:

   * Can read all messages send from the related remote chat;

   * May NOT send message on your behalf.

If the “Link” button doesn’t work for you, you may try the “Manual
Link/Relink” button. To manually link a remote chat:

1. Add the bot to the group you want to link to

2. Copy the code provided by the bot, and send it to the group.

3. If the group is linked successfully, you would receive a
    confirmation from the bot.

Also, you can send ``/unlink_all`` to a group to unlink all remote
chats from it.


Advanced feature: Filtering
~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you have just too much chats, and being too tired for keep tapping
``Next >``, or maybe you just want to find a way to filter out what
you’re looking for, now ETM has equipped ``/chat`` and ``/list`` with
filtering feature. Attach your keyword behind, and you can get a
filtered result.

E.g.: ``/chat Eana`` will give you all chats has the word “Eana”.

Technical Details: The filter query is in fact a regular expression
matching. We used Python’s ``re.search`` with flags ``re.DOTALL |
re.IGNORECASE`` in this case, i.e.: ``.`` matches everything including
line breaks, and the query is NOT case-sensitive. Each comparison is
done against a specially crafted string which allows you to filter
multiple criteria.

::

   Channel: <Channel name>
   Name: <Chat name>
   Alias: <Chat Alias>
   ID: <Chat Unique ID>
   Type: (User|Group)
   Mode: [Linked]
   Other: <Python Dictionary String>

Note: Type can be either “User” or “Group”Other is the vendor specific
   information provided by slave channels. Format of such information
   is specified in their documentations respectively.

Examples:

* Look for all WeChat groups: ``Channel: WeChat.*Type: Group``

* Look for everyone who has an alias ``Name: (.*?)\nAlias: (?!\1)``

* Look for all entries contain “John” and “Johnny” in any order:
   ``(?=.*John)(?=.*Johnny)"``


Send a message
--------------


Send to a linked chat
~~~~~~~~~~~~~~~~~~~~~

You can send message as you do in a normal Telegram chat.

What is supported:

* Send/forward message in all supported types

* Direct reply to a message

* Send message with inline bot in supported types

What is NOT supported:

* @ reference

* Markdown/HTML formatting

* Messages with unsupported types


Send to a non-linked chat
~~~~~~~~~~~~~~~~~~~~~~~~~

To send a message to a non-linked chat, you should “direct reply” to a
message or a “chat head” that is sent from your recipient. Those
messages should appear only in the bot conversation.

In a non-linked chat, direct reply will not be delivered to the remote
channel, everything else is supported as it does in a linked chat.


Edit and delete message
~~~~~~~~~~~~~~~~~~~~~~~

In EFB v2, the framework added support to message editing and removal,
and so does ETM. However, due to the limitation of Telegram Bot API,
although you may have selected “Delete for the bot”, or “Delete for
everyone” while deleting messages, the bot would not know anything
about it. Therefore, if you want your message to be removed from a
remote chat, edit your message and prepend it with rm` (it’s R, M, and
~`, not single quote), so that the bot knows that you want to delete
the message.

Please also notice that some channels may not support editing and/or
deleting messages depends on their implementations.


``/chat``: Chat head
~~~~~~~~~~~~~~~~~~~~

If you want to send a message to a non-linked chat which has not yet
sent you a message, you can ask ETM to generate a “chat head”. Chat
head works similarly to an incoming message, you can reply to it to
send messages to your recipient.

Send ``/chat`` to the bot, and choose a chat from the list. When you
see “Reply to this message to send to from ”, it’s ready to go.


Advanced feature: Filtering
"""""""""""""""""""""""""""

Filter is also available in ``/chat`` command. Please refer to the
same chapter above, under ``/link`` for the details.


``/extra``: External commands from slave channels (“additional features”)
-------------------------------------------------------------------------

Some slave channels may provide commands that allows you to remotely
control those accounts, and achieve extra functionality, those
commands are called “additional features”. To view the list of
available extra functions, send ``/extra`` to the bot, you will
receive a list of commands available.

Those commands are named like “``/<number>_<command_name>``”, and can
be called like an CLI utility. (of course, advanced features like
piping etc would not be supported)


``/update_info``: Update name and profile picture of linked group
-----------------------------------------------------------------

ETM can help you to update the name and profile picture of a group to
match with appearance in the remote chat.

This functionality is available when:

* This command is sent to a group

* The bot is an admin of the group

* The group is linked to **exactly** one remote chat

* The remote chat is accessible

Profile picture will not be set if it’s not available from the slave
channel.


``/react``: Send reactions to a message or show a list of reactors
------------------------------------------------------------------

Reply ``/react`` to a message to show a list of chat members who have
reacted to the message and what their reactions are.

Reply ``/react`` followed by an emoji to react to this message, e.g.
``/react 👍``. Send ``/react -`` to remove your reaction.

Note that some slave channels may not accept message reactions, and
some channels have a limited reactions you can send with. Usually when
you send an unaccepted reaction, slave channels can provide a list of
suggested reactions you may want to try instead.


Telegram Channel support
------------------------

ETM supports linking remote chats to Telegram Channels with partial
support.

The bot can:

* Link one or more remote chats to a Telegram Channel

* Check and manage link status of the channel

* Update channel title and profile pictures accordingly

It cannot:

* Process messages sent by you or others to the channel

* Accept commands in the channel

Currently the following commands are supported in channels:

* ``/start`` for manual chat linking

* ``/link`` to manage chats linked to the channel

* ``/info`` to show information of the channel

* ``/update_info`` to update the channel title and picture

How to use:

1. Add the bot as an administrator of the channel

2. Send commands to the channel

3. Forward the command message to the bot privately


Limitations
===========

Due to the technical limitations of Telegram Bot API and EH Forwarder
Bot framework, there are some limitations:

* Some Telegram message types are **not** supported:
      * Game messages

      * Invoice messages

      * Payment messages

      * Passport messages

      * Vote messages

* Some components in Telegram messages are dropped:
      * Original author and signature of forwarded messages

      * Formats, links and link previews

      * Buttons attached to messages

      * Details about inline bot used on messages

* Some components in messages from slave channels are dropped:
      * @ references.

* The Telegram bot can only
      * send you any file up to 50 MiB,

      * receive file from you up to 20 MiB.


Experimental flags
==================

The following flags are experimental features, may change, break, or
disappear at any time. Use at your own risk.

Flags can be enabled in the ``flags`` key of the configuration file,
e.g.:

::

   flags:
       flag_name: flag_value

* ``no_conversion`` *(bool)* [Default: ``false``]

   Disable audio conversion, send all audio file as is, and let
   Telegram to handle it.

   *Only works in linked chats.*

* ``chats_per_page`` *(int)* [Default: ``10``]

   Number of chats shown in when choosing for ``/chat`` and ``/link``
   command. An overly large value may lead to malfunction of such
   commands.

* ``network_error_prompt_interval`` *(int)* [Default: ``100``]

   Notify the user about network error every ``n`` errors received.
   Set to 0 to disable it.

* ``multiple_slave_chats`` *(bool)* [Default: ``true``]

   Link more than one remote chat to one Telegram group. Send and
   reply as you do with an unlinked chat. Disable to link remote chats
   and Telegram group one-to-one.

* ``prevent_message_removal`` *(bool)* [Default: ``true``]

   When a slave channel requires to remove a message, EFB will ignore
   the request if this value is ``true``.

* ``auto_locale`` *(str)* [Default: ``true``]

   ..
      Detect the locale from admin's messages automatically. Locale
      defined in environment variables will be used otherwise.

* ``retry_on_error`` *(bool)* [Default: ``false``]

   ..
      Retry infinitely when an error occurred while sending request to
      Telegram Bot API. Note that this may lead to repetitive message
      delivery, as the respond of Telegram Bot API is not reliable,
      and may not reflect the actual result.

* ``send_image_as_file`` *(bool)* [Default: ``false``]

   ..
      Send all image messages as files, in order to prevent Telegram's
      image compression in an aggressive way.


Experimental localization support
=================================

ETM supports localized user interface prompts experimentally. The bot
detects languages of Telegram Client of the admins from their
messages, and automatically matches with a supported language on the
go. Otherwise, you can set your language by turning off the
``auto_locale`` feature, and then setting the locale environmental
variable (``LANGUAGE``, ``LC_ALL``, ``LC_MESSAGES`` or ``LANG``) to
one of our supported languages. Meanwhile, you can help to translate
this project into your languages on `our Crowdin page
<https://crowdin.com/project/ehforwarderbot/>`_.
