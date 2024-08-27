import asyncio
from typing import Optional

import twitchio
from twitchio.ext import commands

from meta import CrocBot
from utils.lib import replace_multiple
from . import logger
from .data import ShoutoutData


class ShoutoutCog(commands.Cog):
    # Future extension: channel defaults and config
    DEFAULT_SHOUTOUT = """
    We think that {name} is a great streamer and you should check them out \
    and drop a follow! \
    They {areorwere} streaming {game} at {channel}
    """
    def __init__(self, bot: CrocBot):
        self.bot = bot
        self.data = bot.data.load_registry(ShoutoutData())

        self.loaded = asyncio.Event()

    async def cog_load(self):
        await self.data.init()
        self.loaded.set()

    async def ensure_loaded(self):
        if not self.loaded.is_set():
            await self.cog_load()

    @commands.Cog.event('event_ready')  # type: ignore
    async def on_ready(self):
        await self.ensure_loaded()

    async def cog_check(self, ctx):
        await self.ensure_loaded()
        return True

    async def format_shoutout(self, text: str, user: twitchio.User):
        channels = await self.bot.fetch_channels([user.id])
        if channels:
            channel = channels[0]
            game = channel.game_name or 'Unknown'
        else:
            game = 'Unknown'

        streams = await self.bot.fetch_streams([user.id])
        live = bool(streams)

        mapping = {
            '{name}': user.display_name,
            '{channel}': f"https://www.twitch.tv/{user.name}",
            '{game}': game,
            '{areorwere}': 'are' if live else 'were',
        }
        return replace_multiple(text, mapping)

    @commands.command(aliases=['so'])
    async def shoutout(self, ctx: commands.Context, user: twitchio.User):
        # Make sure caller is mod/broadcaster
        # Lookup custom shoutout for this user
        # If it exists use it, otherwise use default shoutout
        if (ctx.author.is_mod or ctx.author.is_broadcaster):
            data = await self.data.CustomShoutout.fetch(int(user.id))
            if data:
                shoutout = data.content
            else:
                shoutout = self.DEFAULT_SHOUTOUT
            formatted = await self.format_shoutout(shoutout, user)
            await ctx.reply(formatted)
            # TODO: How to /shoutout with lib?

    @commands.command()
    async def editshoutout(self, ctx: commands.Context, user: twitchio.User, *, text: str):
        # Make sure caller is mod/broadcaster/user themselves(?)
        # upsert/delete and insert (is upsert impl?)
        if (ctx.author.is_mod or ctx.author.is_broadcaster or int(ctx.author.id) == int(user.id)):
            await self.data.CustomShoutout.table.delete_where(userid=int(user.id))

            if text and text.lower() not in ('reset', 'none'):
                await self.data.CustomShoutout.create(
                    userid=int(user.id),
                    content=text,
                )
                await ctx.reply("Custom shoutout updated!")
            else:
                await ctx.reply("Custom shoutout removed.")
