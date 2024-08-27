from typing import TYPE_CHECKING

import logging

from twitchio.ext import commands
from twitchio.ext import pubsub

from data import Database

from .config import Conf


if TYPE_CHECKING:
    from .LionBot import LionBot


logger = logging.getLogger(__name__)


class CrocBot(commands.Bot):
    def __init__(self, *args,
                 config: Conf,
                 data: Database,
                 lionbot: 'LionBot', **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.data = data
        self.pubsub = pubsub.PubSubPool(self)
        self.lionbot = lionbot

    async def event_ready(self):
        logger.info(f"Logged in as {self.nick}. User id is {self.user_id}")
