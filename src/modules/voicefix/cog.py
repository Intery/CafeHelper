from typing import Optional
import asyncio
from cachetools import FIFOCache

import discord
from discord.ext import commands as cmds
from discord import app_commands as appcmds

from meta import LionBot, LionCog, LionContext
from . import logger


async def prepare_attachments(attachments: list[discord.Attachment]):
    results = []
    for attach in attachments:
        try:
            as_file = await attach.to_file(spoiler=attach.is_spoiler())
            results.append(as_file)
        except discord.HTTPException:
            pass
    return results


async def prepare_embeds(message: discord.Message):
    embeds = [embed for embed in message.embeds if embed.type == 'rich']
    if message.reference:
        embed = discord.Embed(
            colour=discord.Colour.dark_gray(),
            description=f"Reply to {message.reference.jump_url}"
        )
        embeds.append(embed)
    return embeds



class VoiceFixCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot

        # Map of linkids to list of channelids
        self.link_channels = {}

        # Map of channelids to linkids
        self.channel_links = {}

        # Map of channelids to initialised discord.Webhook
        self.hooks = {}

        # Map of messageid to list of (channelid, webhookmsg) pairs, for updates
        self.message_cache = FIFOCache(maxsize=200)
        # webhook msgid -> orig msgid
        self.wmessages = FIFOCache(maxsize=600)

        self.lock = asyncio.Lock()


    async def cog_load(self):
        # TODO: Just manually filling here, but move to data eventually
        self.link_channels = {
            1: (
                1122589406809821184, 1101422204471750728, 1097147368186593408
            )
        }
        self.channel_links = {
            1122589406809821184: (1,),
            1101422204471750728: (1,),
            1097147368186593408: (1,),
        }
        self.hooks[1101422204471750728] = discord.Webhook.from_url(
            "https://discord.com/api/webhooks/1154751966153560105/DPIIo0IyE5-jfIb6vjeHYBXqME9wwYEMSXLJyotu2T9kn84ZczkZgypzb4misErOiE9l",
            client=self.bot
        )
        self.hooks[1122589406809821184] = discord.Webhook.from_url(
            "https://discord.com/api/webhooks/1154752336628039680/mVVYsY5D3NRP-n3RAk-4Nvv7jrQ6F2y1AFVXZ5X9IFAHlk4jd23onfgsYaknBB7HZQKw",
            client=self.bot
        )
        self.hooks[1097147368186593408] = discord.Webhook.from_url(
            "https://discord.com/api/webhooks/1158446279702093905/ygsbPqJXnN_Kfz2Zq7RKGDT5fG4ZsfCa5W87wS7bMbBqLeZJSEYY8Fz1oxXC3GyhGGRe",
            client=self.bot
        )

    @LionCog.listener('on_message')
    async def on_message(self, message: discord.Message):
        # Don't need this because everything except explicit messages are webhooks now
        # if self.bot.user and (message.author.id == self.bot.user.id):
        #     return
        if message.webhook_id:
            return

        async with self.lock:
            sent = []
            linkids = self.channel_links.get(message.channel.id, ())
            if linkids:
                for linkid in linkids:
                    for channelid in self.link_channels[linkid]:
                        if channelid != message.channel.id:
                            if message.attachments:
                                files = await prepare_attachments(message.attachments)
                            else:
                                files = []

                            hook = self.hooks[channelid]
                            avatar = message.author.avatar or message.author.default_avatar
                            msg = await hook.send(
                                content=message.content,
                                wait=True,
                                username=message.author.display_name,
                                avatar_url=avatar.url,
                                embeds=await prepare_embeds(message),
                                files=files,
                                allowed_mentions=discord.AllowedMentions.none()
                            )
                            sent.append((channelid, msg))
                            self.wmessages[msg.id] = message.id
                if sent:
                    # For easier lookup
                    self.wmessages[message.id] = message.id
                    sent.append((message.channel.id, message))

                    self.message_cache[message.id] = sent
                    logger.info(f"Forwarded message {message.id}")
        

    @LionCog.listener('on_message_edit')
    async def on_message_edit(self, before, after):
        async with self.lock:
            cached_sent = self.message_cache.pop(before.id, ())
            new_sent = []
            for cid, msg in cached_sent:
                try:
                    if msg.id != before.id:
                        msg = await msg.edit(
                            content=after.content,
                            embeds=await prepare_embeds(after),
                        )
                    new_sent.append((cid, msg))
                except discord.NotFound:
                    pass
            if new_sent:
                self.message_cache[after.id] = new_sent

    @LionCog.listener('on_message_delete')
    async def on_message_delete(self, message):
        async with self.lock:
            origid = self.wmessages.get(message.id, None)
            if origid:
                cached_sent = self.message_cache.pop(origid, ())
                for _, msg in cached_sent:
                    try:
                        if msg.id != message.id:
                            await msg.delete()
                    except discord.NotFound:
                        pass

    @LionCog.listener('on_reaction_add')
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        async with self.lock:
            message = reaction.message
            emoji = reaction.emoji
            origid = self.wmessages.get(message.id, None)
            if origid and reaction.count == 1:
                cached_sent = self.message_cache.get(origid, ())
                for _, msg in cached_sent:
                    # TODO: Would be better to have a Message and check the reactions
                    try:
                        if msg.id != message.id:
                            await msg.add_reaction(emoji)
                    except discord.HTTPException:
                        pass

