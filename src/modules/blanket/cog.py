from typing import Optional
import json
import asyncio

import discord
from discord.ext import commands as cmds
from discord import app_commands as appcmds

from wards import low_management, sys_admin_ward
from meta import LionBot, LionCog, LionContext
from utils.ui import AButton, AsComponents
from utils.lib import MessageArgs
from core.setting_types import MessageSetting

from . import babel

_p = babel._p


class BlanketCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot

    @cmds.hybrid_command(
        name="message",
        description="Send a custom message to a channel."
    )
    @appcmds.describe(
        channel="Channel you want to send the message to",
        content="Text of the message",
        attachment="An attachement to add",
        message_data="Downloaded message json, as output by the message editor."
    )
    @sys_admin_ward
    async def message_cmd(self, ctx: LionContext,
                          channel: discord.TextChannel | discord.VoiceChannel,
                          content: Optional[str] = None,
                          attachment: Optional[discord.Attachment] = None,
                          message_data: Optional[discord.Attachment] = None,
                          ):
        await ctx.interaction.response.defer(thinking=True, ephemeral=True)
        args = {}
        if message_data:
            decoded = await MessageSetting.download_attachment(message_data)
            data = json.loads(decoded)
            msg_args = MessageSetting.value_to_args(0, data)
            args.update(msg_args.kwargs)
        if content:
            args['content'] = content
        if attachment:
            args['file'] = await attachment.to_file()

        message = await channel.send(**args)
        await ctx.interaction.edit_original_response(
            content="Message sent! {message.jump_url}"
        )
