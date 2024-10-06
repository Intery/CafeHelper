import asyncio
from enum import Enum
from typing import Optional, overload
from datetime import timedelta

import discord
from discord import app_commands as appcmds
from discord.ext import commands as cmds
from twitchAPI.type import AuthScope
import twitchio
from twitchio.ext import commands
from twitchio import User
from twitchAPI.object.api import TwitchUser


from data.queries import ORDER
from meta import LionCog, LionBot, CrocBot, LionContext
from meta.logger import log_wrap
from utils.lib import utc_now
from . import logger
from .data import ProfileData
from .profile import UserProfile
from .community import Community


class ProfileCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot

        assert bot.crocbot is not None
        self.crocbot: CrocBot = bot.crocbot
        self.data = bot.db.load_registry(ProfileData())

        self._profile_migrators = {}
        self._comm_migrators = {}

    async def cog_load(self):
        await self.data.init()

    async def cog_check(self, ctx):
        return True

    # Profile API
    def add_profile_migrator(self, migrator, name=None):
        name = name or migrator.__name__
        self._profile_migrators[name or migrator.__name__] = migrator

        logger.info(
            f"Added user profile migrator {name}: {migrator}"
        )
        return migrator

    def del_profile_migrator(self, name: str):
        migrator = self._profile_migrators.pop(name, None)

        logger.info(
            f"Removed user profile migrator {name}: {migrator}"
        )

    @log_wrap(action="profile migration")
    async def migrate_profile(self, source_profile, target_profile) -> list[str]:
        logger.info(
            f"Beginning user profile migration from {source_profile!r} to {target_profile!r}"
        )
        results = []
        # Wrap this in a transaction so if something goes wrong with migration,
        # we roll back safely (although this may mess up caches)
        async with self.bot.db.connection() as conn:
            self.bot.db.conn = conn
            async with conn.transaction():
                for name, migrator in self._profile_migrators.items():
                    try:
                        result = await migrator(source_profile, target_profile)
                        if result:
                            results.append(result)
                    except Exception:
                        logger.exception(
                            f"Unexpected exception running user profile migrator {name} "
                            f"migrating {source_profile!r} to {target_profile!r}."
                        )
                        raise

                # Move all Discord and Twitch profile references over to the new profile
                discord_rows = await self.data.DiscordProfileRow.table.update_where(
                    profileid=source_profile.profileid
                ).set(profileid=target_profile.profileid)
                results.append(f"Migrated {len(discord_rows)} attached discord account(s).")

                twitch_rows = await self.data.TwitchProfileRow.table.update_where(
                    profileid=source_profile.profileid
                ).set(profileid=target_profile.profileid)
                results.append(f"Migrated {len(twitch_rows)} attached twitch account(s).")

                # And then mark the old profile as migrated
                await source_profile.update(migrated=target_profile.profileid)
                results.append("Marking old profile as migrated.. finished!")
        return results

    async def fetch_profile_by_id(self, profile_id: int) -> UserProfile:
        """
        Fetch a UserProfile by the given id.
        """
        return await UserProfile.fetch(self.bot, profile_id=profile_id)

    async def fetch_profile_discord(self, user: discord.Member | discord.User) -> UserProfile:
        """
        Fetch or create a UserProfile from the provided discord account.
        """
        profile = await UserProfile.fetch_from_discordid(self.bot, user.id)
        if profile is None:
            profile = await UserProfile.create_from_discord(self.bot, user)
        return profile

    async def fetch_profile_twitch(self, user: twitchio.User) -> UserProfile:
        """
        Fetch or create a UserProfile from the provided twitch account.
        """
        profile = await UserProfile.fetch_from_twitchid(self.bot, user.id)
        if profile is None:
            profile = await UserProfile.create_from_twitch(self.bot, user)
        return profile

    # Community API
    def add_community_migrator(self, migrator, name=None):
        name = name or migrator.__name__
        self._comm_migrators[name or migrator.__name__] = migrator

        logger.info(
            f"Added community migrator {name}: {migrator}"
        )
        return migrator

    def del_community_migrator(self, name: str):
        migrator = self._comm_migrators.pop(name, None)

        logger.info(
            f"Removed community migrator {name}: {migrator}"
        )

    @log_wrap(action="community migration")
    async def migrate_community(self, source_comm, target_comm) -> list[str]:
        logger.info(
            f"Beginning community migration from {source_comm!r} to {target_comm!r}"
        )
        results = []
        # Wrap this in a transaction so if something goes wrong with migration,
        # we roll back safely (although this may mess up caches)
        async with self.bot.db.connection() as conn:
            self.bot.db.conn = conn
            async with conn.transaction():
                for name, migrator in self._comm_migrators.items():
                    try:
                        result = await migrator(source_comm, target_comm)
                        if result:
                            results.append(result)
                    except Exception:
                        logger.exception(
                            f"Unexpected exception running community migrator {name} "
                            f"migrating {source_comm!r} to {target_comm!r}."
                        )
                        raise

                # Move all Discord and Twitch community preferences over to the new profile
                discord_rows = await self.data.DiscordCommunityRow.table.update_where(
                    profileid=source_comm.communityid
                ).set(communityid=target_comm.communityid)
                results.append(f"Migrated {len(discord_rows)} attached discord guilds.")

                twitch_rows = await self.data.TwitchCommunityRow.table.update_where(
                    communityid=source_comm.communityid
                ).set(communityid=target_comm.communityid)
                results.append(f"Migrated {len(twitch_rows)} attached twitch channel(s).")

                # And then mark the old community as migrated
                await source_comm.update(migrated=target_comm.communityid)
                results.append("Marking old community as migrated.. finished!")
        return results

    async def fetch_community_by_id(self, community_id: int) -> Community:
        """
        Fetch a Community by the given id.
        """
        return await Community.fetch(self.bot, community_id=community_id)

    async def fetch_community_discord(self, guild: discord.Guild) -> Community:
        """
        Fetch or create a Community from the provided discord guild.
        """
        comm = await Community.fetch_from_discordid(self.bot, guild.id)
        if comm is None:
            comm = await Community.create_from_discord(self.bot, guild)
        return comm

    async def fetch_community_twitch(self, user: twitchio.User) -> Community:
        """
        Fetch or create a Community from the provided twitch account.
        """
        community = await Community.fetch_from_twitchid(self.bot, user.id)
        if community is None:
            community = await Community.create_from_twitch(self.bot, user)
        return community

    # ----- Profile Commands -----
    @cmds.hybrid_group(
        name='profiles',
        description="Base comand group for user profiles."
    )
    async def profiles_grp(self, ctx: LionContext):
        ...

    @profiles_grp.group(
        name='link',
        description="Base command group for linking profiles"
    )
    async def profiles_link_grp(self, ctx: LionContext):
        ...

    @profiles_link_grp.command(
        name='twitch',
        description="Link a twitch account to your current profile."
    )
    async def profiles_link_twitch_cmd(self, ctx: LionContext):
        if not ctx.interaction:
            return

        await ctx.interaction.response.defer(ephemeral=True)

        # Ask the user to go through auth to get their userid
        auth_cog = self.bot.get_cog('TwitchAuthCog')
        flow = await auth_cog.start_auth()
        message = await ctx.reply(
            f"Please [click here]({flow.auth.return_auth_url()}) to link your profile "
            "to Twitch."
        )
        authrow = await flow.run()
        await message.edit(
            content="Authentication Complete! Beginning profile merge..."
        )

        results = await self.crocbot.fetch_users(ids=[authrow.userid])
        if not results:
            logger.error(
                f"User {authrow} obtained from Twitch authentication does not exist."
            )
            await ctx.error_reply("Sorry, something went wrong. Please try again later!")
            return

        user = results[0]

        # Retrieve author's profile if it exists
        author_profile = await UserProfile.fetch_from_discordid(self.bot, ctx.author.id)

        # Check if the twitch-side user has a profile 
        source_profile = await UserProfile.fetch_from_twitchid(self.bot, user.id)

        if author_profile and source_profile is None:
            # All we need to do is attach the twitch row
            await author_profile.attach_twitch(user)
            await message.edit(
                content=f"Successfully added Twitch account **{user.name}**! There was no profile data to merge."
            )
        elif source_profile and author_profile is None:
            # Attach the discord row to the profile
            await source_profile.attach_discord(ctx.author)
            await message.edit(
                content=f"Successfully connected to Twitch profile **{user.name}**! There was no profile data to merge."
            )
        elif source_profile is None and author_profile is None:
            profile = await UserProfile.create_from_discord(self.bot, ctx.author)
            await profile.attach_twitch(user)

            await message.edit(
                content=f"Opened a new user profile for you and linked Twitch account **{user.name}**."
            )
        elif author_profile.profileid == source_profile.profileid:
            await message.edit(
                content=f"The Twitch account **{user.name}** is already linked to your profile!"
            )
        else:
            # Migrate the existing profile data to the new profiles
            try:
                results = await self.migrate_profile(source_profile, author_profile)
            except Exception:
                await ctx.error_reply(
                    "An issue was encountered while merging your account profiles!\n"
                    "Migration rolled back, no data has been lost.\n"
                    "The developer has been notified. Please try again later!"
                )
                raise

            content = '\n'.join((
                "## Connecting Twitch account and merging profiles...",
                *results,
                "**Successfully linked account and merged profile data!**"
            ))
            await message.edit(content=content)

    # ----- Community Commands -----
    @cmds.hybrid_group(
        name='community',
        description="Base comand group for community profiles."
    )
    async def community_grp(self, ctx: LionContext):
        ...

    @community_grp.group(
        name='link',
        description="Base command group for linking communities"
    )
    async def community_link_grp(self, ctx: LionContext):
        ...

    @community_link_grp.command(
        name='twitch',
        description="Link a twitch account to this community."
    )
    @appcmds.guild_only()
    @appcmds.default_permissions(manage_guild=True)
    async def comm_link_twitch_cmd(self, ctx: LionContext):
        if not ctx.interaction:
            return
        assert ctx.guild is not None

        await ctx.interaction.response.defer(ephemeral=True)

        if not ctx.author.guild_permissions.manage_guild:
            await ctx.error_reply("You need the `MANAGE_GUILD` permission to link this guild to a community.")
            return

        # Ask the user to go through auth to get their userid
        auth_cog = self.bot.get_cog('TwitchAuthCog')
        flow = await auth_cog.start_auth(
            scopes=[
                AuthScope.CHAT_EDIT,
                AuthScope.CHAT_READ,
                AuthScope.MODERATION_READ,
                AuthScope.CHANNEL_BOT,
            ]
        )
        message = await ctx.reply(
            f"Please [click here]({flow.auth.return_auth_url()}) to link your Twitch channel to this server."
        )
        authrow = await flow.run()
        await message.edit(
            content="Authentication Complete! Beginning community profile merge..."
        )

        results = await self.crocbot.fetch_users(ids=[authrow.userid])
        if not results:
            logger.error(
                f"User {authrow} obtained from Twitch authentication does not exist."
            )
            await ctx.error_reply("Sorry, something went wrong. Please try again later!")
            return

        user = results[0]

        # Retrieve author's profile if it exists
        guild_comm = await Community.fetch_from_discordid(self.bot, ctx.guild.id)

        # Check if the twitch-side user has a profile 
        twitch_comm = await Community.fetch_from_twitchid(self.bot, user.id)

        if guild_comm and twitch_comm is None:
            # All we need to do is attach the twitch row
            await guild_comm.attach_twitch(user)
            await message.edit(
                content=f"Successfully linked Twitch channel **{user.name}**! There was no community data to merge."
            )
        elif twitch_comm and guild_comm is None:
            # Attach the discord row to the profile
            await twitch_comm.attach_discord(ctx.guild)
            await message.edit(
                content=f"Successfully connected to Twitch channel **{user.name}**!"
            )
        elif twitch_comm is None and guild_comm is None:
            profile = await Community.create_from_discord(self.bot, ctx.guild)
            await profile.attach_twitch(user)

            await message.edit(
                content=f"Created a new community for this server and linked Twitch account **{user.name}**."
            )
        elif guild_comm.communityid == twitch_comm.communityid:
            await message.edit(
                content=f"This server is already linked to the Twitch channel **{user.name}**!"
            )
        else:
            # Migrate the existing profile data to the new profiles
            try:
                results = await self.migrate_community(twitch_comm, guild_comm)
            except Exception:
                await ctx.error_reply(
                    "An issue was encountered while merging your community profiles!\n"
                    "Migration rolled back, no data has been lost.\n"
                    "The developer has been notified. Please try again later!"
                )
                raise

            content = '\n'.join((
                "## Connecting Twitch account and merging community profiles...",
                *results,
                "**Successfully linked account and merged community data!**"
            ))
            await message.edit(content=content)
