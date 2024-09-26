import asyncio
from enum import Enum
from typing import Optional
from datetime import timedelta

import discord
from discord.ext import commands as cmds
import twitchio
from twitchio.ext import commands
from twitchAPI.object.api import TwitchUser


from data.queries import ORDER
from meta import LionCog, LionBot, CrocBot
from utils.lib import utc_now
from . import logger
from .data import ProfileData


class UserProfile:
    def __init__(self, data, profile_row, *, discord_row=None, twitch_row=None):
        self.data: ProfileData = data
        self.profile_row: ProfileData.UserProfileRow = profile_row

        self.discord_row: Optional[ProfileData.DiscordProfileRow] = discord_row
        self.twitch_row: Optional[ProfileData.TwitchProfileRow] = twitch_row

    @property
    def profileid(self):
        return self.profile_row.profileid

    async def attach_discord(self, user: discord.User | discord.Member):
        """
        Attach a new discord user to this profile.
        """
        # TODO: Attach whatever other data we want to cache here.
        # Currently Lion also caches most of this data
        discord_row = await self.data.DiscordProfileRow.create(
            profileid=self.profileid, 
            userid=user.id
        )

    async def attach_twitch(self, user: TwitchUser):
        """
        Attach a new Twitch user to this profile.
        """
        ...

    @classmethod
    async def fetch_profile(
            cls, data: ProfileData, 
            *,
            profile_id: Optional[int] = None,
            profile_row: Optional[ProfileData.UserProfileRow] = None,
            discord_row: Optional[ProfileData.DiscordProfileRow] = None,
            twitch_row: Optional[ProfileData.TwitchProfileRow] = None,
    ):
        if not any((profile_id, profile_row, discord_row, twitch_row)):
            raise ValueError("UserProfile needs an id or a data row to construct.")
        if profile_id is None:
            profile_id = (profile_row or discord_row or twitch_row).profileid
        profile_row = profile_row or await data.UserProfileRow.fetch(profile_id)
        discord_row = discord_row or await data.DiscordProfileRow.fetch_profile(profile_id)
        twitch_row = twitch_row or await data.TwitchProfileRow.fetch_profile(profile_id)

        return cls(data, profile_row, discord_row=discord_row, twitch_row=twitch_row)


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
        # TODO: (Extension) May be context dependent
        # Current model assumes profile (one->0..n) discord
        discord_row = next(await self.data.DiscordProfileRow.fetch_where(userid=userid), None)
        if discord_row is None:
            profile_row = await self.data.UserProfileRow.create()

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
