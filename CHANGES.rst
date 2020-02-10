=========
Changelog
=========

All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog`_, adapted for reStructuredText syntax
and this project adheres to `Semantic Versioning`_-flavored `PEP 440`_.

.. _Keep a Changelog: https://keepachangelog.com/en/1.0.0/
.. _PEP 440: https://www.python.org/dev/peps/pep-0440/
.. _Semantic Versioning: https://semver.org/spec/v2.0.0.html

Unreleased
==========

Added
-----
- `#93`_: Send error message to user when size of media from slave channel
  exceeds Telegram Bot API limit

Changed
-------
- Improved compatibility with Python Telegram Bot 12.4.1

Removed
-------

Fixed
-----

Known issue
-----------
- All edited messages from Telegram are seen as edited with media due to the
  update of Telegram Bot API 4.5. This will be fixed only after Python Telegram
  Bot introduce supports to Bot API 4.5. No workaround is available for now.

2.0.0_ - 2020-01-31
===================
First release.

.. _2.0.0: https://etm.1a23.studio/releases/tag/v2.0.0
.. _2.0.1: https://etm.1a23.studio/compare/v2.0.0...v0.0.1
.. _#93: https://etm.1a23.studio/issues/93
