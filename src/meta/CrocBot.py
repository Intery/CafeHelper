from collections import defaultdict
from typing import TYPE_CHECKING

import logging

import twitchio
from twitchio.ext import commands
from twitchio.ext import pubsub
from twitchio.ext.commands.core import itertools

from data import Database

from .config import Conf


logger = logging.getLogger(__name__)


class CrocBot(commands.Bot):
    def __init__(self, *args,
                 config: Conf,
                 data: Database,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.data = data
        self.pubsub = pubsub.PubSubPool(self)

        self._member_cache = defaultdict(dict)

    async def event_ready(self):
        logger.info(f"Logged in as {self.nick}. User id is {self.user_id}")

    async def event_join(self, channel: twitchio.Channel, user: twitchio.User):
        self._member_cache[channel.name][user.name] = user

    async def event_message(self, message: twitchio.Message):
        if message.channel and message.author:
            self._member_cache[message.channel.name][message.author.name] = message.author
        await self.handle_commands(message)

    async def seek_user(self, userstr: str, matching=True, fuzzy=True):
        if userstr.startswith('@'):
            matching = False
        userstr = userstr.strip('@ ')

        result = None
        if matching and len(userstr) >= 3:
            lowered = userstr.lower()
            full_matches = []
            for user in itertools.chain(*(cmems.values() for cmems in self._member_cache.values())):
                matchstr = user.name.lower()
                print(matchstr)
                if matchstr.startswith(lowered):
                    result = user
                    break
                if lowered in matchstr:
                    full_matches.append(user)
            if result is None and full_matches:
                result = full_matches[0]
        print(result)

        if result is None:
            lookup = userstr
        elif result.id is None:
            lookup = result.name
        else:
            lookup = None

        if lookup:
            found = await self.fetch_users(names=[lookup])
            if found:
                result = found[0]

        # No matches found
        return result
