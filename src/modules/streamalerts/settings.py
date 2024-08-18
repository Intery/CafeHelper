from typing import Optional, Any
import json

from meta.LionBot import LionBot
from settings import ModelData
from settings.groups import SettingGroup, ModelConfig, SettingDotDict
from settings.setting_types import BoolSetting, ChannelSetting
from core.setting_types import MessageSetting
from babel.translator import LocalBabel
from utils.lib import recurse_map, replace_multiple, tabulate

from .data import AlertsData


babel = LocalBabel('streamalerts')
_p = babel._p


class AlertConfig(ModelConfig):
    settings = SettingDotDict()
    _model_settings = set()
    model = AlertsData.AlertChannel


class AlertSettings(SettingGroup):
    @AlertConfig.register_model_setting
    class AlertMessage(ModelData, MessageSetting):
        setting_id = 'alert_live_message'
        _display_name = _p('', 'live_message')

        _desc = _p(
            '',
           'Message sent to the channel when the streamer goes live.'
        )
        _long_desc = _p(
            '',
            'Message sent to the attached channel when the Twitch streamer goes live.'
        )
        _accepts = _p('', 'JSON formatted greeting message data')
        _default = json.dumps({'content': "**{display_name}** just went live at {channel_link}"})

        _model = AlertsData.AlertChannel
        _column = AlertsData.AlertChannel.live_message.name

        _subkey_desc = {
            '{display_name}': "Twitch channel name (with capitalisation)",
            '{login_name}': "Twitch channel login name (as in url)",
            '{channel_link}': "Link to the live twitch channel",
            '{stream_start}': "Numeric timestamp when stream went live",
        }
        # TODO: More stuff

        @property
        def update_message(self) -> str:
            return "The go-live notification message has been updated!"

        @classmethod
        async def generate_formatter(cls, bot: LionBot, stream: AlertsData.Stream, streamer: AlertsData.Streamer, **kwargs):
            """
            Generate a formatter function for this message
            from the provided stream and streamer data.

            The formatter function accepts and returns a message data dict.
            """
            async def formatter(data_dict: Optional[dict[str, Any]]):
                if not data_dict:
                    return None

                mapping = {
                    '{display_name}': streamer.display_name,
                    '{login_name}': streamer.login_name,
                    '{channel_link}': f"https://www.twitch.tv/{streamer.login_name}",
                    '{stream_start}': int(stream.start_at.timestamp()),
                }

                recurse_map(
                    lambda loc, value: replace_multiple(value, mapping) if isinstance(value, str) else value,
                    data_dict,
                )
                return data_dict
            return formatter

        async def editor_callback(self, editor_data):
            self.value = editor_data
            await self.write()

        def _desc_table(self, show_value: Optional[str] = None) -> list[tuple[str, str]]:
            lines = super()._desc_table(show_value=show_value)
            keytable = tabulate(*self._subkey_desc.items(), colon='')
            expline = (
                "The following placeholders will be substituted with their values."
            )
            keyfield = (
                "Placeholders",
                expline + '\n' + '\n'.join(f"> {line}" for line in keytable)
            )
            lines.append(keyfield)
            return lines

    @AlertConfig.register_model_setting
    class AlertEndMessage(ModelData, MessageSetting):
        """
        Custom ending message to edit the live alert to.
        If not set, doesn't edit the alert.
        """
        setting_id = 'alert_end_message'
        _display_name = _p('', 'end_message')

        _desc = _p(
            '',
           'Optional message to edit the live alert with when the stream ends.'
        )
        _long_desc = _p(
            '',
            "If set, and `end_delete` is not on, "
            "the live alert will be edited with this custom message "
            "when the stream ends."
        )
        _accepts = _p('', 'JSON formatted greeting message data')
        _default = None

        _model = AlertsData.AlertChannel
        _column = AlertsData.AlertChannel.end_message.name

        _subkey_desc = {
            '{display_name}': "Twitch channel name (with capitalisation)",
            '{login_name}': "Twitch channel login name (as in url)",
            '{channel_link}': "Link to the live twitch channel",
            '{stream_start}': "Numeric timestamp when stream went live",
            '{stream_end}': "Numeric timestamp when stream ended",
        }

        @property
        def update_message(self) -> str:
            if self.value:
                return "The stream ending message has been updated."
            else:
                return "The stream ending message has been unset."

        @classmethod
        async def generate_formatter(cls, bot: LionBot, stream: AlertsData.Stream, streamer: AlertsData.Streamer, **kwargs):
            """
            Generate a formatter function for this message
            from the provided stream and streamer data.

            The formatter function accepts and returns a message data dict.
            """
            # TODO: Fake stream data maker (namedtuple?) for previewing
            async def formatter(data_dict: Optional[dict[str, Any]]):
                if not data_dict:
                    return None

                mapping = {
                    '{display_name}': streamer.display_name,
                    '{login_name}': streamer.login_name,
                    '{channel_link}': f"https://www.twitch.tv/{streamer.login_name}",
                    '{stream_start}': int(stream.start_at.timestamp()),
                    '{stream_end}': int(stream.end_at.timestamp()),
                }

                recurse_map(
                    lambda loc, value: replace_multiple(value, mapping) if isinstance(value, str) else value,
                    data_dict,
                )
                return data_dict
            return formatter

        async def editor_callback(self, editor_data):
            self.value = editor_data
            await self.write()

        def _desc_table(self, show_value: Optional[str] = None) -> list[tuple[str, str]]:
            lines = super()._desc_table(show_value=show_value)
            keytable = tabulate(*self._subkey_desc.items(), colon='')
            expline = (
                "The following placeholders will be substituted with their values."
            )
            keyfield = (
                "Placeholders",
                expline + '\n' + '\n'.join(f"> {line}" for line in keytable)
            )
            lines.append(keyfield)
            return lines
        ...

    @AlertConfig.register_model_setting
    class AlertEndDelete(ModelData, BoolSetting):
        """
        Whether to delete the live alert after the stream ends.
        """
        setting_id = 'alert_end_delete'
        _display_name = _p('', 'end_delete')
        _desc = _p(
            '',
            'Whether to delete the live alert after the stream ends.'
        )
        _long_desc = _p(
            '',
            "If enabled, the live alert message will be deleted when the stream ends. "
            "This overrides the `end_message` setting."
        )
        _default = False

        _model = AlertsData.AlertChannel
        _column = AlertsData.AlertChannel.end_delete.name

        @property
        def update_message(self) -> str:
            if self.value:
                return "The live alert will be deleted at the end of the stream."
            else:
                return "The live alert will not be deleted when the stream ends."

    @AlertConfig.register_model_setting
    class AlertPaused(ModelData, BoolSetting):
        """
        Whether this live alert is currently paused.
        """
        setting_id = 'alert_paused'
        _display_name = _p('', 'paused')
        _desc = _p(
            '',
            "Whether the alert is currently paused."
        )
        _long_desc = _p(
            '',
            "Paused alerts will not trigger live notifications, "
            "although the streams will still be tracked internally."
        )
        _default = False

        _model = AlertsData.AlertChannel
        _column = AlertsData.AlertChannel.paused.name

        @property
        def update_message(self):
            if self.value:
                return "This alert is now paused"
            else:
                return "This alert has been unpaused"

    @AlertConfig.register_model_setting
    class AlertChannel(ModelData, ChannelSetting):
        """
        The channel associated to this alert.
        """
        setting_id = 'alert_channel'
        _display_name = _p('', 'channel')
        _desc = _p(
            '',
            "The Discord channel this live alert will be sent in."
        )
        _long_desc = _desc

        # Note that this cannot actually be None,
        # as there is no UI pathway to unset the setting.
        _default = None

        _model = AlertsData.AlertChannel
        _column = AlertsData.AlertChannel.channelid.name

        @property
        def update_message(self):
            return f"This alert will now be posted to {self.value.channel.mention}"
