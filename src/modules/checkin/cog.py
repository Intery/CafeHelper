import asyncio
from typing import Optional
import datetime as dt
from datetime import timedelta, datetime

import discord
import twitchAPI
from twitchAPI.object.eventsub import ChannelPointsCustomRewardRedemptionData
from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.type import AuthScope

import twitchio
from twitchio.ext import commands

from meta import CrocBot, LionCog, LionContext, LionBot 
from utils.lib import utc_now 
from . import logger


class CheckinCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot 
        self.crocbot: CrocBot = bot.crocbot 

        self.listeners = []
        self.eswebsockets = {}

    async def cog_load(self):
        self._load_twitch_methods(self.crocbot)

        check_in_channel_id = self.bot.config.croccy['check_in_channel'].strip()
        await self.attach_checkin_channel(check_in_channel_id)

    async def cog_unload(self):
        self._unload_twitch_methods(self.crocbot)

    async def fetch_eventsub_for(self, channelid):
        if (eventsub := self.eswebsockets.get(channelid)) is None:
            authcog = self.bot.get_cog('TwitchAuthCog')
            if not await authcog.check_auth(channelid, scopes=[AuthScope.channelid_READ_REDEMPTIONS]):
                logger.error(
                    f"Insufficient auth to login to registered check-in channelid {channelid}"
                )
            else:
                twitch = await authcog.fetch_client_for(channelid)
                eventsub = EventSubWebsocket(twitch)
                eventsub.start()
                self.eswebsockets[channelid] = eventsub
        return eventsub

    async def attach_checkin_channel(self, channel):
        # Register a listener for the given channel (given as a string id)
        eventsub = await self.fetch_eventsub_for(channel)
        if eventsub:
            await eventsub.listen_channel_points_custom_reward_redemption_add(channel, self.handle_redeem)
            logger.info(f"Attached check-in listener to registered channel {channel}")
        else:
            logger.error(f"Could not attach checkin listener to registered channel {channel}")

    async def handle_redeem(self, data: ChannelPointsCustomRewardRedemptionData):
        # Check if the redeem is one of the 'checkin' or 'quiet checkin' redeems.
        title = data.event.title.lower()
        # TODO: Redeem ID based registration (configured)
        seeking = ('check in', 'quiet hello')
        if title in seeking:
            quiet = seeking.index(title)
            await self.do_checkin(
                data.event.broadcaster_user_id,
                data.event.broadcaster_user_login,
                data.event.user_id,
                data.event.user_name,
                quiet,
                data.event.redeemed_at
            )

    async def do_checkin(self, channel, channel_name, user, user_name, quiet, redeemed_at):
        logger.info(
            f"Starting checkin process for {channel_name=}, {user_name=}, {quiet=}, {redeemed_at=}"
        )
        checkin_counter_name = '_checkin'
        first_counter_name = '_first'
        second_counter_name = '_second'
        third_counter_name = '_third'

        counters = self.bot.get_cog('CounterCog')
        if not counters:
            raise ValueError("Check-in running without counters cog loaded!")
        profiles = self.bot.get_cog('ProfileCog')
        if not profiles:
            raise ValueError("Check-in running without profile cog loaded!")

        # TODO: Relies on profile implementation detail
        profile = await profiles.fetch_profile_twitch(discord.Object(id=user))

        stream_start = await self.get_stream_start(channel)
        # Stream has to be running for this to do anything
        if stream_start is not None:
            # Get all check-in redeems since the start of stream.
            check_in_counter = await counters.fetch_counter(checkin_counter_name)
            entries = await counters.data.CounterEntry.table.select_where(
                counters.data.CounterEntry.created_at >= stream_start,
                counterid=check_in_counter.counterid,
            )
            position = len(entries) + 1
            if profile.profileid not in (e.userid for e in entries):
                # User has not already checked in!
                # Check them in
                # TODO: May be worth setting custom counter time
                await counters.add_to_counter(
                    counter=check_in_counter.name,
                    userid=profile.profileid,
                    value=1,
                )
                checkin_total = await counters.personal_total(checkin_counter_name, profile.profileid)

                # If they deserve a first, give them that
                position_total = None
                if position <= 3:
                    counter_name = (first_counter_name, second_counter_name, third_counter_name)[position-1]
                    await counters.add_to_counter(
                        counter=counter_name,
                        userid=profile.profileid,
                        value=1,
                    )
                    position_total = await counters.personal_total(counter_name, profile.profileid)

                if not quiet:
                    name = user_name
                    if position == 1:
                        message = f"Welcome in and congrats on first check-in {name}! You have been first {position_total}/{checkin_total} times!"
                    else:
                        # TODO: Randomised replies
                        # TODO: Maybe different messages for lower positions or earlier times but not explicitly giving numbers?
                        # Need to update this for stream calcs anyway.
                        message = f"Welcome in {name}! You have checked in {checkin_total} times! Let's have a productive time together~"

                    # Now get the channel and post 
                    channel = self.crocbot.get_channel(channel_name)
                    if not channel:
                        logger.error(
                            f"Channel {channel_name} is not in cache. Cannot send checkin reply."
                        )
                    else:
                        await channel.send(message)

    async def get_stream_start(self, channelid: str | int) -> Optional[datetime]:
        streams = await self.crocbot.fetch_streams(user_ids=[int(channelid)])
        if streams:
            return streams[0].started_at
