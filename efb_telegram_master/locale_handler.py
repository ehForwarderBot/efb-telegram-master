# coding=utf-8

import gettext
import logging
from pkg_resources import resource_filename
from typing import TYPE_CHECKING

from language_tags import tags
from telegram.ext.handler import Handler
from telegram import Update

if TYPE_CHECKING:
    from . import TelegramChannel


class LocaleHandler(Handler):
    """
    Handler class Extract.

    Args:
        channel (TelegramChannel): The ETM channel object.
        pass_update_queue (optional[bool]): If the handler should be passed the
            update queue as a keyword argument called ``update_queue``. It can
            be used to insert updates. Default is ``False``
    """

    def __init__(self, channel: 'TelegramChannel', pass_update_queue: bool = False):
        def void_function(*args, **kwargs):
            pass

        super().__init__(void_function, pass_update_queue)
        self.logger = logging.getLogger(__name__)

        self.channel = channel
        self.auto_locale = self.channel.flag('auto_locale')

    def check_update(self, update: object):
        if not self.auto_locale:
            return False
        if not isinstance(update, Update):
            return False
        if not update.effective_user or not update.effective_user.language_code:
            return
        self.logger.debug("[%s] Update has language %s.", update.update_id, update.effective_user.language_code)
        if update.effective_user.language_code and update.effective_user.language_code != self.channel.locale:
            self.channel.locale = update.effective_user.language_code
            tag = tags.tag(update.effective_user.language_code)
            if tag.language:
                locale = tag.language.format
                if tag.region:
                    locale += "_" + tag.region.format
            else:
                locale = update.effective_user.language_code.replace('-', '_')
            self.logger.info("Updating locale to %s", locale)
            self.channel.translator = gettext.translation("efb_telegram_master",
                                                          resource_filename('efb_telegram_master', 'locale'),
                                                          languages=[locale, 'C'],
                                                          fallback=True)
        return False

    def handle_update(self, update, dispatcher, check_result, context=None):
        pass
