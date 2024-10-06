from typing import Optional, Self

import discord
import twitchio

from meta import LionBot
from utils.lib import utc_now

from . import logger
from .data import ProfileData



class Community:
    def __init__(self, bot: LionBot, community_row):
        self.bot = bot
        self.row: ProfileData.CommunityRow = community_row

    @property
    def cog(self):
        return self.bot.get_cog('ProfileCog')

    @property
    def data(self) -> ProfileData:
        return self.cog.data

    @property
    def communityid(self):
        return self.row.communityid

    def __repr__(self):
        return f"<Community communityid={self.communityid} row={self.row}>"

    async def attach_discord(self, guild: discord.Guild):
        """
        Attach a new discord guild to this community.
        Assumes the discord guild is not already associated to a community.
        """
        discord_row = await self.data.DiscordCommunityRow.create(
            communityid=self.communityid,
            guildid=guild.id
        )
        logger.info(
            f"Attached discord guild {guild!r} to community {self!r}"
        )
        return discord_row

    async def attach_twitch(self, user: twitchio.User):
        """
        Attach a new Twitch user channel to this community.
        """
        twitch_row = await self.data.TwitchCommunityRow.create(
            communityid=self.communityid,
            channelid=str(user.id)
        )
        logger.info(
            f"Attached twitch channel {user!r} to community {self!r}"
        )
        return twitch_row

    async def discord_guilds(self) -> list[ProfileData.DiscordCommunityRow]:
        """
        Fetch the Discord guild rows associated to this community.
        """
        return await self.data.DiscordCommunityRow.fetch_where(communityid=self.communityid)

    async def twitch_channels(self) -> list[ProfileData.TwitchCommunityRow]:
        """
        Fetch the Twitch user rows associated to this profile.
        """
        return await self.data.TwitchCommunityRow.fetch_where(communityid=self.communityid)

    @classmethod
    async def fetch(cls, bot: LionBot, community_id: int) -> Self:
        community_row = await bot.get_cog('ProfileCog').data.CommunityRow.fetch(community_id)
        if community_row is None:
            raise ValueError("Provided community_id does not exist.")
        return cls(bot, community_row)

    @classmethod
    async def fetch_from_twitchid(cls, bot: LionBot, channelid: int | str) -> Optional[Self]:
        data = bot.get_cog('ProfileCog').data
        rows = await data.TwitchCommunityRow.fetch_where(channelid=str(channelid))
        if rows:
            return await cls.fetch(bot, rows[0].communityid)

    @classmethod
    async def fetch_from_discordid(cls, bot: LionBot, guildid: int) -> Optional[Self]:
        data = bot.get_cog('ProfileCog').data
        rows = await data.DiscordCommunityRow.fetch_where(guildid=guildid)
        if rows:
            return await cls.fetch(bot, rows[0].communityid)

    @classmethod
    async def create(cls, bot: LionBot, **kwargs) -> Self:
        """
        Create a new empty community with the given initial arguments.

        Communities should usually be created using `create_from_discord` or `create_from_twitch`
        to correctly setup initial preferences (e.g. name, avatar).
        """
        # Create a new community
        data = bot.get_cog('ProfileCog').data
        row = await data.CommunityRow.create(created_at=utc_now(), **kwargs)
        return await cls.fetch(bot, row.communityid)

    @classmethod
    async def create_from_discord(cls, bot: LionBot, guild: discord.Guild, **kwargs) -> Self:
        """
        Create a new community using the given Discord guild as a base.
        """
        self = await cls.create(bot, **kwargs)
        await self.attach_discord(guild)
        return self

    @classmethod
    async def create_from_twitch(cls, bot: LionBot, user: twitchio.User, **kwargs) -> Self:
        """
        Create a new profile using the given Twitch channel user as a base.
        """
        self = await cls.create(bot, **kwargs)
        await self.attach_twitch(user)
        return self
