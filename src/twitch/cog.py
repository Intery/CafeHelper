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

        self.client_cache = {}

    async def cog_load(self):
        await self.data.init()

    # ----- Auth API -----

    async def fetch_client_for(self, userid: str):
        authrow = await self.data.UserAuthRow.fetch(userid)
        if authrow is None:
            # TODO: Some user authentication error 
            self.client_cache.pop(userid, None)
            raise ValueError("Requested user is not authenticated.")
        if (twitch := self.client_cache.get(userid)) is None:
            twitch = await Twitch(self.bot.config.twitch['app_id'], self.bot.config.twitch['app_secret'])
            scopes = await self.data.UserAuthRow.get_scopes_for(userid)
            authscopes = [AuthScope(scope) for scope in scopes]
            await twitch.set_user_authentication(authrow.access_token, authscopes, authrow.refresh_token)
            self.client_cache[userid] = twitch
        return twitch

    async def check_auth(self, userid: str, scopes: list[AuthScope] = []) -> bool:
        """
        Checks whether the given userid is authorised.
        If 'scopes' is given, will also check the user has all of the given scopes.
        """
        authrow = await self.data.UserAuthRow.fetch(userid)
        if authrow:
            if scopes:
                has_scopes = await self.data.UserAuthRow.get_scopes_for(userid)
                desired = {scope.value for scope in scopes}
                has_auth = desired.issubset(has_scopes)
                logger.info(f"Auth check for `{userid}`: Requested scopes {desired}, has scopes {has_scopes}. Passed: {has_auth}")
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
        self.client_cache.pop(userid, None)
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

    @cmds.hybrid_command(name='modauth')
    async def cmd_modauth(self, ctx: LionContext):
        if ctx.interaction:
            await ctx.interaction.response.defer(ephemeral=True)
        scopes = [
            AuthScope.MODERATOR_READ_FOLLOWERS,
            AuthScope.CHANNEL_READ_REDEMPTIONS,
            AuthScope.MODERATOR_MANAGE_CHAT_MESSAGES,
        ]
        flow = await self.start_auth(scopes=scopes)
        await ctx.reply(flow.auth.return_auth_url())
        await flow.run()
        await ctx.reply("Authentication Complete!")
