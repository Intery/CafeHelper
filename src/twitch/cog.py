import asyncio
from enum import Enum
from typing import Optional
from datetime import timedelta

import discord
from discord.ext import commands as cmds

from twitchAPI.oauth import UserAuthenticator
from twitchAPI.twitch import AuthType, Twitch
from twitchAPI.type import AuthScope
import twitchio
from twitchio.ext import commands


from data.queries import ORDER
from meta import LionCog, LionBot, CrocBot
from meta.LionContext import LionContext
from twitch.userflow import UserAuthFlow
from utils.lib import utc_now
from . import logger
from .data import TwitchAuthData


class TwitchAuthCog(LionCog):
    DEFAULT_SCOPES = []

    def __init__(self, bot: LionBot):
        self.bot = bot
        self.data = bot.db.load_registry(TwitchAuthData())

    async def cog_load(self):
        await self.data.init()

    # ----- Auth API -----

    async def fetch_client_for(self, userid: int):
        ...

    async def check_auth(self, userid: str, scopes: list[AuthScope] = []) -> bool:
        """
        Checks whether the given userid is authorised.
        If 'scopes' is given, will also check the user has all of the given scopes.
        """
        authrow = await self.data.UserAuthRow.fetch(userid)
        if authrow:
            if scopes:
                has_scopes = await self.data.UserAuthRow.get_scopes_for(userid)
                has_auth = set(map(str, scopes)).issubset(has_scopes)
            else:
                has_auth = True
        else:
            has_auth = False
        return has_auth

    async def start_auth_for(self, userid: str, scopes: list[AuthScope] = []):
        """
        Start the user authentication flow for the given userid.
        Will request the given scopes along with the default ones and any existing scopes.
        """
        existing_strs = await self.data.UserAuthRow.get_scopes_for(userid)
        existing = map(AuthScope, existing_strs)
        to_request = set(existing).union(scopes)
        return await self.start_auth(to_request)

    async def start_auth(self, scopes = []):
        # TODO: Work out a way to just clone the current twitch object
        # Or can we otherwise build UserAuthenticator without app auth?
        twitch = await Twitch(self.bot.config.twitch['app_id'], self.bot.config.twitch['app_secret'])
        auth = UserAuthenticator(twitch, scopes, url=self.bot.config.twitchauth['callback_uri'])
        flow = UserAuthFlow(self.data, auth, self.bot.config.twitchauth['ws_url'])
        await flow.setup()

        return flow

    # ----- Commands -----
    @cmds.hybrid_command(name='auth')
    async def cmd_auth(self, ctx: LionContext):
        if ctx.interaction:
            await ctx.interaction.response.defer(ephemeral=True)
        flow = await self.start_auth()
        await ctx.reply(flow.auth.return_auth_url())
        await flow.run()
        await ctx.reply("Authentication Complete!")
