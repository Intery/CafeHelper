import asyncio
import datetime as dt
import json
import os
from typing import Optional

from attr import dataclass
import twitchio
from twitchio.ext import commands

from meta import CrocBot, LionCog
from meta.LionBot import LionBot
from meta.sockets import Channel, register_channel
from utils.lib import strfdelta, utc_now
from . import logger
from .data import NowListData


class NowDoingChannel(Channel):
    name = 'NowList'

    def __init__(self, cog: 'NowDoingCog', **kwargs):
        self.cog = cog
        super().__init__(**kwargs)

    async def on_connection(self, websocket, event):
        await super().on_connection(websocket, event)
        for task in self.cog.tasks.values():
            await self.send_set(*self.task_args(task), websocket=websocket)

    async def send_test_set(self):
        tasks = [
            (0, 'Tester0', "Testing Tasklist", True),
            (1, 'Tester1', "Getting Confused", False),
            (2, "Tester2", "Generating Bugs", True),
            (3, "Tester3", "Fixing Bugs", False),
            (4, "Tester4", "Pushing the red button", False),
        ]
        for task in tasks:
            await self.send_set(*task)

    def task_args(self, task: NowListData.Task):
        return (
            task.userid,
            task.name,
            task.task,
            task.started_at.isoformat(),
            task.done_at.isoformat() if task.done_at else None,
        )

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

    async def send_del(self, userid):
        await self.send_event({
            'type': "DO",
            'method': "delTask",
            'args': {
                'userid': userid,
            }
        })

    async def send_clear(self):
        await self.send_event({
            'type': "DO",
            'method': "clearTasks",
            'args': {
            }
        })


class NowDoingCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.crocbot = bot.crocbot
        self.data = bot.db.load_registry(NowListData())
        self.channel = NowDoingChannel(self)
        register_channel(self.channel.name, self.channel)

        # userid -> Task
        self.tasks: dict[int, NowListData.Task] = {}

        self.loaded = asyncio.Event()

    async def cog_load(self):
        await self.data.init()

        await self.load_tasks()

        self._load_twitch_methods(self.crocbot)
        self.loaded.set()

    async def cog_unload(self):
        self.loaded.clear()
        self.tasks.clear()
        self._unload_twitch_methods(self.crocbot)

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
            await ctx.send(str(ctx.author.id))
        else:
            await ctx.send(f"Hello {ctx.author.name}! I don't think you have permission to test that.")

    @commands.command(aliases=['task', 'check'])
    async def now(self, ctx: commands.Context, *, args: Optional[str] = None):
        userid = int(ctx.author.id)
        args = args.strip() if args else None
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
            await ctx.send(f"Updated your current task, good luck!")
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

    @commands.command(name='next')
    async def nownext(self, ctx: commands.Context, *, args: Optional[str] = None): 
        userid = int(ctx.author.id)
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
            await ctx.send(f"Next task set, good luck!" + ' ' + prefix)
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

    @commands.command()
    async def done(self, ctx: commands.Context):
        userid = int(ctx.author.id)
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

    @commands.command()
    async def clear(self, ctx: commands.Context):
        userid = int(ctx.author.id)
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
