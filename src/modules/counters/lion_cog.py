import asyncio
from typing import Optional

import discord
from discord.ext import commands as cmds
from discord import app_commands as appcmds

from meta import LionBot, LionCog, LionContext
from meta.errors import UserInputError
from meta.logger import log_wrap
from utils.lib import utc_now
from data.conditions import NULL

from . import logger
from .data import CounterData


class CounterCog(LionCog):

    def __init__(self, bot: LionBot):
        self.bot = bot 

        self.counter_cog = bot.crocbot.get_cog('CounterCog')
