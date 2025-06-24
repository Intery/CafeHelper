import datetime as dt

import twitchio
from twitchio.ext import commands

from meta import CrocBot, LionCog, LionContext, LionBot 
from utils.lib import strfdelta, utc_now, parse_dur

from . import logger 


class TimeCog(LionCog):
    def __init__(self, bot: LionBot):
        self.bot = bot
        self.crocbot: CrocBot = bot.crocbot 

    async def cog_load(self):
        self._load_twitch_methods(self.crocbot)

    async def cog_unload(self):
        self._unload_twitch_methods(self.crocbot)

    async def get_timezone_for(self, profile):
        timezone = None
        discords = await profile.discord_accounts()
        if discords:
            userid = discords[0].userid 
            luser = await self.bot.core.lions.fetch_user(userid)
            if luser:
                timezone = luser.config.timezone.value
        return timezone

    def get_timestr(self, tz, brief=False):
        """
        Get the current time in the given timezone, using a fixed format string.
        """
        format_str = "%H:%M, %d/%m/%Y" if brief else "%I:%M %p (%Z) on %a, %d/%m/%Y"
        now = dt.datetime.now(tz=tz)
        return now.strftime(format_str)

    async def time_diff(self, tz, auth_tz, name, brief=False):
        """
        Get a string representing the time difference between the user's timezone and the given one.
        """
        if auth_tz is None or tz is None:
            return None
        author_time = dt.datetime.now(tz=auth_tz)
        other_time = dt.datetime.now(tz=tz)
        timediff = other_time.replace(tzinfo=None) - author_time.replace(tzinfo=None)
        diffsecs = round(timediff.total_seconds())

        if diffsecs == 0:
            return ", the same as {}!".format(name)

        modifier = "behind" if diffsecs > 0 else "ahead"
        diffsecs = abs(diffsecs)

        hours, remainder = divmod(diffsecs, 3600)
        mins, _ = divmod(remainder, 60)

        hourstr = "{} hour{} ".format(hours, "s" if hours > 1 else "") if hours else ""
        minstr = "{} minutes ".format(mins) if mins else ""
        joiner = "and " if (hourstr and minstr) else ""
        return ". {} is {}{}{}{}, at {}.".format(
            name, hourstr, joiner, minstr, modifier, self.get_timestr(auth_tz, brief=brief)
        )

    @commands.command(name='time', aliases=['ti'])
    async def time_cmd(self, ctx, *, args: str=''):
        """
        Current usage is 
        !time 
        !time <target user>

        Planned:
        !time set ...
        !time at ...
        """
        authprofile = await self.bot.get_cog('ProfileCog').fetch_profile_twitch(ctx.author)
        authtz = await self.get_timezone_for(authprofile)

        if args:
            target_tw = await self.crocbot.seek_user(args)
            if target_tw is None:
                return await ctx.reply(f"Couldn't find user '{args}'!")
            target = await self.bot.get_cog('ProfileCog').fetch_profile_twitch(target_tw)
            targettz = await self.get_timezone_for(target)
            name = await target.get_name()
            if targettz is None:
                return await ctx.reply(
                    f"{name} hasn't set their timezone! Ask them to set it with '/my timezone' on discord."
                )
        else:
            target = None
            targettz = None
            name = None
            if authtz is None:
                return await ctx.reply(
                    "You haven't set your timezone! Set it on discord by linking your Twitch account with `/profiles link twitch`, and then using `/my timezone`"
                )

        timestr = self.get_timestr(targettz if target else authtz)
        name = name or await authprofile.get_name()

        if target:
            tdiffstr = await self.time_diff(targettz, authtz, name)
            msg = f"The current time for {name} is {timestr}{tdiffstr}"
        else:
            msg = f"The current time for {name} is {timestr}"
        await ctx.reply(msg)
