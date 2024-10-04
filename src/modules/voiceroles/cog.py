from collections import defaultdict
from typing import Optional
import asyncio
from cachetools import FIFOCache
from weakref import WeakValueDictionary

import discord
from discord.abc import GuildChannel
from discord.ext import commands as cmds
from discord import app_commands as appcmds

from meta import LionBot, LionCog, LionContext
from meta.logger import log_wrap
from meta.errors import ResponseTimedOut, SafeCancellation, UserInputError
from utils.ui import Confirm

from . import logger
from .data import VoiceRoleData


class VoiceRoleCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.data = bot.db.load_registry(VoiceRoleData())

        self._event_locks: WeakValueDictionary[tuple[int, int], asyncio.Lock] = WeakValueDictionary()

    async def cog_load(self):
        await self.data.init()

    @LionCog.listener('on_voice_state_update')
    @log_wrap(action='Voice Role Update')
    async def voicerole_update(self, member: discord.Member,
                               before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        after_channel = after.channel
        before_channel = before.channel
        if after_channel == before_channel:
            return

        task_key = (member.guild.id, member.id)
        async with self.event_lock(task_key):
            # Get the roles of the channel they left to remove
            # Get the roles of the channel they are joining to add
            # Use a set difference to remove the roles to be added from the ones to remove
            if before_channel is not None:
                leaving_roles = await self.get_roles_for(before_channel.id)
            else:
                leaving_roles = []

            if after_channel is not None:
                gaining_roles = await self.get_roles_for(after_channel.id)
            else:
                gaining_roles = []

            to_remove = []
            for role in leaving_roles:
                if role in member.roles and role not in gaining_roles and role.is_assignable():
                    to_remove.append(role)

            to_add = []
            for role in gaining_roles:
                if role not in member.roles and role.is_assignable():
                    to_add.append(role)

            if to_remove:
                await member.remove_roles(*to_remove, reason="Removing voice channel associated roles.")
            if to_add:
                await member.add_roles(*to_add, reason="Adding voice channel associated roles.")

            logger.info(
                    f"Voice roles removed {len(to_remove)} roles "
                    f"and added {len(to_add)} roles to <uid: {member.id}>"
            )

    async def get_roles_for(self, channelid: int) -> list[discord.Role]:
        """
        Get the voice roles associated to the given channel, as a list.

        Returns an empty list if there are no associated voice roles.
        """
        rows = await self.data.VoiceRole.fetch_where(channelid=channelid)
        channel = self.bot.get_channel(channelid)
        if not channel:
            raise ValueError("Provided voice role target channel is not in cache.")

        target_roles = []
        for row in rows:
            role = channel.guild.get_role(row.roleid)
            if role is not None:
                target_roles.append(role)

        return target_roles

    def event_lock(self, key) -> asyncio.Lock:
        """
        Get an asyncio.Lock for the given key.

        Guarantees sequential event handling.
        """
        lock = self._event_locks.get(key, None)
        if lock is None:
            lock = self._event_locks[key] = asyncio.Lock()
        logger.debug(f"Getting video event lock {key} (locked: {lock.locked()})")
        return lock


    # -------- Commands --------
    @cmds.hybrid_group(
        name='voiceroles',
        description="Base command group for voice channel -> role associationes."
    )
    @appcmds.default_permissions(manage_channels=True)
    async def voicerole_group(self, ctx: LionContext):
        ...

    @voicerole_group.command(
        name="link",
        description="Link a given voice channel with a given role."
    )
    @appcmds.describe(
        channel="The voice channel to link.",
        role="The associated role to give to members joining the voice channel."
    )
    async def voicerole_link(self, ctx: LionContext,
                             channel: discord.VoiceChannel,
                             role: discord.Role):
        if not ctx.interaction:
            return
        if not channel.permissions_for(ctx.author).manage_channels:
            await ctx.error_reply(f"You don't have the manage channels permission in {channel.mention}")
            return
        if not ctx.author.guild_permissions.manage_roles or not (role < ctx.author.top_role):
            await ctx.error_reply(f"You don't have the permission to manage this role!")
            return

        await self.data.VoiceRole.table.insert(channelid=channel.id, roleid=role.id)
        await ctx.reply("Voice role associated!")

    @voicerole_group.command(
        name="unlink",
        description="Unlink a given voice channel from a given role."
    )
    @appcmds.describe(
        channel="The voice channel to unlink.",
        role="The role to remove from this voice channel."
    )
    async def voicerole_unlink(self, ctx: LionContext,
                               channel: discord.VoiceChannel,
                               role: discord.Role):
        if not ctx.interaction:
            return
        if not channel.permissions_for(ctx.author).manage_channels:
            await ctx.error_reply(f"You don't have the manage channels permission in {channel.mention}")
            return
        if not ctx.author.guild_permissions.manage_roles or not (role < ctx.author.top_role):
            await ctx.error_reply(f"You don't have the permission to manage this role!")
            return

        await self.data.VoiceRole.table.delete_where(channelid=channel.id, roleid=role.id)
        await ctx.reply("Voice role disassociated!")

    # TODO: Display and visual editing of roles.

