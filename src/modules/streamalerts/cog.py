import asyncio
from typing import Optional

import discord
from discord.ext import commands as cmds
from discord import app_commands as appcmds

from twitchAPI.twitch import Twitch
from twitchAPI.helper import first

from meta import LionBot, LionCog, LionContext
from meta.errors import UserInputError
from meta.logger import log_wrap
from utils.lib import utc_now
from data.conditions import NULL

from . import logger
from .data import AlertsData
from .settings import AlertConfig, AlertSettings
from .editor import AlertEditorUI


class AlertCog(LionCog):
    POLL_PERIOD = 60

    def __init__(self, bot: LionBot):
        self.bot = bot
        self.data = bot.db.load_registry(AlertsData())
        self.twitch = None
        self.alert_settings = AlertSettings()

        self.poll_task = None
        self.event_tasks = set()

        # Cache of currently live streams, maps streamerid -> stream
        self.live_streams = {}

        # Cache of streamers we are watching state changes for
        # Map of streamerid -> streamer
        self.watching = {}

    async def cog_load(self):
        await self.data.init()

        await self.twitch_login()
        await self.load_subs()
        self.poll_task = asyncio.create_task(self.poll_live())

    async def twitch_login(self):
        # TODO: Probably abstract this out to core or a dedicated core cog
        # Also handle refresh tokens
        if self.twitch is not None:
            await self.twitch.close()
            self.twitch = None

        self.twitch = await Twitch(
            self.bot.config.twitch['app_id'].strip(), 
            self.bot.config.twitch['app_secret'].strip()
        )

    async def load_subs(self):
        # Load active subscriptions
        active_subs = await self.data.AlertChannel.fetch_where()
        to_watch = {sub.streamerid for sub in active_subs}
        live_streams = await self.data.Stream.fetch_where(
            self.data.Stream.end_at != NULL
        )
        to_watch.union(stream.streamerid for stream in live_streams)

        # Load associated streamers
        watching = {}
        if to_watch:
            streamers = await self.data.Streamer.fetch_where(
                userid=list(to_watch)
            )
            for streamer in streamers:
                watching[streamer.userid] = streamer

        self.watching = watching
        self.live_streams = {stream.streamerid: stream for stream in live_streams}

        logger.info(
            f"Watching {len(watching)} streamers for state changes. "
            f"Loaded {len(live_streams)} (previously) live streams into cache."
        )

    async def poll_live(self):
        # Every PERIOD seconds,
        # request get_streams for the streamers we are currently watching.
        # Check if they are in the live_stream cache,
        # and update cache and data and fire-and-forget start/stop events as required.
        # TODO: Logging
        # TODO: Error handling so the poll loop doesn't die from temporary errors
        # And when it does die it gets logged properly.
        if not self.twitch:
            raise ValueError("Attempting to start alert poll-loop before twitch set.")

        block_i = 0

        self.polling = True
        while self.polling:
            await asyncio.sleep(self.POLL_PERIOD)

            to_request = list(self.watching.keys())
            if not to_request:
                continue
            # Each loop we request the 'next' slice of 100 userids
            blocks = [to_request[i:i+100] for i in range(0, len(to_request), 100)]
            block_i += 1
            block_i %= len(blocks)
            block = blocks[block_i]

            streaming = {}
            async for stream in self.twitch.get_streams(user_id=block, first=100):
                # Note we set page size to 100
                # So we should never get repeat or missed streams
                # Since we can request a max of 100 userids anyway.
                streaming[stream.user_id] = stream

            started = set(streaming.keys()).difference(self.live_streams.keys())
            ended = set(self.live_streams.keys()).difference(streaming.keys())

            for streamerid in started:
                stream = streaming[streamerid]
                stream_data = await self.data.Stream.create(
                    streamerid=stream.user_id,
                    start_at=stream.started_at,
                    twitch_stream_id=stream.id,
                    game_name=stream.game_name,
                    title=stream.title,
                )
                self.live_streams[streamerid] = stream_data
                task = asyncio.create_task(self.on_stream_start(stream_data))
                self.event_tasks.add(task)
                task.add_done_callback(self.event_tasks.discard)

            for streamerid in ended:
                stream_data = self.live_streams.pop(streamerid)
                await stream_data.update(end_at=utc_now())
                task = asyncio.create_task(self.on_stream_end(stream_data))
                self.event_tasks.add(task)
                task.add_done_callback(self.event_tasks.discard)

    async def on_stream_start(self, stream_data):
        # Get channel subscriptions listening for this streamer
        uid = stream_data.streamerid
        logger.info(f"Streamer <uid:{uid}> started streaming! {stream_data=}")
        subbed = await self.data.AlertChannel.fetch_where(streamerid=uid)

        # Fulfill those alerts
        for sub in subbed:
            try:
                # If the sub is paused, don't create the alert
                await self.sub_alert(sub, stream_data)
            except discord.HTTPException:
                # TODO: Needs to be handled more gracefully at user level
                # Retry logic?
                logger.warning(
                    f"Could not complete subscription {sub=} for {stream_data=}", exc_info=True
                )
            except Exception:
                logger.exception(
                    f"Unexpected exception completing {sub=} for {stream_data=}"
                )
                raise

    async def subscription_error(self, subscription, stream_data, err_msg):
        """
        Handle a subscription fulfill failure.
        Stores the error message for user display,
        and deletes the subscription after some number of errors.
        # TODO
        """
        logger.warning(
            f"Subscription error {subscription=} {stream_data=} {err_msg=}"
        )

    async def sub_alert(self, subscription, stream_data):
        # Base alert behaviour is just to send a message
        # and create an alert row

        channel = self.bot.get_channel(subscription.channelid)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            # Subscription channel is gone!
            # Or the Discord channel cache died
            await self.subscription_error(
                subscription, stream_data,
                "Subscription channel no longer exists."
            )
            return
        permissions = channel.permissions_for(channel.guild.me)
        if not (permissions.send_messages and permissions.embed_links):
            await self.subscription_error(
                subscription, stream_data,
                "Insufficient permissions to post alert message."
            )
            return

        # Build message
        streamer = await self.data.Streamer.fetch(stream_data.streamerid)
        if not streamer:
            # Streamer was deleted while handling the alert
            # Just quietly ignore
            # Don't error out because the stream data row won't exist anymore
            logger.warning(
                f"Cancelling alert for subscription {subscription.subscriptionid}"
                " because the streamer no longer exists."
            )
            return

        alert_config = AlertConfig(subscription.subscriptionid, subscription)
        paused = alert_config.get(self.alert_settings.AlertPaused.setting_id)
        if paused.value:
            logger.info(f"Skipping alert for subscription {subscription=} because it is paused.")
            return

        live_message = alert_config.get(self.alert_settings.AlertMessage.setting_id)

        formatter = await live_message.generate_formatter(self.bot, stream_data, streamer)
        formatted = await formatter(live_message.value)
        args = live_message.value_to_args(subscription.subscriptionid, formatted)

        try:
            message = await channel.send(**args.send_args)
        except discord.HTTPException as e:
            logger.warning(
                f"Message send failure while sending streamalert {subscription.subscriptionid}",
                exc_info=True
            )
            await self.subscription_error(
                subscription, stream_data,
                "Failed to post live alert."
            )
            return

        # Store sent alert
        alert = await self.data.StreamAlert.create(
            streamid=stream_data.streamid,
            subscriptionid=subscription.subscriptionid,
            sent_at=utc_now(),
            messageid=message.id
        )
        logger.debug(
            f"Fulfilled subscription {subscription.subscriptionid} with alert {alert.alertid}"
        )

    async def on_stream_end(self, stream_data):
        # Get channel subscriptions listening for this streamer
        uid = stream_data.streamerid
        logger.info(f"Streamer <uid:{uid}> stopped streaming! {stream_data=}")
        subbed = await self.data.AlertChannel.fetch_where(streamerid=uid)

        # Resolve subscriptions
        for sub in subbed:
            try:
                await self.sub_resolve(sub, stream_data)
            except discord.HTTPException:
                # TODO: Needs to be handled more gracefully at user level
                # Retry logic?
                logger.warning(
                    f"Could not resolve subscription {sub=} for {stream_data=}", exc_info=True
                )
            except Exception:
                logger.exception(
                    f"Unexpected exception resolving {sub=} for {stream_data=}"
                )
                raise

    async def sub_resolve(self, subscription, stream_data):
        # Check if there is a current active alert to resolve
        alerts = await self.data.StreamAlert.fetch_where(
            streamid=stream_data.streamid,
            subscriptionid=subscription.subscriptionid,
        )
        if not alerts:
            logger.info(
                f"Resolution requested for subscription {subscription.subscriptionid} with stream {stream_data.streamid} "
                "but no active alerts were found."
            )
            return
        alert = alerts[0]
        if alert.resolved_at is not None:
            # Alert was already resolved
            # This is okay, Twitch might have just sent the stream ending twice
            logger.info(
                f"Resolution requested for subscription {subscription.subscriptionid} with stream {stream_data.streamid} "
                "but alert was already resolved."
            )
            return

        # Check if message is to be deleted or edited (or nothing)
        alert_config = AlertConfig(subscription.subscriptionid, subscription)
        del_setting = alert_config.get(self.alert_settings.AlertEndDelete.setting_id)
        edit_setting = alert_config.get(self.alert_settings.AlertEndMessage.setting_id)

        if (delmsg := del_setting.value) or (edit_setting.value):
            # Find the message 
            message = None
            channel = self.bot.get_channel(subscription.channelid)
            if channel:
                try:
                    message = await channel.fetch_message(alert.messageid)
                except discord.HTTPException:
                    # Message was probably deleted already
                    # Or permissions were changed
                    # Or Discord connection broke
                    pass
            else:
                # Channel went after posting the alert
                # Or Discord cache sucks
                # Nothing we can do, just mark it handled
                pass
            if message:
                if delmsg:
                    # Delete the message
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        logger.warning(
                            f"Discord exception while del-resolve live alert {alert=}",
                            exc_info=True
                        )
                else:
                    # Edit message with custom arguments
                    streamer = await self.data.Streamer.fetch(stream_data.streamerid)
                    formatter = await edit_setting.generate_formatter(self.bot, stream_data, streamer)
                    formatted = await formatter(edit_setting.value)
                    args = edit_setting.value_to_args(subscription.subscriptionid, formatted)
                    try:
                        await message.edit(**args.edit_args)
                    except discord.HTTPException:
                        logger.warning(
                            f"Discord exception while edit-resolve live alert {alert=}",
                            exc_info=True
                        )
        else:
            # Explicitly don't need to do anything to the alert
            pass

        # Save alert as resolved
        await alert.update(resolved_at=utc_now())

    async def cog_unload(self):
        if self.poll_task is not None and not self.poll_task.cancelled():
            self.poll_task.cancel()

        if self.twitch is not None:
            await self.twitch.close()
            self.twitch = None

    # ----- Commands -----
    @cmds.hybrid_group(
        name='streamalert',
        description=(
            "Create and configure stream live-alerts."
        )
    )
    @cmds.guild_only()
    @appcmds.default_permissions(manage_channels=True)
    async def streamalert_group(self, ctx: LionContext):
        # Placeholder group, method not used
        raise NotImplementedError

    @streamalert_group.command(
        name='create',
        description=(
            "Subscribe a Discord channel to notifications when a Twitch stream goes live."
        )
    )
    @appcmds.describe(
        streamer="Name of the twitch channel to watch.",
        channel="Which Discord channel to send live alerts in.",
        message="Custom message to send when the channel goes live (may be edited later)."
    )
    @appcmds.default_permissions(manage_channels=True)
    async def streamalert_create_cmd(self, ctx: LionContext,
                                     streamer: str,
                                     channel: discord.TextChannel,
                                     message: Optional[str]):
        # Type guards
        assert ctx.guild is not None, "Guild-only command has no guild ctx."
        assert self.twitch is not None, "Twitch command run with no twitch obj."

        # Wards
        if not channel.permissions_for(ctx.author).manage_channels:
            await ctx.error_reply(
                "Sorry, you need the `MANAGE_CHANNELS` permission "
                "to add a stream alert to a channel."
            )
            return

        # Look up the specified streamer
        tw_user = await first(self.twitch.get_users(logins=[streamer]))
        if not tw_user:
            await ctx.error_reply(
                f"Sorry, could not find `{streamer}` on Twitch! "
                "Make sure you use the name in their channel url."
            )
            return

        # Create streamer data if it doesn't already exist
        streamer_data = await self.data.Streamer.fetch_or_create(
            tw_user.id,
            login_name=tw_user.login,
            display_name=tw_user.display_name,
        )

        # Add subscription to alerts list
        sub_data = await self.data.AlertChannel.create(
            streamerid=streamer_data.userid,
            guildid=channel.guild.id,
            channelid=channel.id,
            created_by=ctx.author.id,
            paused=False
        )

        # Add to watchlist
        self.watching[streamer_data.userid] = streamer_data

        # Open AlertEditorUI for the new subscription
        # TODO
        await ctx.reply("StreamAlert Created.")

    async def alert_acmpl(self, interaction: discord.Interaction, partial: str):
        if not interaction.guild:
            raise ValueError("Cannot acmpl alert in guildless interaction.")

        # Get all alerts in the server
        alerts = await self.data.AlertChannel.fetch_where(guildid=interaction.guild_id)

        if not alerts:
            # No alerts available
            options = [
                appcmds.Choice(
                    name="No stream alerts are set up in this server!",
                    value=partial
                )
            ]
        else:
            options = []
            for alert in alerts:
                streamer = await self.data.Streamer.fetch(alert.streamerid)
                if streamer is None:
                    # Should be impossible by foreign key condition
                    # Might be a stale cache
                    continue
                channel = interaction.guild.get_channel(alert.channelid)
                display = f"{streamer.display_name} in #{channel.name if channel else 'unknown'}"
                if partial.lower() in display.lower():
                    # Matching option
                    options.append(appcmds.Choice(name=display, value=str(alert.subscriptionid)))
            if not options:
                options.append(
                    appcmds.Choice(
                        name=f"No stream alerts matching {partial}"[:25],
                        value=partial
                    )
                )
        return options

    async def resolve_alert(self, interaction: discord.Interaction, alert_str: str):
        if not interaction.guild:
            raise ValueError("Resolving alert outside of a guild.")
        # Expect alert_str to be the integer subscriptionid
        if not alert_str.isdigit():
            raise UserInputError(
                f"No stream alerts in this server matching `{alert_str}`!"
            )
        alert = await self.data.AlertChannel.fetch(int(alert_str))
        if not alert or not alert.guildid == interaction.guild_id:
            raise UserInputError(
                "Could not find the selected alert! Please try again."
            )
        return alert

    @streamalert_group.command(
        name='edit',
        description=(
            "Update settings for an existing Twitch stream alert."
        )
    )
    @appcmds.describe(
        alert="Which alert do you want to edit?",
        # TODO: Other settings here
    )
    @appcmds.default_permissions(manage_channels=True)
    async def streamalert_edit_cmd(self, ctx: LionContext, alert: str):
        # Type guards
        assert ctx.guild is not None, "Guild-only command has no guild ctx."
        assert self.twitch is not None, "Twitch command run with no twitch obj."
        assert ctx.interaction is not None, "Twitch command needs interaction ctx."

        # Look up provided alert
        sub_data = await self.resolve_alert(ctx.interaction, alert)

        # Check user permissions for editing this alert
        channel = ctx.guild.get_channel(sub_data.channelid)
        permlevel = channel if channel else ctx.guild
        if not permlevel.permissions_for(ctx.author).manage_channels:
            await ctx.error_reply(
                "Sorry, you need the `MANAGE_CHANNELS` permission "
                "in this channel to edit the stream alert."
            )
            return
        # If edit options have been given, save edits and retouch cache if needed
        # If not, open AlertEditorUI
        ui = AlertEditorUI(bot=self.bot, sub_data=sub_data, callerid=ctx.author.id)
        await ui.run(ctx.interaction)
        await ui.wait()

    @streamalert_edit_cmd.autocomplete('alert')
    async def streamalert_edit_cmd_alert_acmpl(self, interaction, partial):
        return await self.alert_acmpl(interaction, partial)

    @streamalert_group.command(
        name='pause',
        description=(
            "Pause a streamalert."
        )
    )
    @appcmds.describe(
        alert="Which alert do you want to pause?",
    )
    @appcmds.default_permissions(manage_channels=True)
    async def streamalert_pause_cmd(self, ctx: LionContext, alert: str):
        # Type guards
        assert ctx.guild is not None, "Guild-only command has no guild ctx."
        assert self.twitch is not None, "Twitch command run with no twitch obj."
        assert ctx.interaction is not None, "Twitch command needs interaction ctx."

        # Look up provided alert
        sub_data = await self.resolve_alert(ctx.interaction, alert)

        # Check user permissions for editing this alert
        channel = ctx.guild.get_channel(sub_data.channelid)
        permlevel = channel if channel else ctx.guild
        if not permlevel.permissions_for(ctx.author).manage_channels:
            await ctx.error_reply(
                "Sorry, you need the `MANAGE_CHANNELS` permission "
                "in this channel to edit the stream alert."
            )
            return

        await sub_data.update(paused=True)
        await ctx.reply("This alert is now paused!")

    @streamalert_group.command(
        name='unpause',
        description=(
            "Resume a streamalert."
        )
    )
    @appcmds.describe(
        alert="Which alert do you want to unpause?",
    )
    @appcmds.default_permissions(manage_channels=True)
    async def streamalert_unpause_cmd(self, ctx: LionContext, alert: str):
        # Type guards
        assert ctx.guild is not None, "Guild-only command has no guild ctx."
        assert self.twitch is not None, "Twitch command run with no twitch obj."
        assert ctx.interaction is not None, "Twitch command needs interaction ctx."

        # Look up provided alert
        sub_data = await self.resolve_alert(ctx.interaction, alert)

        # Check user permissions for editing this alert
        channel = ctx.guild.get_channel(sub_data.channelid)
        permlevel = channel if channel else ctx.guild
        if not permlevel.permissions_for(ctx.author).manage_channels:
            await ctx.error_reply(
                "Sorry, you need the `MANAGE_CHANNELS` permission "
                "in this channel to edit the stream alert."
            )
            return

        await sub_data.update(paused=False)
        await ctx.reply("This alert has been unpaused!")

    @streamalert_group.command(
        name='remove',
        description=(
            "Deactivate a streamalert entirely (see /streamalert pause to temporarily pause it)."
        )
    )
    @appcmds.describe(
        alert="Which alert do you want to remove?",
    )
    @appcmds.default_permissions(manage_channels=True)
    async def streamalert_remove_cmd(self, ctx: LionContext, alert: str):
        # Type guards
        assert ctx.guild is not None, "Guild-only command has no guild ctx."
        assert self.twitch is not None, "Twitch command run with no twitch obj."
        assert ctx.interaction is not None, "Twitch command needs interaction ctx."

        # Look up provided alert
        sub_data = await self.resolve_alert(ctx.interaction, alert)

        # Check user permissions for editing this alert
        channel = ctx.guild.get_channel(sub_data.channelid)
        permlevel = channel if channel else ctx.guild
        if not permlevel.permissions_for(ctx.author).manage_channels:
            await ctx.error_reply(
                "Sorry, you need the `MANAGE_CHANNELS` permission "
                "in this channel to edit the stream alert."
            )
            return

        await sub_data.delete()
        await ctx.reply("This alert has been deleted.")
