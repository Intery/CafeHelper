import asyncio
import datetime as dt
from datetime import datetime, timedelta
import json
import os
from typing import Optional

import discord
from discord.ext import commands as cmds
from discord import app_commands as appcmds

import twitchio
from twitchio.ext import commands

from modules.profiles.profile import UserProfile

from meta import CrocBot, LionCog, LionContext, LionBot
from meta.sockets import Channel, register_channel
from utils.lib import strfdelta, utc_now
from . import logger
from .data import TaskData, TaskInfo
from .tasklist import Tasklist, TaskRegistry


class NowDoingChannel(Channel):
    name = 'NowList'

    def __init__(self, cog: 'NowDoingCog', **kwargs):
        self.cog = cog
        super().__init__(**kwargs)

    async def on_connection(self, websocket, event):
        await super().on_connection(websocket, event)
        await self.reload_tasklist(websocket=websocket)

    def task_args(self, task: TaskInfo, profile: UserProfile):
        if task.is_complete:
            fake_started_at = task.completed_at - timedelta(seconds=task.total_duration)
        else:
            fake_started_at = utc_now() - timedelta(seconds=task.total_duration)
        return (
            task.profileid,
            profile.profile_row.nickname or str(task.profileid),
            task.content,
            fake_started_at.isoformat(),
            task.completed_at.isoformat() if task.completed_at else None,
        )

    async def reload_tasklist(self, websocket=None):
        """
        Clear tasklist and re-send current tasks.
        """
        await self.send_clear(websocket=websocket)
        for task in await self.cog.tasker.get_nowlist():
            profile = await self.cog.bot.get_cog('ProfileCog').fetch_profile_by_id(task.profileid)
            await self.send_set(*self.task_args(task, profile), websocket=websocket)

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
        self.data = bot.db.load_registry(TaskData())
        self.tasker = TaskRegistry(self.data)
        self.channel = NowDoingChannel(self)
        register_channel(self.channel.name, self.channel)

        self.loaded = asyncio.Event()

    async def cog_load(self):
        await self.data.init()
        await self.tasker.setup()

        self.bot.get_cog('ProfileCog').add_profile_migrator(self.migrate_profiles, name='task-migrator')

        self._load_twitch_methods(self.crocbot)
        self.loaded.set()

    async def cog_unload(self):
        self.loaded.clear()
        if profiles := self.bot.get_cog('ProfileCog'):
            profiles.del_profile_migrator('task-migrator')
        self._unload_twitch_methods(self.crocbot)

    async def dispatch_update(self, tasklist: Tasklist, profile):
        current = tasklist.get_current()
        if current is None:
            await self.channel.send_del(tasklist.profileid)
        else:
            args = self.channel.task_args(current, profile)
            await self.channel.send_set(*args)

    async def migrate_profiles(self, source_profile: UserProfile, target_profile: UserProfile):
        # TODO
        """
        Move current source task to target profile if there's room for it, otherwise annihilate
        """
        results = ["(Tasklist)"]

        source_tasklist = await self.tasker.get_tasklist(source_profile.profileid)
        source_task = source_tasklist.get_current()
        await source_tasklist.unset_now()
        target_tasklist = await self.tasker.get_tasklist(target_profile.profileid)
        target_task = target_tasklist.get_current()
        await target_tasklist.unset_now()

        new_plan = (*source_tasklist.plan, *target_tasklist.plan)

        # Update all tasks in source list to target id.
        # Includes deleted tasks
        rows = await self.data.tasklist.update_where(
            profileid=source_profile.profileid
        ).set(profileid=target_profile.profileid)

        results.append(
            f"Migrated {len(rows)} tasks from source tasklist."
        )

        await target_tasklist.set_plan(*new_plan)
        # TODO: Something with profile settings

        if source_task:
            if target_task and (target_task.is_complete or target_task.started_at < source_task.started_at):
                # If target is done, remove it so we can overwrite
                results.append("Unset older running task from target tasklist.")
                target_task = None

            if not target_task:
                # Update source task with new profile id
                await target_tasklist.set_now(source_task.taskid)
                results.append("Migrated 1 currently running task from source tasklist.")
            else:
                # If there is a target task we can't overwrite, just delete the source task
                results.append("Ignoring older running task from source tasklist.")

        await self.dispatch_update(source_tasklist, source_profile)
        await self.dispatch_update(target_tasklist, target_profile)

        return ' '.join(results)

    async def cog_check(self, ctx):
        if not self.loaded.is_set():
            await ctx.reply("Tasklists are still loading! Please wait a moment~")
            return False
        return True

    async def now(self, ctx: commands.Context | LionContext, profile: UserProfile, args: Optional[str] = None):
        args = args.strip() if args else None
        profileid = profile.profileid

        tasklist = await self.tasker.get_tasklist(profileid)
        current = tasklist.get_current()

        if args:
            task, = await tasklist.create_tasks(args)
            await tasklist.set_now(task.taskid)
            await self.dispatch_update(tasklist, profile)
            await ctx.reply("Updated your current task, good luck!")
            # TODOv1: Add information about pushed back task
        elif current:
            if current.is_complete:
                done_ago = strfdelta(utc_now() - current.completed_at)
                await ctx.reply(f"You finished '{current.content}' {done_ago} ago!")
            else:
                started_ago = strfdelta(timedelta(seconds=current.total_duration))
                await ctx.reply(
                    f"You have been working on '{current.content}' for {started_ago}"
                )
        else:
            await ctx.reply(
                "You don't have a current task set! "
                "Show what you are working on with e.g. !now Reading notes"
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

    async def edit(self, ctx: commands.Context | LionContext, profile: UserProfile, args: Optional[str] = None):
        args = args.strip() if args else None
        profileid = profile.profileid

        tasklist = await self.tasker.get_tasklist(profileid)
        current = tasklist.get_current()

        if current:
            # Edit with new args
            await tasklist.edit_task(current.taskid, args)
            await self.dispatch_update(tasklist, profile)
            await ctx.reply("Updated your current task!")
        else:
            # Error with nothing to edit 
            # Will change for v1
            await ctx.reply(
                "You don't have a current task to edit! "
                "Show what you are working on with e.g. !now Reading notes"
            )

    @commands.command(
        name='edit',
    )
    async def twi_edit(self, ctx: commands.Context, *, args: Optional[str] = None):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_twitch(ctx.author)
        await self.edit(ctx, profile, args)

    @cmds.hybrid_command(
        name='edit',
    )
    async def disc_edit(self, ctx: LionContext, *, args: Optional[str] = None):
        profile = await self.bot.get_cog('ProfileCog').fetch_profile_discord(ctx.author)
        await self.edit(ctx, profile, args)

    async def nownext(self, ctx: commands.Context | LionContext, profile: UserProfile, args: Optional[str]): 
        if not args:
            await ctx.reply(
                f"Usage:{ctx.prefix}next <next task> "
                f"TIP: {ctx.prefix}next completes your current task and sets the given task as your new current task."
            )
            return

        args = args.strip() if args else None
        profileid = profile.profileid

        tasklist = await self.tasker.get_tasklist(profileid)
        current = tasklist.get_current()

        # Complete the current task if it exists
        if current and not current.is_complete:
            current, = await tasklist.complete_tasks(current.taskid)

        new_current, = await tasklist.create_tasks(args)
        await tasklist.set_now(new_current.taskid)

        await self.dispatch_update(tasklist, profile)
        if current:
            started_ago = strfdelta(timedelta(seconds=current.total_duration))
            await ctx.reply(
                "Completed your current task and started your next one! Good luck! "
                f"You worked on '{current.content}' for {started_ago}"
            )
        else:
            await ctx.reply(
                "Started your next task, good luck!"
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
        args = None

        # TODO: We can actually create the task here if it's not done.

        tasklist = await self.tasker.get_tasklist(profile.profileid)
        current = tasklist.get_current()

        if args:
            tasks = await tasklist.parse_taskspec(args)
        else:
            tasks = [current] if current else []

        if tasks:
            # Complete the tasks
            completed = await tasklist.complete_tasks(*[task.taskid for task in tasks])

            # Response depends on how many tasks were complete
            # Don't show if duration is less than 30 seconds
            if not completed:
                # No tasks were actually completed
                if len(tasks) > 1:
                    await ctx.reply("You already finished these tasks!")
                else:
                    task = tasks[0]
                    await ctx.reply(f"You already finished '{task.content}'")
            else:
                # Note that duration for completed tasks will always be correct
                duration = int(sum(task.duration for task in completed))
                durstr = strfdelta(timedelta(seconds=duration))
                if len(completed) == 1:
                    task = completed[0]
                    taskstr = f"Good work finishing '{task.content}'"
                    if duration > 60:
                        taskstr += f" You worked on it for {durstr}"
                        # TIP: Next task if plan
                        # Summary of remaining and done
                else:
                    taskstr = f"{len(completed)} more tasks completed, great work!"
                    if duration > 60:
                        taskstr += f" You worked on them for {durstr}"
                await self.dispatch_update(tasklist, profile)
                await ctx.reply(taskstr)
        elif args:
            await ctx.reply(f"'{args}' didn't match any tasks!")
        else:
            await ctx.reply(
                "You don't have a task on the tasklist! "
                f"Show what you are currently working on with, e.g., {ctx.prefix}now Reading Notes"
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
        profileid = profile.profileid

        tasklist = await self.tasker.get_tasklist(profileid)
        current = tasklist.get_current()

        if current:
            await tasklist.delete_tasks(current.taskid)
            await self.dispatch_update(tasklist, profile)
            await ctx.send("Deleted your current task!")
        else:
            await ctx.reply(
                "You don't have a current task set! "
                "Show what you are working on with e.g. !now Reading notes"
            )
