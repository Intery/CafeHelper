import asyncio
from enum import Enum
from typing import Optional
from datetime import timedelta

import discord
from discord.ext import commands as cmds
import twitchio
from twitchio.ext import commands


from data.queries import ORDER
from meta import LionCog, LionBot, CrocBot
from utils.lib import utc_now
from . import logger
from .data import TwitchAuthData


class TwitchAuthCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.data = bot.db.load_registry(TwitchAuthData())

    async def cog_load(self):
        await self.data.init()

    # ----- Auth API -----

    async def fetch_client_for(self, userid: int):
        ...

