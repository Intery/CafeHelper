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
from .data import CounterData


class PERIOD(Enum):
    ALL = ('', 'all', 'all-time')
    STREAM = ('this stream', 'stream',)
    DAY = ('today', 'd', 'day', 'today', 'daily')
    WEEK = ('this week', 'w', 'week', 'weekly')
    MONTH = ('this month', 'm', 'mo', 'month', 'monthly')
    YEAR = ('this year', 'y', 'year', 'yearly')


class CounterCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.crocbot: CrocBot = bot.crocbot
        self.data = bot.db.load_registry(CounterData())

        self.loaded = asyncio.Event()

        # Cache of counter names -> rows
        self.counters = {}

    async def cog_load(self):
        self._load_twitch_methods(self.crocbot)

        await self.data.init()
        await self.load_counters()
        self.loaded.set()

    async def cog_unload(self):
        self._unload_twitch_methods(self.crocbot)

    async def cog_check(self, ctx):
        return True

    async def load_counters(self):
        """
        Initialise counter name cache.
        """
        rows = await self.data.Counter.fetch_where()
        self.counters = {row.name: row for row in rows}
        logger.info(
            f"Loaded {len(self.counters)} counters."
        )

    # Counters API

    async def fetch_counter(self, counter: str) -> CounterData.Counter:
        """
        Fetches the Counter with the given name,
        or creates it if it doesn't exist.
        """
        if (row := self.counters.get(counter, None)) is None:
            row = await self.data.Counter.fetch_or_create(name=counter)
            self.counters[counter] = row
        return row

    async def delete_counter(self, counter: str):
        self.counters.pop(counter, None)
        await self.data.Counter.table.delete_where(name=counter)

    async def reset_counter(self, counter: str):
        row = self.counters.get(counter, None)
        if row:
            await self.data.CounterEntry.table.delete_where(counterid=row.counterid)

    async def add_to_counter(self, counter: str, userid: int, value: int, context: Optional[str]=None):
        row = await self.fetch_counter(counter)
        return await self.data.CounterEntry.create(
            counterid=row.counterid,
            userid=userid,
            value=value,
            context_str=context
        )

    async def leaderboard(self, counter: str, start_time=None):
        row = await self.fetch_counter(counter)
        query = self.data.CounterEntry.table.select_where(counterid=row.counterid)
        query.select('userid', user_total="SUM(value)")
        query.group_by('userid')
        query.order_by('user_total', ORDER.DESC)
        if start_time is not None:
            query.where(self.data.CounterEntry.created_at >= start_time)
        query.with_no_adapter()
        results = await query
        lb = {result['userid']: result['user_total'] for result in results}

        return lb

    async def personal_total(self, counter: str, userid: int):
        row = await self.fetch_counter(counter)
        query = self.data.CounterEntry.table.select_where(counterid=row.counterid, userid=userid)
        query.select(user_total="SUM(value)")
        query.with_no_adapter()
        results = await query
        return results[0]['user_total'] if results else 0

    async def totals(self, counter):
        row = await self.fetch_counter(counter)
        query = self.data.CounterEntry.table.select_where(counterid=row.counterid)
        query.select(counter_total="SUM(value)")
        query.with_no_adapter()
        results = await query
        return results[0]['counter_total'] if results else 0

    # Counters commands
    @commands.command()
    async def counter(self, ctx: commands.Context, name: str, subcmd: Optional[str], *, args: Optional[str]=None):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        name = name.lower()

        if subcmd is None or subcmd == 'show':
            # Show
            total = await self.totals(name)
            await ctx.reply(f"'{name}' counter is: {total}")
        elif subcmd == 'add':
            if args is None:
                value = 1
            else:
                try:
                    value = int(args)
                except ValueError:
                    await ctx.reply(f"Could not parse value to add.")
                    return
            await self.add_to_counter(
                name,
                int(ctx.author.id),
                value,
                context='cmd: counter add'
            )
            total = await self.totals(name)
            await ctx.reply(f"'{name}' counter is now: {total}")
        elif subcmd == 'lb':
            user = await ctx.channel.user()
            lbstr = await self.formatted_lb(name, args or '', int(user.id))
            await ctx.reply(lbstr)
        elif subcmd == 'clear':
            await self.reset_counter(name)
            await ctx.reply(f"'{name}' counter reset.")
        else:
            await ctx.reply(f"Unrecognised subcommand {subcmd}. Supported subcommands: 'show', 'add', 'lb', 'clear'.")

    async def parse_period(self, userid: int, periodstr: str, default=PERIOD.STREAM):
        if periodstr:
            period = next((period for period in PERIOD if periodstr.lower() in period.value), None)
            if period is None:
                raise ValueError("Invalid period string provided")
        else:
            period = default

        now = utc_now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if period is PERIOD.ALL:
            start_time = None
        elif period is PERIOD.STREAM:
            streams = await self.crocbot.fetch_streams(user_ids=[userid])
            if streams:
                stream = streams[0]
                start_time = stream.started_at
            else:
                period = PERIOD.ALL
                start_time = None
        elif period is PERIOD.DAY:
            start_time = today
        elif period is PERIOD.WEEK:
            start_time = today - timedelta(days=today.weekday())
        elif period is PERIOD.MONTH:
            start_time = today.replace(day=1)
        elif period is PERIOD.YEAR:
            start_time = today.replace(day=1, month=1)
        else:
            period = PERIOD.ALL
            start_time = None

        return (period, start_time)

    async def formatted_lb(self, counter: str, periodstr: str, channelid: int):

        period, start_time = await self.parse_period(channelid, periodstr)

        lb = await self.leaderboard(counter, start_time=start_time)
        if lb:
            userids = list(lb.keys())
            users = await self.crocbot.fetch_users(ids=userids)
            name_map = {user.id: user.display_name for user in users}
            parts = []
            for userid, total in lb.items():
                name = name_map.get(userid, str(userid))
                part = f"{name}: {total}"
                parts.append(part)
            lbstr = '; '.join(parts)
            return f"{counter} {period.value[-1]} leaderboard --- {lbstr}"
        else:
            return f"{counter} {period.value[-1]} leaderboard is empty!"

    # Misc actual counter commands
    # TODO: Factor this out to a different module...
    @commands.command()
    async def tea(self, ctx: commands.Context, *, args: Optional[str]=None):
        userid = int(ctx.author.id)
        channelid = int((await ctx.channel.user()).id)
        period, start_time = await self.parse_period(channelid, '')
        counter = 'tea'

        await self.add_to_counter(
            counter,
            userid,
            1,
            context='cmd: tea'
        )
        lb = await self.leaderboard(counter, start_time=start_time)
        user_total = lb.get(userid, 0)
        total = sum(lb.values())
        await ctx.reply(f"Enjoy your tea! We have had {total} cups of tea {period.value[0]}.")
        
    @commands.command()
    async def tealb(self, ctx: commands.Context, *, args: str = ''):
        user = await ctx.channel.user()
        await ctx.reply(await self.formatted_lb('tea', args, int(user.id)))

    @commands.command()
    async def coffee(self, ctx: commands.Context, *, args: Optional[str]=None):
        userid = int(ctx.author.id)
        channelid = int((await ctx.channel.user()).id)
        period, start_time = await self.parse_period(channelid, '')
        counter = 'coffee'

        await self.add_to_counter(
            counter,
            userid,
            1,
            context='cmd: coffee'
        )
        lb = await self.leaderboard(counter, start_time=start_time)
        user_total = lb.get(userid, 0)
        total = sum(lb.values())
        await ctx.reply(f"Enjoy your coffee! We have had {total} cups of coffee {period.value[0]}.")
        
    @commands.command()
    async def coffeelb(self, ctx: commands.Context, *, args: str = ''):
        user = await ctx.channel.user()
        await ctx.reply(await self.formatted_lb('coffee', args, int(user.id)))

    @commands.command()
    async def water(self, ctx: commands.Context, *, args: Optional[str]=None):
        userid = int(ctx.author.id)
        channelid = int((await ctx.channel.user()).id)
        period, start_time = await self.parse_period(channelid, '')
        counter = 'water'

        await self.add_to_counter(
            counter,
            userid,
            1,
            context='cmd: water'
        )
        lb = await self.leaderboard(counter, start_time=start_time)
        user_total = lb.get(userid, 0)
        total = sum(lb.values())
        await ctx.reply(f"Good job hydrating! We have had {total} cups of water {period.value[0]}.")

    @commands.command()
    async def waterlb(self, ctx: commands.Context, *, args: str = ''):
        user = await ctx.channel.user()
        await ctx.reply(await self.formatted_lb('water', args, int(user.id)))

    @commands.command()
    async def stuff(self, ctx: commands.Context, *, args: str = ''):
        await ctx.reply(f"Stuff {args}")

    @cmds.hybrid_command('water')
    async def d_water_cmd(self, ctx):
        await ctx.reply(repr(ctx))
