=========
Changelog
=========

All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog`_, adapted for reStructuredText syntax.
This project adheres to `Semantic Versioning`_-flavored `PEP 440`_.

.. _Keep a Changelog: https://keepachangelog.com/en/1.0.0/
.. _PEP 440: https://www.python.org/dev/peps/pep-0440/
.. _Semantic Versioning: https://semver.org/spec/v2.0.0.html

Unreleased
==========

Added
-----

Changed
-------

Removed
-------

Fixed
-----

Known issue
-----------

2.2.0_ - 2020-08-25
===================

Added
-----
- Experimental flag ``default_media_prompt`` to modify placeholder text of
  media messages with no caption.

Changed
-------
- Moved ``lottie`` and ``cairosvg`` to optional dependencies to avoid
  unnecessary hurdle on new installations.


2.1.0_ - 2020-07-11
===================

Fixed
-----
- Update dependency requirement of ``python-telegram-bot`` for the latest API.
- Bump minor version for the new features added in 2.0.4.

2.0.4_ - 2020-07-09
===================

Added
-----
- Add support to outgoing 🎲, 🎯, 🏀 messages from Telegram
- Allow wizard to set commands list of the bot
- Show invalid remote chats when sending ``/link`` to a group (`#100`_)
- Suppress first poll conflict warning within 60 seconds as an isolated case (`#103`_)


Fixed
-----
- Program breaks when older version of Pillow is encountered
- Attempt to fix the issue where choosing destination for a an unaddressed
  message may lead to unintended behavior
- Wizard should return int instead of float
- Some symbols are over escaped in chat names
- Missing ``send_to_last_chat`` in wizard (`#99`_)
- Migrate from ``tgs`` to ``lottie`` per upstream library
- Editing messages sent with destination specified post-sending will not trigger error message again (`#102`_)

2.0.3_ - 2020-04-04
===================

Added
-----
- Check if the bot would work properly in linked Telegram groups before linking.

Changed
-------
- Improvements on TGS to GIF conversion logic (by `Curtis Jiang`__)

__ https://github.com/jqqqqqqqqqq/UnifiedMessageRelay/blob/c920d005714a33fbd50594ef8013ce7ec2f3b240/src/Core/UMRFile.py#L141

Fixed
-----
- Attempt to fix “*Database is locked*” issue by wrapping all database write
  operations with an atomic transaction.
- Edited messages from Telegram can now be correctly detected for
  caption-only or media edits.

Known issue
-----------
- 🎲 messages are not supported until Python Telegram Bot introduce supports
  to Bot API 4.7. No workaround is available for now.

2.0.2_ - 2020-02-26
===================

Fixed
-----
- Experimental flags settings breaks the ETM wizard.
- Exception requiring ``libcairo`` when ``animation_sticker`` flag is not enabled.

Known issue
-----------
- All edited messages from Telegram are seen as edited with media due to the
  update of Telegram Bot API 4.5. This will be fixed only after Python Telegram
  Bot introduce supports to Bot API 4.5. No workaround is available for now.

2.0.1_ - 2020-02-10
===================

Added
-----
- `#93`_: Send error message to user when size of media from slave channel
  exceeds Telegram Bot API limit

Changed
-------
- Improved compatibility with Python Telegram Bot 12.4.1

Known issue
-----------
- All edited messages from Telegram are seen as edited with media due to the
  update of Telegram Bot API 4.5. This will be fixed only after Python Telegram
  Bot introduce supports to Bot API 4.5. No workaround is available for now.

2.0.0_ - 2020-01-31
===================
First release.

.. _2.0.0: https://etm.1a23.studio/releases/tag/v2.0.0
.. _2.0.1: https://etm.1a23.studio/compare/v2.0.0...v2.0.1
.. _2.0.2: https://etm.1a23.studio/compare/v2.0.1...v2.0.2
.. _2.0.3: https://etm.1a23.studio/compare/v2.0.2...v2.0.3
.. _2.0.4: https://etm.1a23.studio/compare/v2.0.3...v2.0.4
.. _2.1.0: https://etm.1a23.studio/compare/v2.0.4...v2.1.0
.. _2.2.0: https://etm.1a23.studio/compare/v2.1.0...v2.2.0
.. _#93: https://etm.1a23.studio/issues/93
.. _#99: https://etm.1a23.studio/issues/99
.. _#100: https://etm.1a23.studio/issues/100
.. _#102: https://etm.1a23.studio/issues/102
.. _#103: https://etm.1a23.studio/issues/103
