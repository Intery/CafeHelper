import asyncio
from enum import Enum
from typing import Optional
from datetime import timedelta

import discord
from discord.ext import commands as cmds
from discord import app_commands as appcmds

import twitchio
from twitchio.ext import commands


from data.queries import ORDER
from meta import LionCog, LionBot, CrocBot, LionContext
from modules.profiles.community import Community
from modules.profiles.profile import UserProfile
from utils.lib import utc_now, paginate_list, pager
from . import logger
from .data import CounterData


class PERIOD(Enum):
    ALL = ('', 'all', 'all-time')
    STREAM = ('this stream', 'stream',)
    DAY = ('today', 'd', 'day', 'today', 'daily')
    WEEK = ('this week', 'w', 'week', 'weekly')
    MONTH = ('this month', 'm', 'mo', 'month', 'monthly')
    YEAR = ('this year', 'y', 'year', 'yearly')


class ORIGIN(Enum):
    DISCORD = 'discord'
    TWITCH = 'twitch'


def counter_cmd_factory(
    counter: str,
    response: str,
    default_period: Optional[PERIOD] = PERIOD.STREAM,
    context: Optional[str] = None
):
    context = context or f"cmd: {counter}"
    async def counter_cmd(
        cog,
        ctx: commands.Context | LionContext,
        origin: ORIGIN,
        author: UserProfile,
        community: Community,
        args: Optional[str]
    ):
        userid = author.profileid
        period, start_time = await cog.parse_period(community, '', default=default_period)

        args = (args or '').strip(" 󠀀 ")
        splits = args.split(maxsplit=1)
        splits = [split.strip() for split in splits if split]

        details = None
        amount = 1
        
        if splits:
            if splits[0].isdigit() or (splits[0].startswith('-') and splits[0][1:].isdigit()):
                amount = int(splits[0])
                splits = splits[1:]
            if splits:
                details = ' '.join(splits)

        await cog.add_to_counter(
            counter, userid, amount,
            context=context,
            details=details
        )
        lb = await cog.leaderboard(counter, start_time=start_time)
        user_total = lb.get(userid, 0)
        total = sum(lb.values())
        await ctx.reply(
            response.format(
                total=total,
                period=period,
                period_name=period.value[0],
                detailsorname=details or counter,
                user_total=user_total,
            )
        )

    async def lb_cmd(
        cog,
        ctx: commands.Context | LionContext,
        origin: ORIGIN,
        author: UserProfile,
        community: Community,
        args: Optional[str]
    ):
        await cog.show_lb(ctx, counter, args, author, community, origin)

    async def undo_cmd(
        cog,
        ctx: commands.Context | LionContext,
        origin: ORIGIN,
        author: UserProfile,
        community: Community,
        args: Optional[str]
    ):
        userid = author.profileid
        _counter = await cog.fetch_counter(counter)
        query = cog.data.CounterEntry.fetch_where(
            counterid=_counter.counterid,
            userid=userid,
        )
        query.order_by('created_at', direction=ORDER.DESC)
        query.limit(1)
        results = await query
        if not results:
            await ctx.reply("Nothing to delete!")
        else:
            row = results[0]
            await row.delete()
            await ctx.reply("Undo successful!")

    return (counter_cmd, lb_cmd, undo_cmd)


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

        await self.load_counter_commands()
        await self.load_counters()
        self.loaded.set()

        profiles = self.bot.get_cog('ProfileCog')
        profiles.add_profile_migrator(self.migrate_profiles, name='counters')

    async def cog_unload(self):
        self._unload_twitch_methods(self.crocbot)

    async def load_counter_commands(self):
        rows = await self.data.CounterCommand.fetch_where()
        for row in rows:
            counter = await self.data.Counter.fetch(row.counterid)
            counter_cb, lb_cb, undo_cb = counter_cmd_factory(
                counter.name,
                row.response
            )
            twitch_cmds = []
            disc_cmds = []
            twitch_cmds.append(
                commands.command(
                    name=row.name
                )(self.twitch_callback(counter_cb))
            )
            disc_cmds.append(
                cmds.hybrid_command(
                    name=row.name
                )(self.discord_callback(counter_cb))
            )

            if row.lbname:
                twitch_cmds.append(
                    commands.command(
                        name=row.lbname
                    )(self.twitch_callback(lb_cb))
                )
                disc_cmds.append(
                    cmds.hybrid_command(
                        name=row.lbname
                    )(self.discord_callback(lb_cb))
                )
            if row.undoname:
                twitch_cmds.append(
                    commands.command(
                        name=row.undoname
                    )(self.twitch_callback(undo_cb))
                )
                disc_cmds.append(
                    cmds.hybrid_command(
                        name=row.undoname
                    )(self.discord_callback(undo_cb))
                )

            for cmd in twitch_cmds:
                self.add_twitch_command(self.crocbot, cmd)
            for cmd in disc_cmds:
                # cmd.cog = self
                self.bot.add_command(cmd)
                print(f"Adding command: {cmd}")

        logger.info(f"(Re)Loaded {len(rows)} counter commands!")

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

    async def migrate_profiles(self, source_profile: UserProfile, target_profile: UserProfile):
        """
        Move source profile entries to target profile entries
        """
        results = ["(Counters)"]

        rows = await self.data.CounterEntry.table.update_where(userid=source_profile.profileid).set(userid=target_profile.profileid)
        if rows:
            results.append(
                f"Migrated {len(rows)} counter entries from source profile."
            )
        else:
            results.append(
                "No counter entries to migrate in source profile."
            )

        return ' '.join(results)

    async def user_profile_migration(self):
        """
        Manual single-use migration method from the old userid format to the new profileid format.
        """
        async with self.bot.db.connection() as conn:
            self.bot.db.conn = conn
            async with conn.transaction():
                entries = await self.data.CounterEntry.fetch_where()
                for entry in entries:
                    if entry.userid > 1000:
                        # Assume userid is a twitch userid
                        profile = await UserProfile.fetch_from_twitchid(self.bot, entry.userid)
                        if not profile:
                            # Need to create
                            users = await self.crocbot.fetch_users(ids=[entry.userid])
                            if not users:
                                continue
                            user = users[0]
                            profile = await UserProfile.create_from_twitch(self.bot, user)
                        await entry.update(userid=profile.profileid)
        logger.info("Completed single-shot user profile migration")

    # General API
    def twitch_callback(self, callback):
        """
        Generate a Twitch command callback from the given general callback.

        General callback must be of the form 
        callback(cog, ctx: GeneralContext, origin: ORIGIN, author: Profile, comm: Community, args: Optional[str])

        Return will be a command callback of the form
        callback(cog, ctx: Context, *, args: Optional[str] = None)
        """
        async def command_callback(cog: CounterCog, ctx: commands.Context, *, args: Optional[str] = None):
            profiles = cog.bot.get_cog('ProfileCog')
            # Compute author profile
            author = await profiles.fetch_profile_twitch(ctx.author)
            # Compute community profile
            community = await profiles.fetch_community_twitch(await ctx.channel.user())
            return await callback(cog, ctx, ORIGIN.TWITCH, author, community, args)
        return command_callback

    def discord_callback(self, callback):
        """
        Generate a Discord command callback from the given general callback.

        General callback must be of the form 
        callback(cog, ctx: GeneralContext, origin: ORIGIN, author: Profile, comm: Community, args: Optional[str])

        Return will be a command callback of the form
        callback(cog, ctx: LionContext, *, args: Optional[str] = None)
        """
        cog = self
        async def command_callback(ctx: LionContext, *, args: Optional[str] = None):
            profiles = cog.bot.get_cog('ProfileCog')
            # Compute author profile
            author = await profiles.fetch_profile_discord(ctx.author)
            # Compute community profile
            community = await profiles.fetch_community_discord(ctx.guild)
            return await callback(cog, ctx, ORIGIN.DISCORD, author, community, args)

        return command_callback

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

    async def add_to_counter(
        self,
        counter: str, userid: int, value: int,
        context: Optional[str]=None,
        details: Optional[str]=None,
    ):
        row = await self.fetch_counter(counter)
        return await self.data.CounterEntry.create(
            counterid=row.counterid,
            userid=userid,
            value=value,
            context_str=context,
            details=details
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

    # Manage commands
    @commands.command()
    async def countermigration(self, ctx: commands.Context, *, args: Optional[str]=None):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return
        await self.user_profile_migration()
        await ctx.reply("Counter userid->profileid migration done.")

    # Counters commands
    @commands.command()
    async def counter(self, ctx: commands.Context, name: str, subcmd: Optional[str], *, args: Optional[str]=None):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        name = name.lower()
        profiles = self.bot.get_cog('ProfileCog')
        author = await profiles.fetch_profile_twitch(ctx.author)
        userid = author.profileid
        community = await profiles.fetch_community_twitch(await ctx.channel.user())

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
                userid,
                value,
                context='cmd: counter add'
            )
            total = await self.totals(name)
            await ctx.reply(f"'{name}' counter is now: {total}")
        elif subcmd == 'lb':
            await self.show_lb(ctx, name, args or '', author, community, origin=ORIGIN.TWITCH)
        elif subcmd == 'clear':
            await self.reset_counter(name)
            await ctx.reply(f"'{name}' counter reset.")
        elif subcmd == 'alias':
            splits = args.split(maxsplit=3) if args else []
            counter = await self.fetch_counter(name)
            rows = await self.data.CounterCommand.fetch_where(counterid=counter.counterid)
            existing = rows[0] if rows else None
            if existing and not args:
                # Show current alias
                await ctx.reply(
                    f"Counter '{name}' aliases: '!{existing.name}' to add to counter; "
                    f"'!{existing.lbname}' to view counter leaderboard; "
                    f"'!{existing.undoname}' to undo (your) last addition."
                )
            elif len(splits) < 4:
                # Show usage
                await ctx.reply(
                    "USAGE: !counter <name> alias <cmdname> <lbname> <undoname> <response> -- "
                    "Response accepts keywords {total}, {period}, {period_name}, {detailsorname}, {user_total}."
                )
            else:
                # Create new alias
                cmdname, lbname, undoname, response = splits
                # Remove any existing alias
                await self.data.CounterCommand.table.delete_where(name=cmdname)

                alias = await self.data.CounterCommand.create(
                    name=cmdname,
                    counterid=counter.counterid,
                    lbname=lbname, undoname=undoname, response=response
                )
                await self.load_counter_commands()
                await ctx.reply(
                    f"Alias created for counter '{name}': '!{alias.name}' to add to counter; "
                    f"'!{alias.lbname}' to view counter leaderboard; "
                    f"'!{alias.undoname}' to undo (your) last addition."
                )
        else:
            await ctx.reply(f"Unrecognised subcommand {subcmd}. Supported subcommands: 'show', 'add', 'lb', 'clear', 'alias'.")

    async def parse_period(self, community: Community, periodstr: str, default=PERIOD.STREAM):
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
            twitches = await community.twitch_channels()
            stream = None
            if twitches:
                twitch = twitches[0]
                streams = await self.crocbot.fetch_streams(user_ids=[int(twitch.channelid)])
                stream = streams[0] if streams else None
            if stream:
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

    @cmds.hybrid_command(
        name='counterlb',
        description="Show the leaderboard for the given counter."
    )
    async def counterlb_dcmd(self, ctx: LionContext, counter: str, period: Optional[str] = None):
        profiles = self.bot.get_cog('ProfileCog')
        author = await profiles.fetch_profile_discord(ctx.author)
        community = await profiles.fetch_community_discord(ctx.guild)
        await self.show_lb(ctx, counter, period, author, community, ORIGIN.DISCORD)

    async def formatted_lb(
            self,
            counter: str,
            periodstr: str,
            community: Community,
            origin: ORIGIN = ORIGIN.TWITCH
        ):

        period, start_time = await self.parse_period(community, periodstr)

        lb = await self.leaderboard(counter, start_time=start_time)
        if lb:
            name_map = {}
            for userid in lb.keys():
                profile = await UserProfile.fetch(self.bot, userid)
                name = await profile.get_name()
                name_map[userid] = name
            # Split this depending on origin
            parts = []
            items = list(lb.items())
            prefix = 'top 10 ' if len(items) > 10 else ''
            items = items[:10]
            for userid, total in items:
                name = name_map.get(userid, str(userid))
                part = f"{name}: {total}"
                parts.append(part)
            lbstr = '; '.join(parts)
            return f"{counter} {period.value[-1]} {prefix}leaderboard --- {lbstr}"
        else:
            return f"{counter} {period.value[-1]} leaderboard is empty!"

    async def show_lb(
            self,
            ctx: commands.Context | LionContext,
            counter: str,
            periodstr: str,
            caller: UserProfile,
            community: Community,
            origin: ORIGIN = ORIGIN.TWITCH
        ):

        period, start_time = await self.parse_period(community, periodstr)
        lb = await self.leaderboard(counter, start_time=start_time)
        name_map = {}
        for userid in lb.keys():
            profile = await UserProfile.fetch(self.bot, userid)
            name = await profile.get_name()
            name_map[userid] = name

        if not lb:
            await ctx.reply(
                f"{counter} {period.value[-1]} leaderboard is empty!"
            )
        elif origin is ORIGIN.TWITCH:
            parts = []
            items = list(lb.items())
            prefix = 'top 10 ' if len(items) > 10 else ''
            items = items[:10]
            for userid, total in items:
                name = name_map.get(userid, str(userid))
                part = f"{name}: {total}"
                parts.append(part)
            lbstr = '; '.join(parts)
            await ctx.reply(f"{counter} {period.value[-1]} {prefix}leaderboard --- {lbstr}")
        elif origin is ORIGIN.DISCORD:
            title = f"'{counter}' {period.value[-1]} leaderboard"

            lb_strings = []
            author_index = None
            max_name_len = min((30, max(len(name) for name in name_map.values())))
            for i, (uid, total) in enumerate(lb.items()):
                if author_index is None and uid == caller.profileid:
                    author_index = i
                lb_strings.append(
                    "{:<{}}\t{:<9}".format(
                        name_map[uid],
                        max_name_len,
                        total,
                    )
                )

            page_len = 20
            pages = paginate_list(lb_strings, block_length=page_len, title=title)
            start_page = author_index // page_len if author_index is not None else 0

            await pager(
                ctx,
                pages,
                start_at=start_page
            )
