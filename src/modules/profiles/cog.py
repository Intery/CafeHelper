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
from .data import ProfileData


class UserProfile:
    def __init__(self):
        ...


class ProfileCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.data = bot.db.load_registry(ProfileData())

    async def cog_load(self):
        await self.data.init()

    async def cog_check(self, ctx):
        return True

    # Profile API
    async def fetch_profile_discord(self, userid: int, create=True):
        """
        Fetch or create a UserProfile from the given Discord userid.
        """
        ...

    async def fetch_profile_twitch(self, userid: int, create=True):
        """
        Fetch or create a UserProfile from the given Twitch userid.
        """
        ...

    async def fetch_profile(self, profileid: int):
        """
        Fetch a UserProfile by the given id.
        """
        ...

    async def merge_profiles(self, sourceid: int, targetid: int):
        """
        Merge two UserProfiles by id.
        Merges the 'sourceid' into the 'targetid'.
        """
        ...

    async def fetch_community_discord(self, guildid: int, create=True):
        ...

    async def fetch_community_twitch(self, guildid: int, create=True):
        ...

    async def fetch_community(self, communityid: int):
        ...

    # ----- Profile Commands -----

    # Link twitch profile
