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
- Improvements on TGS to GIF conversion logic (by `Curtis Jiang`__)

__ https://github.com/jqqqqqqqqqq/UnifiedMessageRelay/blob/c920d005714a33fbd50594ef8013ce7ec2f3b240/src/Core/UMRFile.py#L141

Removed
-------

Fixed
-----
- Attempt to fix “*Database is locked*” issue by wrapping all database write
  operations with an atomic transaction.

Known issue
-----------
- All edited messages from Telegram are seen as edited with media due to the
  update of Telegram Bot API 4.5. This will be fixed only after Python Telegram
  Bot introduce supports to Bot API 4.5. No workaround is available for now.

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
.. _#93: https://etm.1a23.studio/issues/93