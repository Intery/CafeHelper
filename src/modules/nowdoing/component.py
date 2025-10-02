from datetime import timedelta
from typing import Optional

import twitchio
from twitchio.ext import commands as cmds

from meta import Bot 
from utils.lib import strfdelta, utc_now

from ..data import TaskInfo, TaskProfile, Task, TaskData
from ..tasklist import TaskRegistry
from .. import logger


# TaskView and TasklistView?
# TaskView 


class TaskComponent(cmds.Component):
    """
    Command Interface
    -----------------
    !now 1, task, 2-5
    !edit
    !clear
        Deletes the currently set 'now' task.
    !done

    !plan
    !plan a, b, c
    !unplan
    !clearplan

    !notnow
    !resume
    !soon

    !tasklist 
    !add 
    !delete

    !now a, b, c 
    !now x 
    !next

    TODO: Probably a TaskView class for consistently formatting the task contents?
    Maybe with a DiscordTaskView and TwitchTaskView

    TODO: Moderator command clearfor? Not sure how moderators should manage the tasklist.
    """
    def __init__(self, bot: Bot):
        self.bot = bot
        self.data = bot.dbconn.load_registry(TaskData())
        self.tasker = TaskRegistry(self.data)

    async def component_load(self):
        await self.data.init()
        await self.tasker.setup()
        # TODO: Add the IPC task update callback

    async def get_profile_for(self, user: twitchio.PartialUser):
        return await self.bot.profiles.fetch_profile(user)

    @cmds.command(name='now', aliases=['task', 'check', 'add'])
    async def cmd_now(self, ctx: cmds.Context, *, args: Optional[str]):
        """
        Examples:
            {prefix}now
            {prefix}now current task
            {prefix}now current task; next task; task after that
        """
        # TODO: Breaking change: check and add should change behaviour.
        # Check shows the status of the given task (does not allow creation)
        # Add adds the task(s) to the end of the plan.

        profileid = (await self.get_profile_for(ctx.author)).profileid

        # Get tasklist for this profile
        tasklist = await self.tasker.get_tasklist(profileid)
        current = tasklist.get_current()

        # If we are given a new task, delete the current now, set the new now
        if args:
            if current:
                await tasklist.delete_tasks(current.taskid)
            task, = await tasklist.create_tasks(args)
            await tasklist.set_now(task.taskid)
            # TODO: Maybe I should send the update now instead, after three separate changes.. 
            await ctx.reply("Updated your current task, good luck!")
        elif current:
            if current.is_complete:
                done_ago = strfdelta(utc_now() - current.completed_at)
                await ctx.reply(f"You finished '{current.content}' {done_ago} ago!")
            else:
                started_ago = strfdelta(timedelta(seconds=current.total_duration))
                await ctx.reply(f"You have been working on '{current.content}' for {started_ago}!")
        else:
            await ctx.reply(
                "You don't have a task on the tasklist! "
                "Show what you are currently working on with, e.g., !now Reading notes"
            )

    @cmds.command(name='edit')
    async def cmd_edit(self, ctx: cmds.Context, *, args: Optional[str]):
        """
        Usage:
            {prefix}edit [taskid] <new content>
        Examples:
            {prefix}edit new current task
            {prefix}edit 2 New task content for task 2
        """
        # TODO: Breaking changes for multi-tasks
        # edit will support a numberic argument

        if not args:
            # TODO: Better USAGE fetching
            await ctx.reply(f"Usage: {ctx.prefix}edit <new content>. E.g. {ctx.prefix}edit Now Reading")
            return

        profile = await self.get_profile_for(ctx.author)
        tasklist = await self.tasker.get_tasklist(profile.profileid)
        current = tasklist.get_current()
        if current:
            await tasklist.edit_task(current.taskid, args)
            await ctx.reply("Updated your current task!")
        else:
            await ctx.reply("No current task to edit! ")

    @cmds.command(name='delete', aliases=['clear', 'remove'])
    async def cmd_delete(self, ctx: cmds.Context, *, taskspec: Optional[str] = None):
        """
        Description:
            Deletes the specified tasks or the current task.
        Examples:
            !delete 
            !delete 1-
        """
        # TODO: Breaking changes for multi-tasks
        # delete will support an argument
        profile = await self.get_profile_for(ctx.author)
        tasklist = await self.tasker.get_tasklist(profile.profileid)
        current = tasklist.get_current()

        if current:
            await tasklist.delete_tasks(current.taskid)
            await ctx.reply("Deleted your current task from the tasklist!")
        else:
            await ctx.reply("You don't have a current task set at the moment!")

    @cmds.command(name='done')
    async def cmd_done(self, ctx: cmds.Context, *, taskspec: Optional[str] = None):
        """
        Description:
            Marks the specified tasks as complete, or the current task.
        Examples:
            !done
            !done 1-, 3-5, 6
        """
        # TODO: We can actually create the task here if it's not done.

        profile = await self.get_profile_for(ctx.author)
        tasklist = await self.tasker.get_tasklist(profile.profileid)
        current = tasklist.get_current()

        if taskspec:
            tasks = await tasklist.parse_taskspec(taskspec)
        else:
            tasks = [current] if current else []

        if tasks:
            # Complete the tasks
            completed = await tasklist.complete_tasks(task.taskid for task in tasks)

            # Response depends on how many tasks were complete
            # Don't show if duration is less than 30 seconds
            if not completed:
                # No tasks were actually completed
                if len(tasks) > 1:
                    await ctx.reply("You already finished these tasks!")
                else:
                    task = tasks[0]
                    await ctx.reply(f"You already finished '{task.content}'")
            else:
                # Note that duration for completed tasks will always be correct
                duration = int(sum(task.duration for task in completed))
                durstr = strfdelta(timedelta(seconds=duration))
                if len(completed) == 1:
                    task = completed[0]
                    taskstr = f"Good work finishing '{task.content}'"
                    if duration > 60:
                        taskstr += f" You worked on it for {durstr}"
                else:
                    taskstr = f"{len(completed)} more tasks completed, great work!"
                    if duration > 60:
                        taskstr += f" You worked on them for {durstr}"
                await ctx.reply(taskstr)
        elif taskspec:
            await ctx.reply(f"'{taskspec}' didn't match any tasks!")
        else:
            await ctx.reply(
                "You don't have a task on the tasklist! "
                f"Show what you are currently working on with, e.g., {ctx.prefix}now Reading Notes"
            )

    @cmds.command(name='next')
    async def cmd_next(self, ctx: cmds.Context, *, taskspec: Optional[str] = None):
        """
        Description:
            Marks the current task as complete, if it exists,
            and moves to the next task on your plan.

            If an argument is given,
            acts as first a !done and then !now with the same argument
        Examples:
            !next
        """
        if not taskspec:
            await ctx.reply(
                f"Usage:{ctx.prefix}next <next task> "
                f"TIP: {ctx.prefix}next completes your current task and sets the given task as your new current task."
            )
            return

        # Very similar to !now, but with a !done first, and different arguments
        profile = await self.get_profile_for(ctx.author)
        tasklist = await self.tasker.get_tasklist(profile.profileid)
        current = tasklist.get_current()

        # Complete the current task if it exists
        if current and not current.is_complete:
            current, = await tasklist.complete_tasks(current.taskid)

        new_current, = await tasklist.create_tasks(taskspec)
        await tasklist.set_now(new_current.taskid)

        if current:
            started_ago = strfdelta(timedelta(seconds=current.total_duration))
            await ctx.reply(
                "Completed your current task and started your next one! Good luck! "
                f"You worked on '{current.content}' for {started_ago}"
            )
        else:
            await ctx.reply(
                "Started your next task, good luck!"
            )

    @cmds.command(name='plan')
    async def cmd_plan(self, ctx: cmds.Context):
        """
        Description:
            View or set a plan of tasks to do from your tasklist.
            The plan lets you work with just your immediate next tasks,
            and writing !next with no arguments will switch you to your next task in the plan.

            If given arguments, this command adds the specified tasks
            to the end of the plan. 

            See also !clearplan, !replan, !soon, !later/add
        Examples:
            ...
        """
        await ctx.reply("Planning is not implemented yet, coming soon!")
        ...

    @cmds.command(name='unplan', aliases=('clearplan',))
    async def cmd_unplan(self, ctx: cmds.Context):
        """
        Description:
            Clears your plan, or moves the 
        """
        await ctx.reply("Planning is not implemented yet, coming soon!")
        ...

