import asyncio
import datetime as dt
from collections import namedtuple
from functools import wraps
from typing import TYPE_CHECKING

import discord
from discord.ui.button import button, Button, ButtonStyle
from discord.ui.select import select, Select, SelectOption, ChannelSelect

from meta import LionBot, conf

from utils.lib import MessageArgs, tabulate, utc_now
from utils.ui import MessageUI
from utils.ui.msgeditor import MsgEditor

from .settings import AlertSettings as Settings
from .settings import AlertConfig as Config
from .data import AlertsData

if TYPE_CHECKING:
    from .cog import AlertCog


FakeStream = namedtuple(
    'FakeStream',
    ["streamid", "streamerid", "start_at", "twitch_stream_id", "game_name", "title", "end_at"]
)


class AlertEditorUI(MessageUI):
    setting_classes = (
        Settings.AlertPaused,
        Settings.AlertEndDelete,
        Settings.AlertEndMessage,
        Settings.AlertMessage,
        Settings.AlertChannel,
    )

    def __init__(self, bot: LionBot, sub_data: AlertsData.AlertChannel, **kwargs):
        super().__init__(**kwargs)

        self.bot = bot
        self.sub_data = sub_data
        self.subid = sub_data.subscriptionid
        self.cog: 'AlertCog' = bot.get_cog('AlertCog')
        self.config = Config(self.subid, sub_data)

    # ----- UI API -----
    def preview_stream_data(self):
        # TODO: Probably makes sense to factor this out to the cog
        # Or even generate it in the formatters themselves
        data = self.sub_data
        return FakeStream(
            -1,
            data.streamerid,
            utc_now() - dt.timedelta(hours=1),
            -1,
            "Discord Admin",
            "Testing Go Live Message",
            utc_now()
        )

    def call_and_refresh(self, func):
        """
        Generate a wrapper which runs coroutine 'func' and then refreshes the UI.
        """
        # TODO: Check whether the UI has finished interaction
        @wraps(func)
        async def wrapped(*args, **kwargs):
            await func(*args, **kwargs)
            await self.refresh()
        return wrapped

    # ----- UI Components -----

    # Pause button
    @button(label="PAUSE_PLACEHOLDER", style=ButtonStyle.blurple)
    async def pause_button(self, press: discord.Interaction, pressed: Button):
        await press.response.defer(thinking=True, ephemeral=True)
        setting = self.config.get(Settings.AlertPaused.setting_id)
        setting.value = not setting.value
        await setting.write()
        await self.refresh(thinking=press)

    async def pause_button_refresh(self):
        button = self.pause_button
        if self.config.get(Settings.AlertPaused.setting_id).value:
            button.label = "UnPause"
            button.style = ButtonStyle.grey
        else:
            button.label = "Pause"
            button.style = ButtonStyle.green

    # Delete button
    @button(label="Delete Alert", style=ButtonStyle.red)
    async def delete_button(self, press: discord.Interaction, pressed: Button):
        await press.response.defer(thinking=True, ephemeral=True)
        await self.sub_data.delete()
        embed = discord.Embed(
            colour=discord.Colour.brand_green(),
            description="Stream alert removed."
        )
        await press.edit_original_response(embed=embed)
        await self.close()

    # Close button
    @button(emoji=conf.emojis.cancel, style=ButtonStyle.red)
    async def close_button(self, press: discord.Interaction, pressed: Button):
        await press.response.defer(thinking=False)
        await self.close()

    # Edit Alert button
    @button(label="Edit Alert", style=ButtonStyle.blurple)
    async def edit_alert_button(self, press: discord.Interaction, pressed: Button):
        # Spawn MsgEditor for the live alert
        await press.response.defer(thinking=True, ephemeral=True)

        setting = self.config.get(Settings.AlertMessage.setting_id)

        stream = self.preview_stream_data()
        streamer = await self.cog.data.Streamer.fetch(self.sub_data.streamerid)

        editor = MsgEditor(
            self.bot,
            setting.value,
            callback=self.call_and_refresh(setting.editor_callback),
            formatter=await setting.generate_formatter(self.bot, stream, streamer),
            callerid=press.user.id
        )
        self._slaves.append(editor)
        await editor.run(press)

    # Edit End message
    @button(label="Edit Ending Alert", style=ButtonStyle.blurple)
    async def edit_end_button(self, press: discord.Interaction, pressed: Button):
        # Spawn MsgEditor for the ending alert
        await press.response.defer(thinking=True, ephemeral=True)
        await self.open_end_editor(press)

    async def open_end_editor(self, respond_to: discord.Interaction):
        setting = self.config.get(Settings.AlertEndMessage.setting_id)
        # Start from current live alert data if not set
        if not setting.value:
            alert_setting = self.config.get(Settings.AlertMessage.setting_id)
            setting.value = alert_setting.value

        stream = self.preview_stream_data()
        streamer = await self.cog.data.Streamer.fetch(self.sub_data.streamerid)

        editor = MsgEditor(
            self.bot,
            setting.value,
            callback=self.call_and_refresh(setting.editor_callback),
            formatter=await setting.generate_formatter(self.bot, stream, streamer),
            callerid=respond_to.user.id
        )
        self._slaves.append(editor)
        await editor.run(respond_to)
        return editor

    # Ending Mode Menu
    @select(
        cls=Select,
        placeholder="Select action to take when the stream ends",
        options=[SelectOption(label="DUMMY")],
        min_values=0, max_values=1
    )
    async def ending_mode_menu(self, selection: discord.Interaction, selected: Select):
        if not selected.values:
            await selection.response.defer()
            return

        await selection.response.defer(thinking=True, ephemeral=True)
        value = selected.values[0]

        if value == '0':
            # In Do Nothing case,
            # Ensure Delete is off and custom edit message is unset
            setting = self.config.get(Settings.AlertEndDelete.setting_id)
            if setting.value:
                setting.value = False
                await setting.write()
            setting = self.config.get(Settings.AlertEndMessage.setting_id)
            if setting.value:
                setting.value = None
                await setting.write()

            await self.refresh(thinking=selection)
        elif value == '1':
            # In Delete Alert case,
            # Set the delete setting to True
            setting = self.config.get(Settings.AlertEndDelete.setting_id)
            if not setting.value:
                setting.value = True
                await setting.write()

            await self.refresh(thinking=selection)
        elif value == '2':
            # In Edit Message case,
            # Set the delete setting to False,
            setting = self.config.get(Settings.AlertEndDelete.setting_id)
            if setting.value:
                setting.value = False
                await setting.write()

            # And open the edit message editor 
            await self.open_end_editor(selection)
            await self.refresh()

    async def ending_mode_menu_refresh(self):
        # Build menu options
        options = [
            SelectOption(
                label="Do Nothing",
                description="Don't modify the live alert message.",
                value="0",
            ),
            SelectOption(
                label="Delete Alert After Stream",
                description="Delete the live alert message.",
                value="1",
            ),
            SelectOption(
                label="Edit Alert After Stream",
                description="Edit the live alert message to a custom message. Opens editor.",
                value="2",
            ),
        ]

        # Calculate the correct default
        if self.config.get(Settings.AlertEndDelete.setting_id).value:
            options[1].default = True
        elif self.config.get(Settings.AlertEndMessage.setting_id).value:
            options[2].default = True

        self.ending_mode_menu.options = options

    # Edit channel menu
    @select(cls=ChannelSelect,
            placeholder="Select Alert Channel",
            channel_types=[discord.ChannelType.text, discord.ChannelType.voice],
            min_values=0, max_values=1)
    async def channel_menu(self, selection: discord.Interaction, selected):
        if selected.values:
            await selection.response.defer(thinking=True, ephemeral=True)
            setting = self.config.get(Settings.AlertChannel.setting_id)
            setting.value = selected.values[0]
            await setting.write()
            await self.refresh(thinking=selection)
        else:
            await selection.response.defer(thinking=False)

    async def channel_menu_refresh(self):
        # current = self.config.get(Settings.AlertChannel.setting_id).value
        # TODO: Check if discord-typed menus can have defaults yet
        # Impl in stable dpy, but not released to pip yet
        ...

    # ----- UI Flow -----
    async def make_message(self) -> MessageArgs:
        streamer = await self.cog.data.Streamer.fetch(self.sub_data.streamerid)
        if streamer is None:
            raise ValueError("Streamer row does not exist in AlertEditor")
        name = streamer.display_name

        # Build relevant setting table
        table_map = {}
        table_map['Channel'] = self.config.get(Settings.AlertChannel.setting_id).formatted
        table_map['Streamer'] = f"https://www.twitch.tv/{streamer.login_name}"
        table_map['Paused'] = self.config.get(Settings.AlertPaused.setting_id).formatted

        prop_table = '\n'.join(tabulate(*table_map.items()))

        embed = discord.Embed(
            colour=discord.Colour.dark_green(),
            title=f"Stream Alert for {name}",
            description=prop_table,
            timestamp=utc_now()
        )

        message_setting = self.config.get(Settings.AlertMessage.setting_id)
        message_desc_lines = [
            f"An alert message will be posted to {table_map['Channel']}.",
            f"Press `{self.edit_alert_button.label}`"
            " to preview or edit the alert.",
            "The following keys will be substituted in the alert message."
        ]
        keytable = tabulate(*message_setting._subkey_desc.items())
        for line in keytable:
            message_desc_lines.append(f"> {line}")

        embed.add_field(
            name=f"When {name} goes live",
            value='\n'.join(message_desc_lines),
            inline=False
        )
        
        # Determine the ending behaviour
        del_setting = self.config.get(Settings.AlertEndDelete.setting_id)
        end_msg_setting = self.config.get(Settings.AlertEndMessage.setting_id)

        if del_setting.value:
            # Deleting
            end_msg_desc = "The live alert message will be deleted."
            ...
        elif end_msg_setting.value:
            # Editing
            lines = [
                "The live alert message will edited to the configured message.",
                f"Press `{self.edit_end_button.label}` to preview or edit the message.",
                "The following substitution keys are supported "
                "*in addition* to the live alert keys."
            ]
            keytable = tabulate(
                *[(k, v) for k, v in end_msg_setting._subkey_desc.items() if k not in message_setting._subkey_desc]
            )
            for line in keytable:
                lines.append(f"> {line}")
            end_msg_desc = '\n'.join(lines)
        else:
            # Doing nothing
            end_msg_desc = "The live alert message will not be changed."

        embed.add_field(
            name=f"When {name} ends their stream",
            value=end_msg_desc,
            inline=False
        )

        return MessageArgs(embed=embed)

    async def reload(self):
        await self.sub_data.refresh()
        # Note self.config references the sub_data, and doesn't need reloading.

    async def refresh_layout(self):
        to_refresh = (
            self.pause_button_refresh(),
            self.channel_menu_refresh(),
            self.ending_mode_menu_refresh(),
        )
        await asyncio.gather(*to_refresh)

        show_end_edit = (
            not self.config.get(Settings.AlertEndDelete.setting_id).value
            and
            self.config.get(Settings.AlertEndMessage.setting_id).value
        )


        if not show_end_edit:
            # Don't show edit end button
            buttons = (
                self.edit_alert_button,
                self.pause_button, self.delete_button, self.close_button
            )
        else:
            buttons = (
                self.edit_alert_button, self.edit_end_button,
                self.pause_button, self.delete_button, self.close_button
            )

        self.set_layout(
                buttons,
                (self.ending_mode_menu,),
                (self.channel_menu,),
        )

