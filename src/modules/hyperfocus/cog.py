import asyncio
import json
from typing import Optional
from dataclasses import dataclass

import twitchio
from twitchio.ext import commands
from twitchAPI.type import AuthScope
import random
import datetime as dt
from datetime import timedelta, datetime

from meta import CrocBot, LionCog, LionContext, LionBot
from meta.sockets import Channel, register_channel
from utils.lib import strfdelta, utc_now
from . import logger


@dataclass
class FocusState:
    userid: int | str
    name: str
    focus_ends: datetime
    hyper: bool = True


class FocusChannel(Channel):
    name = 'FocusList'

    def __init__(self, cog: 'HyperFocusCog', **kwargs):
        self.cog = cog
        super().__init__(**kwargs)

    async def on_connection(self, websocket, event):
        await super().on_connection(websocket, event)
        await self.reload_focus(websocket=websocket)

    def focus_args(self, state: FocusState):
        return (
            state.userid,
            state.name,
            state.hyper,
            state.focus_ends.isoformat(),
        )

    async def reload_focus(self, websocket=None):
        """
        Clear tasklist and re-send current tasks.
        """
        await self.send_clear(websocket=websocket)
        for state in self.cog.hyperfocusing.values():
            await self.send_set(*self.focus_args(state), websocket=websocket)

    async def send_set(self, userid, name, hyper, end_at, websocket=None):
        await self.send_event({
            'type': "DO",
            'method': "setFocus",
            'args': {
                'userid': userid,
                'name': name,
                'hyper': hyper,
                'end_at': end_at,
            }
        }, websocket=websocket)

    async def send_del(self, userid, websocket=None):
        await self.send_event({
            'type': "DO",
            'method': "delFocus",
            'args': {
                'userid': userid,
            }
        }, websocket=websocket)

    async def send_clear(self, websocket=None):
        await self.send_event({
            'type': "DO",
            'method': "clearFocus",
            'args': {
            }
        }, websocket=websocket)



class HyperFocusCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.crocbot: CrocBot = bot.crocbot

        # userid -> timestamp when they stop
        self.hyperfocusing: dict[str, FocusState] = {}

        self.channel = FocusChannel(self)
        register_channel(self.channel.name, self.channel)

        self.loaded = asyncio.Event()

    async def cog_load(self):
        self._load_twitch_methods(self.crocbot)
        self.load_hyperfocus()
        self.loaded.set()

    async def cog_unload(self):
        self._unload_twitch_methods(self.crocbot)

    def save_hyperfocus(self):
        with open('hyperfocus.json', 'w', encoding='utf-8') as f:
            mapped = {
                userid: {
                    'userid': str(state.userid),
                    'name': state.name,
                    'focus_ends': state.focus_ends.isoformat(),
                    'hyper': state.hyper
                }
                for userid, state in self.hyperfocusing.items()
            }
            json.dump(mapped, f, ensure_ascii=False, indent=4)

    def load_hyperfocus(self):
        with open('hyperfocus.json') as f:
            mapped = json.load(f)
            self.hyperfocusing.clear()
            for userid, map in mapped.items():
                self.hyperfocusing[str(userid)] = FocusState(
                    userid=str(map['userid']),
                    name=map['name'],
                    hyper=map['hyper'],
                    focus_ends=dt.datetime.fromisoformat(map['focus_ends'])
                )
        print(f"Loaded hyperfocus: {self.hyperfocusing}")

    def check_hyperfocus(self, userid):
        """
        Returns whether a user is currently in HYPERFOCUS mode!
        """
        return (state := self.hyperfocusing.get(userid, None)) and utc_now() < state.focus_ends

    @commands.Cog.event('event_message')
    async def on_message(self, message: twitchio.Message):
        if message.content and message.content.lower() == 'nice':
            await message.channel.send("That's Nice")

        await self.good_croccy_handler(message)

        tags = message.tags
        if tags and message.content and self.check_hyperfocus(tags.get('user-id')):
            if not self.valid_focus_message(message):
                logger.info(
                    f"Deleting message from hyperfocused user. {message.raw_data=}"
                )
                await asyncio.sleep(1)
                msgid = tags['id']
                # TODO: Better selection for moderator
                # i.e. if the message is not from the broadcaster and we do have delete perms
                # then use our own token.
                broadcasterid = tags['room-id']
                authcog = self.bot.get_cog('TwitchAuthCog')
                if not await authcog.check_auth(broadcasterid, scopes=[AuthScope.MODERATOR_MANAGE_CHAT_MESSAGES]):
                    await message.channel.send(f"@{message.author.name} Stay focused! (I tried to delete your message because you are in !hyperfocus. Unfortunately I don't have the permissions to do that. But stay focused anyway!)")
                else:
                    twitch = await authcog.fetch_client_for(broadcasterid)
                    await twitch.delete_chat_message(
                        broadcasterid,
                        broadcasterid,
                        msgid,
                    )
                    await message.channel.send(
                        f"@{message.author.name} Stay focused! (I deleted your message because you are in !hyperfocus, use !unfocus to come back.)"
                    )

    async def good_croccy_handler(self, message: twitchio.Message):
        if not message.content:
            return
        cleaned = message.content.lower().replace('@croccyhelper', '').strip()
        if cleaned in ('good croc', 'good croccy', 'good helper'):
            await message.channel.send("holono1Heart")
        elif cleaned in ('bad croc', 'bad croccy', 'bad helper'):
            await message.channel.send("holono1Sad")

    async def chemical_handler(self, message: twitchio.Message):
        if not message.content:
            return
        cleaned = message.content.lower().strip()
        if cleaned in ('oh',):
            await message.channel.send('Oxygen Hydrogen!')

    def valid_focus_message(self, message: twitchio.Message) -> bool:
        """
        Determined whether the given message is allowed to be sent in !hyperfocus.
        That is, if it appears to be emote-only or a command.
        """

        content = message.content
        if not content:
            return True

        tags = message.tags or {}
        to_remove = []

        if (replying := tags.get('reply-parent-user-login', '')) and content.startswith('@'):
            # Trim the mention from the start of the content
            splits = content.split(maxsplit=1)
            to_remove.append((0, len(splits[0])))

        if emotesstr := tags.get('emotes', ''):
            for emotestr in emotesstr.split('/'):
                emote, locs = emotestr.split(':')
                for loc in locs.split(','):
                    start, end = loc.split('-')
                    to_remove.append((int(start), int(end) + 1))

        # Sort the pairs to remove by descending starting index
        # This should allow clean removal with a loop as long as there are no intersections.
        to_remove.sort(key=lambda pair: pair[0], reverse=True)
        for start, end in to_remove:
            content = content[:start] + content[end:]
        content = content.strip().replace(' ', '').replace('\n', '')
        allowed = not content or content.startswith('!') or content.startswith('*')
        allowed = allowed or all(not char.isascii() for char in content)

        if not allowed:
            logger.info(f"Invalid hyperfocus message. Trimmed content: {content}")

        return allowed

    @commands.command(name='coinflip')
    async def coinflip(self, ctx):
        await ctx.reply(random.choice(('heads', 'tails')))

    @commands.command(name='choose')
    async def choose(self, ctx, *, args: str):
        if not args:
            await ctx.reply("Give me something to choose, e.g. !choose Heads | Tails")
        else:
            options = args.split('|')
            options = [option.strip() for option in options]
            options = [option for option in options if option]
            choice = random.choice(options)
            if random.random() < 0.01:
                choice = "You"
            await ctx.reply(f"I choose: {choice}")

    @commands.command(name='hyperfocus')
    async def hyperfocus_cmd(self, ctx, dur: Optional[int] = None):
        userid = str(ctx.author.id)
        now = utc_now()
        end_time = None

        if dur is None:
            # Automatically select time
            next_hour = now.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
            next_block = next_hour - dt.timedelta(minutes=10)
            if now > next_block:
                # Currently in the break
                next_block = next_block + dt.timedelta(hours=1)
            end_time = next_block
            dur = int((end_time - now).total_seconds() // 60)
        elif dur > 720:
            await ctx.reply("You can hyperfocus for at most 12 hours at a time!")
        else:
            end_time = utc_now() + dt.timedelta(minutes=dur)

        if end_time is not None:
            state = self.hyperfocusing[userid] = FocusState(
                userid=userid,
                name=ctx.author.display_name,
                focus_ends=end_time,
            )
            self.save_hyperfocus()
            await self.channel.send_set(*self.channel.focus_args(state))
            await ctx.reply(
                f"{ctx.author.name} has gone into HYPERFOCUS mode! "
                f"They will be in emote and command only mode for the next {dur} minutes! "
                "Use !unfocus if you really need to chat before then, best of luck! 🍀"
            )

    @commands.command(name='unfocus')
    async def unfocus_cmd(self, ctx):
        self.hyperfocusing.pop(ctx.author.id, None)
        self.save_hyperfocus()
        await self.channel.send_del(ctx.author.id)
        await ctx.reply("Welcome back from focus, hope it went well! Have a comfy break and remember to have a sippie and a stretch~")

    @commands.command(name='hyperfocused')
    async def focused_cmd(self, ctx, user: Optional[twitchio.User] = None):
        user = user if user is not None else ctx.author
        userid = str(user.id)
        if self.check_hyperfocus(userid):
            state = self.hyperfocusing.get(userid)
            end_time = state.focus_ends
            durstr = strfdelta(end_time - utc_now())
            await ctx.reply(
                f"{user.name} is in HYPERFOCUS for another {durstr}! "
                "They can only write emojis and commands in this time~ "
                "(use !unfocus to come back if you need to!) "
                "Good luck!"
            )
        elif userid != str(ctx.author.id):
            await ctx.reply(
                f"{user.name} is not hyperfocused!"
            )
        else:
            await ctx.reply(
                "You are not hyperfocused! "
                "Enter HYPERFOCUS mode for e.g. 10 minutes by writing !hyperfocus 10"
            )
