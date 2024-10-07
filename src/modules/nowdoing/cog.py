import asyncio
import datetime as dt
import json
import os
from typing import Optional

import discord
from discord.ext import commands as cmds
from discord import app_commands as appcmds

import twitchio
from twitchio.ext import commands

from meta import CrocBot, LionCog, LionContext, LionBot
from meta.sockets import Channel, register_channel
from utils.lib import strfdelta, utc_now
from . import logger
from .data import NowListData

from modules.profiles.profile import UserProfile


class NowDoingChannel(Channel):
    name = 'NowList'

    def __init__(self, cog: 'NowDoingCog', **kwargs):
        self.cog = cog
        super().__init__(**kwargs)

    async def on_connection(self, websocket, event):
        await super().on_connection(websocket, event)
        await self.reload_tasklist(websocket=websocket)

    def task_args(self, task: NowListData.Task):
        return (
            task.userid,
            task.name,
            task.task,
            task.started_at.isoformat(),
            task.done_at.isoformat() if task.done_at else None,
        )

    async def reload_tasklist(self, websocket=None):
        """
        Clear tasklist and re-send current tasks.
        """
        await self.send_clear(websocket=websocket)
        for task in self.cog.tasks.values():
            await self.send_set(*self.task_args(task), websocket=websocket)

    async def send_set(self, userid, name, task, start_at, end_at, websocket=None):
        await self.send_event({
            'type': "DO",
            'method': "setTask",
            'args': {
                'userid': userid,
                'name': name,
                'task': task,
                'start_at': start_at,
                'end_at': end_at,
            }
        }, websocket=websocket)

    async def send_del(self, userid, websocket=None):
        await self.send_event({
            'type': "DO",
            'method': "delTask",
            'args': {
                'userid': userid,
            }
        }, websocket=websocket)

    async def send_clear(self, websocket=None):
        await self.send_event({
            'type': "DO",
            'method': "clearTasks",
            'args': {
            }
        }, websocket=websocket)


class NowDoingCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.crocbot: CrocBot = bot.crocbot
        self.data = bot.db.load_registry(NowListData())
        self.channel = NowDoingChannel(self)
        register_channel(self.channel.name, self.channel)

        # userid -> Task
        self.tasks: dict[int, NowListData.Task] = {}

        self.loaded = asyncio.Event()

    async def cog_load(self):
        await self.data.init()
        await self.load_tasks()

        self.bot.get_cog('ProfileCog').add_profile_migrator(self.migrate_profiles, name='task-migrator')

        self._load_twitch_methods(self.crocbot)
        self.loaded.set()

    async def cog_unload(self):
        self.loaded.clear()
        self.tasks.clear()
        if profiles := self.bot.get_cog('ProfileCog'):
            profiles.del_profile_migrator('task-migrator')
        self._unload_twitch_methods(self.crocbot)

    async def migrate_profiles(self, source_profile: UserProfile, target_profile: UserProfile):
        """
        Move current source task to target profile if there's room for it, otherwise annihilate
        """
        await self.load_tasks()
        source_task = self.tasks.pop(source_profile.profileid, None)

        results = ["(Tasklist)"]

        if source_task:
            target_task = self.tasks.get(target_profile.profileid, None)
            if target_task and (target_task.is_done or target_task.started_at < source_task.started_at):
                # If target is done, remove it so we can overwrite
                results.append("Removed older task from target profile.")
                await target_task.delete()
                target_task = None

            if not target_task:
                # Update source task with new profile id
                await source_task.update(userid=target_profile.profileid)
                target_task = source_task
                await self.channel.send_set(*self.channel.task_args(target_task))
                results.append("Migrated 1 currently running task from source profile.")
            else:
                # If there is a target task we can't overwrite, just delete the source task
                await source_task.delete()
                results.append("Ignoring and removing older task from source profile.")

            self.tasks.pop(source_profile.profileid, None)
            await self.channel.send_del(source_profile.profileid)
        else:
            results.append("No running task in source profile, nothing to migrate!")
        await self.load_tasks()

        return ' '.join(results)

    async def user_profile_migration(self):
        """
        Manual single-use migration method from the old userid format to the new profileid format.
        """
        await self.load_tasks()
        for userid, task in self.tasks.items():
            userid = int(userid)
            if userid > 1000:
                # Assume it is a twitch userid
                profile = await UserProfile.fetch_from_twitchid(self.bot, userid)

                if not profile:
                    # Create a new profile with this twitch user
                    users = await self.crocbot.fetch_users(ids=[userid])
                    if not users:
                        continue
                    user = users[0]
                    profile = await UserProfile.create_from_twitch(self.bot, user)

                if not await self.data.Task.fetch(profile.profileid):
                    await task.update(userid=profile.profileid)
                else:
                    await task.delete()
        await self.load_tasks()
        await self.channel.reload_tasklist()

    async def cog_check(self, ctx):
        if not self.loaded.is_set():
            await ctx.reply("Tasklists are still loading! Please wait a moment~")
            return False
        return True

    async def load_tasks(self):
        tasklist = await self.data.Task.fetch_where()
        tasks = {task.userid: task for task in tasklist}
        self.tasks = tasks
        logger.info(f"Loaded {len(tasks)} from database.")

    @commands.command()
    async def test(self, ctx: commands.Context):
        if (ctx.author.is_broadcaster):
            # await self.channel.send_test_set()
            # await ctx.send(f"Hello {ctx.author.name}! This command does something, we aren't sure what yet.")
            # await ctx.send(str(list(self.tasks.items())[0]))
            await self.user_profile_migration()
            await ctx.send(str(ctx.author.id))
            await ctx.reply("Userid -> profile migration done.")
        else:
            await ctx.send(f"Hello {ctx.author.name}! I don't think you have permission to test that.")

    async def now(self, ctx: commands.Context | LionContext, profile: UserProfile, args: Optional[str] = None):
        args = args.strip() if args else None
        userid = profile.profileid
        if args:
            await self.data.Task.table.delete_where(userid=userid)
            task = await self.data.Task.create(
                userid=userid,
                name=ctx.author.display_name,
                task=args,
                started_at=utc_now(),
            )
            self.tasks[task.userid] = task
            await self.channel.send_set(*self.channel.task_args(task))
            await ctx.send("Updated your current task, good luck!")
        elif task := self.tasks.get(userid, None):
            if task.is_done:
                done_ago = strfdelta(utc_now() - task.done_at)
                await ctx.send(
                    f"You finished '{task.task}' {done_ago} ago!"
                )
            else:
                started_ago = strfdelta(utc_now() - task.started_at)
                await ctx.send(
                    f"You have been working on '{task.task}' for {started_ago}!"
                )
        else:
            await ctx.send(
                "You don't have a task on the tasklist! "
                "Show what you are currently working on with, e.g. !now Reading notes"
            )

    @commands.command(
        name='now',
        aliases=['task', 'check']
    )
    async def twi_now(self, ctx: commands.Context, *, args: Optional[str] = None):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_twitch(ctx.author)
        await self.now(ctx, profile, args)

    @cmds.hybrid_command(
        name='now',
        aliases=['task', 'check']
    )
    async def disc_now(self, ctx: LionContext, *, args: Optional[str] = None):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_discord(ctx.author)
        await self.now(ctx, profile, args)

    async def nownext(self, ctx: commands.Context | LionContext, profile: UserProfile, args: Optional[str]): 
        userid = profile.profileid
        task = self.tasks.get(userid, None)
        if args:
            if task:
                if not task.is_done:
                    await task.update(done_at=utc_now())
                started_ago = strfdelta(task.done_at - task.started_at)
                prefix = (
                    f"You worked on '{task.task}' for {started_ago}."
                )
            else:
                prefix = ""
            await self.data.Task.table.delete_where(userid=userid)
            task = await self.data.Task.create(
                userid=userid,
                name=ctx.author.display_name,
                task=args,
                started_at=utc_now(),
            )
            self.tasks[task.userid] = task
            await self.channel.send_set(*self.channel.task_args(task))
            await ctx.send("Next task set, good luck!" + ' ' + prefix)
        elif task:
            if task.is_done:
                done_ago = strfdelta(utc_now() - task.done_at)
                await ctx.send(
                    f"You finished '{task.task}' {done_ago} ago!"
                )
            else:
                started_ago = strfdelta(utc_now() - task.started_at)
                await ctx.send(
                    f"You have been working on '{task.task}' for {started_ago}!"
                )
        else:
            await ctx.send(
                "You don't have a task on the tasklist! "
                "Show what you are currently working on with, e.g. !now Reading notes"
            )

    @commands.command(
        name='next',
    )
    async def twi_next(self, ctx: commands.Context, *, args: Optional[str] = None):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_twitch(ctx.author)
        await self.nownext(ctx, profile, args)

    @cmds.hybrid_command(
        name='next',
    )
    async def disc_next(self, ctx: LionContext, *, args: Optional[str] = None):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_discord(ctx.author)
        await self.nownext(ctx, profile, args)

    async def done(self, ctx: commands.Context | LionContext, profile: UserProfile):
        userid = profile.profileid
        if task := self.tasks.get(userid, None):
            if task.is_done:
                await ctx.send(
                    f"You already finished '{task.task}'!"
                )
            else:
                await task.update(done_at=utc_now())
                started_ago = strfdelta(task.done_at - task.started_at)
                await self.channel.send_set(*self.channel.task_args(task))
                await ctx.send(
                    f"Good job finishing '{task.task}'! "
                    f"You worked on it for {started_ago}."
                )
        else:
            await ctx.send(
                "You don't have a task on the tasklist! "
                "Show what you are currently working on with, e.g. !now Reading notes"
            )

    @commands.command(
        name='done',
    )
    async def twi_done(self, ctx: commands.Context):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_twitch(ctx.author)
        await self.done(ctx, profile)

    @cmds.hybrid_command(
        name='done',
    )
    async def disc_done(self, ctx: LionContext):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_discord(ctx.author)
        await self.done(ctx, profile)

    @commands.command(
        name='clear',
    )
    async def twi_clear(self, ctx: commands.Context):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_twitch(ctx.author)
        await self.clear(ctx, profile)

    @cmds.hybrid_command(
        name='clear',
    )
    async def disc_clear(self, ctx: LionContext):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_discord(ctx.author)
        await self.clear(ctx, profile)

    async def clear(self, ctx: commands.Context | LionContext, profile):
        userid = profile.profileid
        if task := self.tasks.pop(userid, None):
            await task.delete()
            await self.channel.send_del(userid)
            await ctx.send("Removed your task from the tasklist!")
        else:
            await ctx.send(
                "You don't have a task on the tasklist at the moment!"
            )

    @commands.command()
    async def clearfor(self, ctx: commands.Context, user: twitchio.User):
        if (ctx.author.is_mod or ctx.author.is_broadcaster):
            await self.channel.send_del(int(user.id))
            task = self.tasks.pop(int(user.id), None)
            if task is not None:
                await task.delete()
            await ctx.send("Cleared the task.")
        else:
            pass

    @commands.command()
    async def clearall(self, ctx: commands.Context):
        if (ctx.author.is_mod or ctx.author.is_broadcaster):
            await self.data.Task.table.delete_where()
            self.tasks.clear()
            await self.channel.send_clear()
            await ctx.send("Tasklist Cleared!")
