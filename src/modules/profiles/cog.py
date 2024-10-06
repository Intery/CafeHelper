import asyncio
from enum import Enum
from typing import Optional, overload
from datetime import timedelta

import discord
from discord.ext import commands as cmds
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
                await source_profile.update(migrate=target_profile.profileid)
                results.append("Marking old profile as migrated.. finished!")
        return results

    async def fetch_profile_by_id(self, profile_id: int) -> UserProfile:
        """
        Fetch a UserProfile by the given id.
        """
        return await UserProfile.fetch_profile(self.bot, profile_id=profile_id)

    async def fetch_profile_discord(self, user: discord.Member | discord.User) -> UserProfile:
        """
        Fetch or create a UserProfile from the provided discord account.
        """
        profile = await UserProfile.fetch_from_discordid(user.id)
        if profile is None:
            profile = await UserProfile.create_from_discord(user)
        return profile

    async def fetch_profile_twitch(self, user: twitchio.User) -> UserProfile:
        """
        Fetch or create a UserProfile from the provided twitch account.
        """
        profile = await UserProfile.fetch_from_twitchid(user.id)
        if profile is None:
            profile = await UserProfile.create_from_twitch(user)
        return profile

    async def fetch_community_discord(self, guildid: int, create=True):
        ...

    async def fetch_community_twitch(self, guildid: int, create=True):
        ...

    async def fetch_community(self, communityid: int):
        ...

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
                content=f"Successfully connect to Twitch profile **{user.name}**! There was no profile data to merge."
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
                "**Successfully linked account and merge profile data!**"
            ))
            await message.edit(content=content)
