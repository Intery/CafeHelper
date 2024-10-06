from typing import Optional, Self

import discord
import twitchio

from meta import LionBot
from utils.lib import utc_now

from . import logger
from .data import ProfileData



class UserProfile:
    def __init__(self, bot: LionBot, profile_row):
        self.bot = bot
        self.profile_row: ProfileData.UserProfileRow = profile_row

    @property
    def cog(self):
        return self.bot.get_cog('ProfileCog')

    @property
    def data(self) -> ProfileData:
        return self.cog.data

    @property
    def profileid(self):
        return self.profile_row.profileid

    def __repr__(self):
        return f"<UserProfile profileid={self.profileid} profile={self.profile_row}>"

    async def attach_discord(self, user: discord.User | discord.Member):
        """
        Attach a new discord user to this profile.
        Assumes the discord user does not itself have a profile.
        """
        discord_row = await self.data.DiscordProfileRow.create(
            profileid=self.profileid, 
            userid=user.id
        )
        logger.info(
            f"Attached discord user {user!r} to profile {self!r}"
        )
        return discord_row

    async def attach_twitch(self, user: twitchio.User):
        """
        Attach a new Twitch user to this profile.
        """
        twitch_row = await self.data.TwitchProfileRow.create(
            profileid=self.profileid,
            userid=str(user.id)
        )
        logger.info(
            f"Attached twitch user {user!r} to profile {self!r}"
        )
        return twitch_row

    async def discord_accounts(self) -> list[ProfileData.DiscordProfileRow]:
        """
        Fetch the Discord accounts associated to this profile.
        """
        return await self.data.DiscordProfileRow.fetch_where(profileid=self.profileid)

    async def twitch_accounts(self) -> list[ProfileData.DiscordProfileRow]:
        """
        Fetch the Twitch accounts associated to this profile.
        """
        return await self.data.TwitchProfileRow.fetch_where(profileid=self.profileid)

    @classmethod
    async def fetch(cls, bot: LionBot, profile_id: int) -> Self:
        profile_row = await bot.get_cog('ProfileCog').data.UserProfileRow.fetch(profile_id)
        if profile_row is None:
            raise ValueError("Provided profile_id does not exist.")
        return cls(bot, profile_row)

    @classmethod
    async def fetch_from_twitchid(cls, bot: LionBot, userid: int | str) -> Optional[Self]:
        data = bot.get_cog('ProfileCog').data
        rows = await data.TwitchProfileRow.fetch_where(userid=str(userid))
        if rows:
            return await cls.fetch(bot, rows[0].profileid)

    @classmethod
    async def fetch_from_discordid(cls, bot: LionBot, userid: int) -> Optional[Self]:
        data = bot.get_cog('ProfileCog').data
        rows = await data.DiscordProfileRow.fetch_where(userid=str(userid))
        if rows:
            return await cls.fetch(bot, rows[0].profileid)

    @classmethod
    async def create(cls, bot: LionBot, **kwargs) -> Self:
        """
        Create a new empty profile with the given initial arguments.

        Profiles should usually be created using `create_from_discord` or `create_from_twitch`
        to correctly setup initial profile preferences (e.g. name, avatar).
        """
        # Create a new profile
        data = bot.get_cog('ProfileCog').data
        profile_row = await data.UserProfileRow.create(created_at=utc_now())
        profile = await cls.fetch(bot, profile_row.profileid)
        return profile

    @classmethod
    async def create_from_discord(cls, bot: LionBot, user: discord.Member | discord.User, **kwargs) -> Self:
        """
        Create a new profile using the given Discord user as a base.
        """
        profile = await cls.create(bot, **kwargs)
        await profile.attach_discord(user)
        return profile

    @classmethod
    async def create_from_twitch(cls, bot: LionBot, user: twitchio.User, **kwargs) -> Self:
        """
        Create a new profile using the given Twitch user as a base.
        """
        profile = await cls.create(bot, **kwargs)
        await profile.attach_twitch(user)
        return profile
