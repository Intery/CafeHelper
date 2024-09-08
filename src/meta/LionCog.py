from functools import partial
from typing import Any, Callable, Optional

from discord.ext.commands import Cog
from discord.ext import commands as cmds
from twitchio.ext import commands
from twitchio.ext.commands import Command, Bot
from twitchio.ext.commands.meta import CogEvent


class LionCog(Cog):
    # A set of other cogs that this cog depends on
    depends_on: set['LionCog'] = set()
    _placeholder_groups_: set[str]
    _twitch_cmds_: dict[str, Command]
    _twitch_events_: dict[str, CogEvent]
    _twitch_events_loaded_: set[Callable]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        cls._placeholder_groups_ = set()
        cls._twitch_cmds_ = {}
        cls._twitch_events_ = {}

        for base in reversed(cls.__mro__):
            for elem, value in base.__dict__.items():
                if isinstance(value, cmds.HybridGroup) and hasattr(value, '_placeholder_group_'):
                    cls._placeholder_groups_.add(value.name)
                elif isinstance(value, Command):
                    cls._twitch_cmds_[value.name] = value
                elif isinstance(value, CogEvent):
                    cls._twitch_events_[value.name] = value

    def __new__(cls, *args: Any, **kwargs: Any):
        # Patch to ensure no placeholder groups are in the command list
        self = super().__new__(cls)
        self.__cog_commands__ = [
            command for command in self.__cog_commands__ if command.name not in cls._placeholder_groups_
        ]
        return self

    async def _inject(self, bot, *args, **kwargs):
        if self.depends_on:
            not_found = {cogname for cogname in self.depends_on if not bot.get_cog(cogname)}
            raise ValueError(f"Could not load cog '{self.__class__.__name__}', dependencies missing: {not_found}")

        return await super()._inject(bot, *args, *kwargs)

    def _load_twitch_methods(self, bot: Bot):
        for name, command in self._twitch_cmds_.items():
            command._instance = self
            command.cog = self
            bot.add_command(command)

        for name, event in self._twitch_events_.items():
            callback = partial(event, self)
            self._twitch_events_loaded_.add(callback)
            bot.add_event(callback=callback, name=name)

    def _unload_twitch_methods(self, bot: Bot):
        for name in self._twitch_cmds_:
            bot.remove_command(name)

        for callback in self._twitch_events_loaded_:
            bot.remove_event(callback=callback)

        self._twitch_events_loaded_.clear()

    @classmethod
    def twitch_event(cls, event: Optional[str] = None):
        def decorator(func) -> CogEvent:
            event_name = event or func.__name__
            return CogEvent(name=event_name, func=func, module=cls.__module__)
        return decorator

    async def cog_check(self, ctx):  # type: ignore
        """
        TwitchIO assumes cog_check is a coroutine,
        so here we narrow the check to only a coroutine.

        The ctx maybe either be a twitch command context or a dpy context.
        """
        if isinstance(ctx, cmds.Context):
            return await self.cog_check_discord(ctx)
        if isinstance(ctx, commands.Context):
            return await self.cog_check_twitch(ctx)

    async def cog_check_discord(self, ctx: cmds.Context):
        return True

    async def cog_check_twitch(self, ctx: commands.Context):
        return True

    @classmethod
    def placeholder_group(cls, group: cmds.HybridGroup):
        group._placeholder_group_ = True
        return group

    def crossload_group(self, placeholder_group: cmds.HybridGroup, target_group: cmds.HybridGroup):
        """
        Crossload a placeholder group's commands into the target group
        """
        if not isinstance(placeholder_group, cmds.HybridGroup) or not isinstance(target_group, cmds.HybridGroup):
            raise ValueError("Placeholder and target groups my be HypridGroups.")
        if placeholder_group.name not in self._placeholder_groups_:
            raise ValueError("Placeholder group was not registered! Stopping to avoid duplicates.")
        if target_group.app_command is None:
            raise ValueError("Target group has no app_command to crossload into.")

        for command in placeholder_group.commands:
            placeholder_group.remove_command(command.name)
            target_group.remove_command(command.name)
            acmd = command.app_command._copy_with(parent=target_group.app_command, binding=self)
            command.app_command = acmd
            target_group.add_command(command)
