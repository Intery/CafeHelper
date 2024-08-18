from data import Registry, RowModel
from data.columns import Integer, Bool, Timestamp, String
from data.models import WeakCache
from cachetools import TTLCache


class AlertsData(Registry):
    class Streamer(RowModel):
        """
        Schema
        ------
        CREATE TABLE streamers(
          userid BIGINT PRIMARY KEY,
          login_name TEXT NOT NULL,
          display_name TEXT NOT NULL
        );
        """
        _tablename_ = 'streamers'
        _cache_ = {}

        userid = Integer(primary=True)
        login_name = String()
        display_name = String()

    class AlertChannel(RowModel):
        """
        Schema
        ------
        CREATE TABLE alert_channels(
          subscriptionid SERIAL PRIMARY KEY,
          guildid BIGINT NOT NULL,
          channelid BIGINT NOT NULL,
          streamerid BIGINT NOT NULL REFERENCES streamers (userid) ON DELETE CASCADE,
          created_by BIGINT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          paused BOOLEAN NOT NULL DEFAULT FALSE,
          end_delete BOOLEAN NOT NULL DEFAULT FALSE,
          live_message TEXT,
          end_message TEXT
        );
        CREATE INDEX alert_channels_guilds ON alert_channels (guildid);
        CREATE UNIQUE INDEX alert_channels_channelid_streamerid ON alert_channels (channelid, streamerid);
        """
        _tablename_ = 'alert_channels'
        _cache_ = {}

        subscriptionid = Integer(primary=True)
        guildid = Integer()
        channelid = Integer()
        streamerid = Integer()
        display_name = Integer()
        created_by = Integer()
        created_at = Timestamp()
        paused = Bool()
        end_delete = Bool()
        live_message = String()
        end_message = String()

    class Stream(RowModel):
        """
        Schema
        ------
        CREATE TABLE streams(
          streamid SERIAL PRIMARY KEY,
          streamerid BIGINT NOT NULL REFERENCES streamers (userid) ON DELETE CASCADE,
          start_at TIMESTAMPTZ NOT NULL,
          twitch_stream_id BIGINT,
          game_name TEXT,
          title TEXT,
          end_at TIMESTAMPTZ
        );
        """
        _tablename_ = 'streams'
        _cache_ = WeakCache(TTLCache(maxsize=100, ttl=24*60*60))

        streamid = Integer(primary=True)
        streamerid = Integer()
        start_at = Timestamp()
        twitch_stream_id = Integer()
        game_name = String()
        title = String()
        end_at = Timestamp()

    class StreamAlert(RowModel):
        """
        Schema
        ------
        CREATE TABLE stream_alerts(
            alertid SERIAL PRIMARY KEY,
            streamid INTEGER NOT NULL REFERENCES streams (streamid) ON DELETE CASCADE,
            subscriptionid INTEGER NOT NULL REFERENCES alert_channels (subscriptionid) ON DELETE CASCADE,
            sent_at TIMESTAMPTZ NOT NULL,
            messageid BIGINT NOT NULL,
            resolved_at TIMESTAMPTZ
        );
        """
        _tablename_ = 'stream_alerts'
        _cache_ = WeakCache(TTLCache(maxsize=1000, ttl=24*60*60))

        alertid = Integer(primary=True)
        streamid = Integer()
        subscriptionid = Integer()
        sent_at = Timestamp()
        messageid = Integer()
        resolved_at = Timestamp()
