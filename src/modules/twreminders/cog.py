import asyncio
import json
import re
import itertools
from typing import Optional
from dataclasses import dataclass
from collections import defaultdict

import twitchio
from twitchio.ext import commands
import datetime as dt
from datetime import timedelta, datetime

from meta import CrocBot, LionCog, LionContext, LionBot
from utils.lib import strfdelta, utc_now, parse_dur
from . import logger


reminder_regex = re.compile(
    r"""
    (^)?(?P<type> (?: \b in) | (?: every))
    \s*(?P<duration> (?: day| hour| (?:\d+\s*(?:(?:d|h|m|s)[a-zA-Z]*)?(?:\s|and)*)+))
    (?:(?(1) (?:, | ; | : | \. | to)? | $))
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL
)


@dataclass
class Reminder:
    userid: int
    content: str
    name: str
    channel: str
    remind_at: datetime


class ReminderCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.crocbot: CrocBot = bot.crocbot

        self.loaded = asyncio.Event()
        self.reminders: dict[int, list[Reminder]] = defaultdict(list)

        self.next_reminder_task = None
        self._reminder_wait_task = None
        self.reminder_lock = asyncio.Lock()

    async def cog_load(self):
        await self.load_reminders()
        self.loaded.set()

    async def ensure_loaded(self):
        if not self.loaded.is_set():
            await self.cog_load()

    async def cog_check(self, ctx):
        await self.ensure_loaded()
        return True

    def save_reminders(self):
        with open('reminders.json', 'w', encoding='utf-8') as f:
            mapped = {
                    int(userid): [
                        {
                            'userid': int(state.userid),
                            'name': state.name,
                            'channel': state.channel,
                            'content': state.content,
                            'remind_at': state.remind_at.isoformat(),
                        }
                        for state in states
                    ]
                    for userid, states in self.reminders.items()
            }
            json.dump(mapped, f, ensure_ascii=False, indent=4)

    async def load_reminders(self):
        if self.next_reminder_task and not self.next_reminder_task.cancelled():
            self.next_reminder_task.cancel()
            self.next_reminder_task = None

        with open('reminders.json') as f:
            mapped = json.load(f)
            self.reminders.clear()
            for userid, states in mapped.items():
                userid = int(userid)
                for map in states:
                    reminder = Reminder(
                        userid=int(map['userid']),
                        content=map['content'],
                        name=map['name'],
                        channel=map['channel'],
                        remind_at=dt.datetime.fromisoformat(map['remind_at'])
                    )
                    self.reminders[userid].append(reminder)
        self.schedule_next_reminder()
        logger.info(f"Loaded reminders: {self.reminders}")

    def schedule_next_reminder(self):
        """
        Schedule the next reminder in the queue, if it exists, and return it.
        Cancels any currently running task.
        """
        if not self.reminders:
            return None
        next_reminder = min(
            itertools.chain(*self.reminders.values()), key=lambda r: r.remind_at, default=None
        )
        if next_reminder:
            self.next_reminder_task = asyncio.create_task(self.run_reminder(next_reminder))
        else:
            # We still need to cancel any ongoing reminders
            if self._reminder_wait_task and not self._reminder_wait_task.cancelled():
                self._reminder_wait_task.cancel()

    async def run_reminder(self, reminder: Reminder):
        """
        Wait for and then run the given reminder.
        Expects to be cancelled if another reminder is scheduled earlier.
        """
        # Cancel the next reminder wait task.
        # If the next reminder is currently executing/firing,
        # this will do nothing and we will wait until it is finished.
        if self._reminder_wait_task and not self._reminder_wait_task.cancelled():
            self._reminder_wait_task.cancel()

        # This ensures that only one reminder task runs at once
        async with self.reminder_lock:
            now = utc_now()
            to_wait = (reminder.remind_at - now).total_seconds()
            try:
                self._reminder_wait_task = asyncio.create_task(asyncio.sleep(to_wait))
                await self._reminder_wait_task
            except asyncio.CancelledError:
                # Reminder task was cancelled
                raise

            # Now fire the reminder
            await self.fire_reminder(reminder)

            # And schedule the next reminder if needed
            self.schedule_next_reminder()

    async def fire_reminder(self, reminder: Reminder):
        """
        Actually run the given reminder.
        """
        # Check that this reminder is still valid
        if reminder not in self.reminders[reminder.userid]:
            logger.error(f"Reminder {reminder!r} is firing but not scheduled!")
            return

        # We don't want to reschedule while a reminder is running
        # Get the channel to send to
        destination = self.crocbot.get_channel(reminder.channel)
        if destination is None:
            logger.info(f"Reminder couldn't get channel '{reminder.channel}'. Trying again in a minute.")
            # In case we aren't actually ready yet
            await self.crocbot.wait_for_ready()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.info("Cancelling channel wait task for reminder.")
                raise
            destination = self.crocbot.get_channel(reminder.channel)
            if destination is None:
                # This means we haven't joined the channel
                logger.warning(f"Reminder couldn't get channel '{reminder.channel}' for the second time. Cancelling.")
            else:
                logger.info(f"Channel '{reminder.channel}' found as {destination}. Continuing.")
        
        if destination is not None:
            # Send the reminder
            msg = f"@{reminder.name}, you asked me to remind you: {reminder.content}"
            await destination.send(msg)

        # This should really be based on a reminderid but oh well
        # It's theoretically possible for a reminder to be scheduled at the same time as it is run
        # In which case the wrong reminder will be removed.
        self.reminders[reminder.userid].remove(reminder)
        self.save_reminders()

    def get_reminders_for(self, userid: int):
        return self.reminders.get(userid, [])

    @commands.command(name='remindme', aliases=['reminders', 'reminder'])
    async def remindme_cmd(self, ctx, *, args: str=''):
        args = args.strip()
        userid = int(ctx.author.id)
        existing = self.get_reminders_for(userid)
        existing.sort(key=lambda r: r.remind_at, reverse=False)
        now = utc_now()

        if not args or args.lower() in ('show', 'list'):
            # Show user's current reminders or show usage
            if not existing:
                await ctx.reply(
                    "USAGE: !remindme <task> in <dur> EG: !remindme Coffee is ready in 10m | !remindme in 10m, Coffee is ready"
                )
            elif len(existing) == 1:
                reminder = existing[0]
                dur = reminder.remind_at - now
                sec = (dur.total_seconds()) < 60
                formatted_dur = strfdelta(dur, short=False, sec=sec)
                await ctx.reply(
                    f"I will remind you about '{reminder.content}' in about {formatted_dur}. Use !remindme cancel to cancel!"
                )
            else:
                parts = []
                for i, reminder in enumerate(existing, start=1):
                    dur = reminder.remind_at - now
                    sec = (dur.total_seconds()) < 60
                    formatted_dur = strfdelta(dur, short=True, sec=sec)
                    parts.append(
                        f"{i}: '{reminder.content}' in {formatted_dur}"
                    )
                remstr = '; '.join(parts)
                if len(remstr) > 290:
                    remstr = remstr[:290] + '...'

                await ctx.reply(
                        f"Active Reminders: {remstr}. Use '!remindme cancel n' or '!remindme clear' to remove!"
                )
        elif args.lower() in ('clear', 'clearall', 'remove all'):
            # Remove all reminders
            if existing:
                self.reminders.pop(userid, None)
                self.save_reminders()
                self.schedule_next_reminder()
            else:
                await ctx.reply("You don't have any reminders set!")
        elif args.lower().split(maxsplit=1)[0] in ('remove', 'cancel'):
            splits = args.split(maxsplit=1)
            remaining = splits[1].strip() if len(splits) > 1 else ''

            # Remove a specified reminder
            to_remove = None
            if not existing:
                await ctx.reply("You don't have any reminders set!")
            elif len(existing) == 1:
                to_remove = existing[0]
            elif remaining.isdigit():
                # Try to the remove the reminder with the give number
                given = int(remaining)
                if given > len(existing):
                    await ctx.reply(f"You only have {len(existing)} reminders!")
                else:
                    to_remove = existing[given - 1]
            else:
                # Invalid arguments, show usage
                await ctx.reply(
                    "USAGE: !remindme cancel <number>, e.g. !remindme cancel 1 to cancel your first reminder!"
                )

            if to_remove is not None:
                self.reminders[userid].remove(to_remove)
                await ctx.reply(
                    f"Cancelled your reminder '{to_remove.content}'"
                )
                self.save_reminders()
                self.schedule_next_reminder()
        else:
            # Parse for reminder
            content = None
            duration = None
            repeating = None

            # First parse it
            match = re.search(reminder_regex, args)
            if match:
                repeating = match.group('type').lower() == 'every'

                duration_str = match.group('duration').lower()
                if duration_str.isdigit():
                    # Default to minutes if no unit given
                    duration = int(duration_str) * 60
                elif duration_str in ('day', 'a day'):
                    duration = 24 * 60 * 60
                elif duration_str in ('hour', 'an hour'):
                    duration = 60 * 60
                else:
                    duration = parse_dur(duration_str)

                content = (args[:match.start()] + args[match.end():]).strip()
                if content.startswith('to '):
                    content = content[3:].strip()
            else:
                # Legacy parsing, without requiring "in" at the front
                splits = args.split(maxsplit=1)
                if len(splits) == 2 and splits[0].isdigit():
                    repeating = False
                    duration = int(splits[0]) * 60
                    content = splits[1].strip()

            # Sanity checking
            if not duration or not content:
                return await ctx.reply(
                    "Sorry, I didn't understand your reminder! Please use e.g. !remindme Coffee is ready in 10m"
                )
            if repeating:
                return await ctx.reply(
                    "Sorry, we don't support repeating reminders right now!"
                )
            if len(existing) > 10:
                return await ctx.reply(
                    "Sorry, you can only have 10 active reminders! Use !remindme cancel or !remindme clear to cancel some!"
                )

            reminder = Reminder(
                userid=userid,
                content=content,
                name=ctx.author.name,
                channel=ctx.channel.name,
                remind_at=now + timedelta(seconds=duration)
            )

            self.reminders[userid].append(reminder)
            dur = reminder.remind_at - now
            sec = (dur.total_seconds()) < 60
            formatted_dur = strfdelta(dur, short=False, sec=sec)

            msg = f"Got it! I will remind you in {formatted_dur}!"

            await ctx.reply(msg)

            self.save_reminders()
            self.schedule_next_reminder()
