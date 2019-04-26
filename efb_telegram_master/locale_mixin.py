# coding=utf-8

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import TelegramChannel


class LocaleMixin:
    channel: 'TelegramChannel'

    @property
    def _(self):
        return self.channel._

    @property
    def ngettext(self):
        return self.channel.ngettext
