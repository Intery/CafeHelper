from datetime import timedelta
from typing import Optional
from collections import defaultdict
from enum import Enum
import asyncio
import re
from io import StringIO

import discord
from discord.ui.select import select, Select, SelectOption
from discord.ui.button import button, Button, ButtonStyle
from discord.ui.text_input import TextInput, TextStyle

from meta import conf
from meta.LionBot import LionBot
from meta.logger import log_wrap
from meta.errors import UserInputError
from utils.lib import MessageArgs, strfdelta, strfdur, utc_now
from utils.ui import LeoUI, LeoModal, FastModal, error_handler_for, ModalRetryUI
from utils.ui.pagers import BasePager, Pager

from . import logger
from .tasklist import Tasklist
from .data import TaskInfo

checkmark = "✔"
checked_emoji = conf.emojis.task_checked
unchecked_emoji = conf.emojis.task_unchecked


class PlanUI(BasePager):
    # Cache of live plan widgets
    # profileid -> discord channelid -> PlanUI
    _live_ = defaultdict(dict)

    def __init__(self,
                 bot: LionBot,
                 tasklist: Tasklist,
                 channel: discord.abc.Messageable,
                 guild: Optional[discord.Guild] = None,
                 caller: Optional[discord.Member | discord.User] = None,
                 **kwargs):
        kwargs.setdefault('timeout', 600)
        super().__init__(**kwargs)

        self.bot = bot
        self.tasklist = tasklist
        self.profileid = tasklist.profileid
        self.channel = channel
        self.guild = guild
        self.caller = caller

        # List of (label, task) pairs 
        # Label is tuple[int, ...]
        self.labelled = []
        # List of lists of (label, task) pairs
        self._pages = []

        self.page_num = 0
        self._channelid = channel.id
        self.current_page = None

        self._message: Optional[discord.Message] = None

    @property
    def this_page(self):
        return self._pages[self.page_num % len(self._pages)] if self._pages else []

    # ----- UI API -----
    @classmethod
    def fetch(cls, bot, tasklist, channel, *args, **kwargs):
        pid = tasklist.profileid
        channelid = channel.id
        if channelid not in cls._live_[pid]:
            self = cls(bot, tasklist, channel, *args, **kwargs)
            cls._live_[pid][channelid] = self
        return cls._live_[pid][channelid]

    async def run(self, interaction: discord.Interaction):
        await self.refresh()
        await self.redraw(interaction)

    async def summon(self, caller=None, force=False):
        """
        Delete, refresh, and redisplay the tasklist widget as a non-ephemeral message in the current channel.

        May raise `discord.HTTPException` (from `redraw`) if something goes wrong with the send.
        """
        if caller:
            self.caller = caller
        await self.refresh()

        resend = force or not await self._check_recent()
        if resend and self._message:
            # Delete our current message if possible
            try:
                await self._message.delete()
            except discord.HTTPException:
                # If we cannot delete, it has probably already been deleted
                # Or we don't have permission somehow
                pass
            self._message = None

        # Redraw
        try:
            await self.redraw()
        except discord.HTTPException:
            if self._message:
                self._message = None
                await self.redraw()

    async def page_cmd(self, interaction: discord.Interaction, value: str):
        return await Pager.page_cmd(self, interaction, value)

    async def page_acmpl(self, interaction: discord.Interaction, partial: str):
        return await Pager.page_acmpl(self, interaction, partial)

    # ----- Utilities / Workers ------
    async def _check_recent(self) -> bool:
        """
        Check whether the tasklist message is a "recent" message in the channel.
        """
        if self._message is not None:
            height = 0
            async for message in self.channel.history(limit=5):
                if message.id == self._message.id:
                    return True
                if message.id < self._message.id:
                    return False
                if message.attachments or message.embeds or height > 20:
                    return False
                height += message.content.count('\n')
            return False
        return False

    def _format_page(self, page: list[tuple[tuple[int, ...], TaskInfo]]) -> str:
        """
        Format a single block of page data into the task codeblock.
        """
        # TODO: Add special marker for current task. Underline number?
        # Hack to adapt to depth version
        lines = []
        numpad = max(sum(len(str(counter)) - 1 for counter in label) for label, _ in page)
        for label, task in page:
            label_string = '.'.join(map(str, label)) + '.' * (len(label) == 1)
            number = f"**`{label_string}`**"
            if len(label) > 1:
                depth = sum(len(str(c)) + 1 for c in label[:-1]) * ' '
                depth = f"`{depth}`"
            else:
                depth = ''
            if task.total_duration > 0:
                durs = strfdur(task.total_duration)
                durstr = f"`dur: {durs}`"
            else:
                durstr = ''
            task_string = "{curmark}{depth}{cross}{number} {current}{content}{current}{cross} {durstr}".format(
                depth=depth,
                number=number,
                emoji=unchecked_emoji if not task.is_complete else checked_emoji,
                content=task.content,
                curmark='\*'*(task.taskid == self.tasklist.current),
                current='**'*(task.taskid == self.tasklist.current),
                cross='~~' if task.is_complete else '',
                durstr=durstr
            )
            lines.append(task_string)
        return '\n'.join(lines)

    def _format_page_text(self, page: list[tuple[tuple[int, ...], TaskInfo]]) -> str:
        """
        Format a single block of page data into the task codeblock.
        """
        lines = []
        numpad = max(sum(len(str(counter)) - 1 for counter in label) for label, _ in page)
        for label, task in page:
            box = '[ ]' if task.is_complete else f"[{checkmark}]"
            task_string = "{prepad}   {depth} {content}".format(
                prepad=' ' * numpad,
                depth=(len(label) - 1) * '   ',
                content=task.content
            )
            label_string = '.'.join(map(str, label)) + '.' * (len(label) == 1)
            taskline = box + ' ' + label_string + task_string[len(label_string):]
            lines.append(taskline)
        return "```md\n{}```".format('\n'.join(lines))

    # ----- Components -----
    @button(label="", style=ButtonStyle.grey, emoji=conf.emojis.cancel)
    async def quit_button(self, press: discord.Interaction, pressed: Button):
        await press.response.defer()
        if self._message is not None:
            try:
                await self._message.delete()
            except discord.HTTPException:
                pass
        await self.close()

    # ----- UI Flow -----
    async def interaction_check(self, interaction: discord.Interaction):
        # Get user profileid and check they have the same profile 
        # TODO: Potential issue with migrated profiles
        profile = await self.bot.get_cog("ProfileCog").fetch_profile_discord(interaction.user)
        return profile.profileid == self.profileid

    async def cleanup(self):
        self.set_inactive()
        self._live_[self.profileid].pop(self.channel.id, None)

        if self._message is not None:
            try:
                await self._message.edit(view=None)
            except discord.HTTPException:
                pass
            self._message = None

        try:
            if self._message is not None:
                await self._message.edit(view=None)
        except discord.HTTPException:
            pass

    async def get_page(self, page_id) -> MessageArgs:
        # Compute completed plan tasks vs total
        current = self.tasklist.get_current()
        plan = self.tasklist.get_plan()
        total = len(plan)
        completed = sum(t.is_complete for t in plan)

        if self.caller:
            if self.guild:
                user = self.guild.get_member(self.caller.id)
            else:
                user = self.bot.get_user(self.caller.id)
            user_name = user.display_name if user else str(self.caller.id)
            user_colour = user.colour if user else discord.Color.orange()
        else:
            profile = await self.bot.get_cog("ProfileCog").fetch_profile_by_id(self.profileid)
            user_name = profile.profile_row.nickname
            user_colour = discord.Color.orange()
            user = None

        author = (
            "{name}'s plan ({completed}/{total} complete)"
        ).format(
            name=user_name,
            completed=completed,
            total=total
        )

        embed = discord.Embed(
            colour=user_colour,
        )
        embed.set_author(
            name=author,
            icon_url=user.avatar if user else None
        )

        # TODO: Something special for current task, especially if it isn't on the plan
        # TODO: Something special for the help page, to show when there are no tasks 
        # Or the help icon is pressed.

        if self._pages:
            page = self.this_page
            block = self._format_page(page)
            # If current task is not on this page, add it to the top?
            if current and not current.is_complete and current not in plan:
                started_ago = strfdelta(timedelta(seconds=current.total_duration))
                currstr = f"*You have been working on '#{current.tasklabel}: {current.content}' for {started_ago}*"
                currstr += '\n\n'
            else:
                currstr = ""
            embed.description = "{currstr}{task_block}".format(task_block=block, currstr=currstr)
        else:
            # TODO: This needs to be updated for current vs plan
            embed.description = ((
                "**You have no tasks on your plan!**\n"
                "Show what you are working on with e.g. `!now Reading page1; Reading page2`"
            )).format(
                cmds=self.bot.core.mention_cache,
                new_button=conf.emojis.task_new
            )

        page_args = MessageArgs(embed=embed)
        return page_args

    def refresh_pages(self):
        labelled = list(self.labelled.items())
        count = len(labelled)
        pages = []

        if count > 0:
            # Break into pages
            edges = [0]
            line_ptr = 0
            while line_ptr < count:
                line_ptr += 20
                if line_ptr < count:
                    # Seek backwards to find the best parent
                    i = line_ptr - 5
                    minlabel = (i, len(labelled[i][0]))
                    while i < line_ptr:
                        i += 1
                        ilen = len(labelled[i][0])
                        if ilen <= minlabel[1]:
                            minlabel = (i, ilen)
                    line_ptr = minlabel[0]
                else:
                    line_ptr = count
                edges.append(line_ptr)

            pages = [labelled[edges[i]:edges[i+1]] for i in range(len(edges) - 1)]

        self._pages = pages
        return pages

    async def refresh(self):
        # Refresh data
        await self.tasklist.refresh()
        plan = self.tasklist.get_plan()
        uncomplete = {(task.tasklabel,): task for task in plan if not task.is_complete}
        complete = {(task.tasklabel,): task for task in plan if task.is_complete}
        self.labelled = uncomplete | complete
        self.refresh_pages()

    async def refresh_components(self):
        # await asyncio.gather(
        #     # self.refresh_button_refresh(),
        #     self.quit_button_refresh(),
        # )

        if len(self._pages) > 1:
            # Multi paged layout
            self._layout = (
                (self.prev_page_button, self.quit_button, self.next_page_button),
            )
        elif len(self.this_page) > 0:
            # Single page, but still at least one task
            self._layout = (
                (self.quit_button,),
            )
        else:
            # No tasks
            self._layout = (
                (self.quit_button,),
            )

    async def redraw(self, interaction: Optional[discord.Interaction] = None):
        self.current_page = await self.get_page(self.page_num)
        await self.refresh_components()

        # Resend
        if interaction is not None:
            if self._message:
                try:
                    await self._message.delete()
                except discord.HTTPException:
                    pass
            self._message = await interaction.followup.send(**self.current_page.send_args, view=self)
        elif self._message:
            await self._message.edit(**self.current_page.edit_args, view=self)
        else:
            self._message = await self.channel.send(**self.current_page.send_args, view=self)

    
