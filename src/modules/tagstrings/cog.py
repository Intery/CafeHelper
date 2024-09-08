import asyncio
from collections import defaultdict
from typing import Optional
import difflib

import twitchio
from twitchio.ext import commands

from meta import CrocBot, LionBot, LionCog
from utils.lib import utc_now
from . import logger
from .data import TagData


class TagCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.crocbot = bot.crocbot
        self.data = bot.db.load_registry(TagData())

        self.loaded = asyncio.Event()

        # Cache of channel tags, channelid -> name.lower() -> Tag
        self.tags: dict[int, dict[str, TagData.Tag]] = {}

    async def load_tags(self):
        tags = defaultdict(dict)

        rows = await self.data.Tag.fetch_where()
        for row in rows:
            tags[row.channelid][row.name.lower()] = row

        self.tags.clear()
        self.tags.update(tags)
        logger.info(f"Loaded {len(tags)} into cache.")

    async def cog_load(self):
        await self.data.init()
        await self.load_tags()
        self._load_twitch_methods(self.crocbot)
        self.loaded.set()

    async def cog_unload(self):
        self.loaded.clear()
        self.tags.clear()
        self._unload_twitch_methods(self.crocbot)

    async def cog_check(self, ctx):
        if not self.loaded.is_set():
            await ctx.reply("Tasklists are still loading! Please wait a moment~")
            return False
        return True

    # API

    async def create_tag(self, channelid: int, name: str, content: str, created_by: int):
        """
        Create a new Tag with the given parameters.

        If the tag already exists, will raise (TODO)
        """
        row = await self.data.Tag.create(
            channelid=channelid,
            name=name,
            content=content,
            created_by=created_by,
        )

        if (chantags := self.tags.get(channelid, None)) is None:
            chantags = self.tags[channelid] = {}
        chantags[name.lower()] = row

        logger.info(f"Created Tag: {row!r}")

        return row

    # Commands

    @commands.command()
    async def edittag(self, ctx: commands.Context, tagname: str, *, content: str):
        """
        Create or edit a tag.
        """
        channelid = int((await ctx.channel.user()).id)
        userid = int(ctx.author.id)

        # Fetch the tag if it exists
        tag = self.tags.get(channelid, {}).get(tagname.lower(), None)

        if tag is None:
            # Create new tag
            tag = await self.create_tag(
                channelid,
                tagname,
                content,
                userid
            )
            await ctx.reply(f"Tag '{tagname}' created as #{tag.tagid}!")
        else:
            # Edit existing tag
            if not (ctx.author.is_mod or ctx.author.is_broadcaster or userid == tag.created_by):
                await ctx.reply("You can't edit this tag!")
                return

            await tag.update(
                content=content,
                updated_at=utc_now()
            )

            await ctx.reply(f"Updated '{tag.name}'")

    @commands.command()
    async def deltag(self, ctx: commands.Context, tagname: str):
        if ctx.author.is_broadcaster or ctx.author.is_mod:
            channelid = int((await ctx.channel.user()).id)
            tag = self.tags.get(channelid, {}).get(tagname.lower(), None)
            if tag is None:
                await ctx.reply(f"Couldn't find '{tagname}' to delete!")
            else:
                self.tags[channelid].pop(tag.name.lower())
                await tag.delete()
                await ctx.reply(f"Deleted '{tag.name}'")

    @commands.command()
    async def tag(self, ctx: commands.Context, tagname: str):
        channelid = int((await ctx.channel.user()).id)
        tags = self.tags.get(channelid, {})
        if (tag := tags.get(tagname.lower(), None)) is None:
            # Search for closest match

            matches = difflib.get_close_matches(tagname.lower(), tags.keys(), n=2)
            matchstr = "'{}'".format("' or '".join(matches)) if matches else None
            suffix = f"Did you mean {matchstr}?" if matches else ""

            await ctx.reply(f"Couldn't find tag '{tagname}'! {suffix}")
            return
        await ctx.reply(tag.content)

    @commands.command(name='tags')
    async def cmd_tags(self, ctx: commands.Context, *, searchstr: str = ''):
        """
        List the tags available in the current channel.
        """
        channelid = int((await ctx.channel.user()).id)
        tag_names = [tag.name for tag in self.tags.get(channelid, {}).values()]
        matching = [name for name in tag_names if searchstr.lower() in name.lower()]
        tagstr = ', '.join(matching)

        if searchstr:
            if matching:
                await ctx.reply(f"Matching tags: {tagstr}")
            else:
                await ctx.reply(f"No tags matching '{searchstr}'")
        else:
            if matching:
                await ctx.reply(f"Available tags: {tagstr}")
            else:
                await ctx.reply("No tags set up on this channel!")
