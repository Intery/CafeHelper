import datetime as dt
from itertools import chain
from psycopg import sql

from data import RowModel, Registry, Table
from data.columns import Integer, String, Timestamp, Bool

from core.data import CoreData


class VoiceTrackerData(Registry):
    # Tracked Channels
    # Current sessions
    # Session history
    # Untracked channels table
    class TrackedChannel(RowModel):
        """
        Reference model describing channels which have been used in tracking.
        TODO: Refactor into central tracking data?

        Schema
        ------
        CREATE TABLE tracked_channels(
          channelid BIGINT PRIMARY KEY,
          guildid BIGINT NOT NULL,
          deleted BOOLEAN DEFAULT FALSE,
          _timestamp TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
          FOREIGN KEY (guildid) REFERENCES guild_config (guildid) ON DELETE CASCADE
        );
        CREATE INDEX tracked_channels_guilds ON tracked_channels (guildid);
        """
        _tablename_ = "tracked_channels"
        _cache_ = {}

        channelid = Integer(primary=True)
        guildid = Integer()
        deleted = Bool()
        _timestamp = Timestamp()

    class VoiceSessionsOngoing(RowModel):
        """
        Model describing currently active voice sessions.

        Schema
        ------
        CREATE TABLE voice_sessions_ongoing(
          guildid BIGINT NOT NULL,
          userid BIGINT NOT NULL,
          channelid BIGINT REFERENCES tracked_channels (channelid),
          rating INTEGER,
          tag TEXT,
          start_time TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'UTC'),
          live_duration INTEGER NOT NULL DEFAULT 0,
          video_duration INTEGER NOT NULL DEFAULT 0,
          stream_duration INTEGER NOT NULL DEFAULT 0,
          coins_earned INTEGER NOT NULL DEFAULT 0,
          last_update TIMESTAMPTZ DEFAULT (now() AT TIME ZONE 'UTC'),
          live_stream BOOLEAN NOT NULL DEFAULT FALSE,
          live_video BOOLEAN NOT NULL DEFAULT FALSE,
          hourly_coins FLOAT NOT NULL DEFAULT 0,
          FOREIGN KEY (guildid, userid) REFERENCES members (guildid, userid) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX voice_sessions_ongoing_members ON voice_sessions_ongoing (guildid, userid);
        """
        _tablename_ = "voice_sessions_ongoing"

        guildid = Integer(primary=True)
        userid = Integer(primary=True)
        channelid = Integer()
        rating = Integer()
        tag = String()
        start_time = Timestamp()
        live_duration = Integer()
        video_duration = Integer()
        stream_duration = Integer()
        coins_earned = Integer()
        last_update = Integer()
        live_stream = Bool()
        live_video = Bool()
        hourly_coins = Integer()

        @classmethod
        async def close_study_session_at(cls, guildid: int, userid: int, _at: dt.datetime) -> int:
            conn = await cls._connector.get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT close_study_session_at(%s, %s, %s)",
                    (guildid, userid, _at)
                )
                member_data = await cursor.fetchone()

        @classmethod
        async def close_voice_sessions_at(cls, *arg_tuples):
            query = sql.SQL("""
                SELECT
                    close_study_session_at(t.guildid, t.userid, t.at)
                FROM
                    (VALUES {})
                    AS
                    t (guildid, userid, at);
            """).format(
                sql.SQL(', ').join(
                    sql.SQL("({}, {}, {})").format(
                        sql.Placeholder(), sql.Placeholder(), sql.Placeholder(),
                    )
                    for _ in arg_tuples
                )
            )
            conn = await cls._connector.get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    query,
                    tuple(chain(*arg_tuples))
                )

        @classmethod
        async def update_voice_session_at(
            cls, guildid: int, userid: int, _at: dt.datetime,
            stream: bool, video: bool, rate: float
        ) -> int:
            conn = await cls._connector.get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT * FROM update_voice_session(%s, %s, %s, %s, %s, %s)",
                    (guildid, userid, _at, stream, video, rate)
                )
                rows = await cursor.fetchall()
                return cls._make_rows(*rows)

        @classmethod
        async def update_voice_sessions_at(cls, *arg_tuples):
            query = sql.SQL("""
                UPDATE
                  voice_sessions_ongoing
                SET
                  stream_duration = (
                    CASE WHEN live_stream
                      THEN stream_duration + EXTRACT(EPOCH FROM (t.at - last_update))
                      ELSE stream_duration
                    END
                  ),
                  video_duration = (
                    CASE WHEN live_video
                      THEN video_duration + EXTRACT(EPOCH FROM (t.at - last_update))
                      ELSE video_duration
                    END
                  ),
                  live_duration = (
                    CASE WHEN live_stream OR live_video
                      THEN live_duration + EXTRACT(EPOCH FROM (t.at - last_update))
                      ELSE live_duration
                    END
                  ),
                  coins_earned = (
                    coins_earned + LEAST((EXTRACT(EPOCH FROM (t.at - last_update)) * hourly_coins) / 3600, 2147483647)
                  ),
                  last_update = t.at,
                  live_stream = t.stream,
                  live_video = t.video,
                  hourly_coins = t.rate
                FROM
                    (VALUES {})
                    AS
                    t(_guildid, _userid, at, stream, video, rate)
                WHERE
                  guildid = t._guildid
                  AND
                  userid = t._userid
                RETURNING *;
            """).format(
                sql.SQL(', ').join(
                    sql.SQL("({}, {}, {}, {}, {}, {})").format(
                        sql.Placeholder(), sql.Placeholder(), sql.Placeholder(),
                        sql.Placeholder(), sql.Placeholder(), sql.Placeholder(),
                    )
                    for _ in arg_tuples
                )
            )
            conn = await cls._connector.get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    query,
                    tuple(chain(*arg_tuples))
                )
                rows = await cursor.fetchall()
                return cls._make_rows(*rows)

    class VoiceSessions(RowModel):
        """
        Model describing completed voice sessions.

        Schema
        ------
        CREATE TABLE voice_sessions(
          sessionid SERIAL PRIMARY KEY,
          guildid BIGINT NOT NULL,
          userid BIGINT NOT NULL,
          channelid BIGINT REFERENCES tracked_channels (channelid),
          rating INTEGER,
          tag TEXT,
          start_time TIMESTAMPTZ NOT NULL,
          duration INTEGER NOT NULL,
          live_duration INTEGER DEFAULT 0,
          stream_duration INTEGER DEFAULT 0,
          video_duration INTEGER DEFAULT 0,
          transactionid INTEGER REFERENCES coin_transactions (transactionid) ON UPDATE CASCADE ON DELETE CASCADE,
          FOREIGN KEY (guildid, userid) REFERENCES members (guildid, userid) ON DELETE CASCADE
        );
        CREATE INDEX session_history_members ON session_history (guildid, userid, start_time);
        """
        _tablename_ = "voice_sessions"

        sessionid = Integer(primary=True)
        guildid = Integer()
        userid = Integer()
        channelid = Integer()
        rating = Integer()
        tag = String()
        start_time = Timestamp()
        duration = Integer()
        live_duration = Integer()
        stream_duration = Integer()
        video_duration = Integer()
        transactionid = Integer()

        @classmethod
        async def study_time_since(cls, guildid: int, userid: int, _start) -> int:
            conn = await cls._connector.get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT study_time_since(%s, %s, %s) AS result",
                    (guildid, userid, _start)
                )
                result = await cursor.fetchone()
                return (result['result'] or 0) if result else 0

        @classmethod
        async def multiple_voice_tracked_since(cls, *arg_tuples):
            query = sql.SQL("""
                SELECT
                    t.guildid AS guildid,
                    t.userid AS userid,
                    COALESCE(study_time_since(t.guildid, t.userid, t.at), 0) AS tracked
                FROM
                    (VALUES {})
                    AS
                    t (guildid, userid, at);
            """).format(
                sql.SQL(', ').join(
                    sql.SQL("({}, {}, {})").format(
                        sql.Placeholder(), sql.Placeholder(), sql.Placeholder(),
                    )
                    for _ in arg_tuples
                )
            )
            conn = await cls._connector.get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    query,
                    tuple(chain(*arg_tuples))
                )
                return await cursor.fetchall()

    """
    Schema
    ------
    CREATE TABLE untracked_channels(
      guildid BIGINT NOT NULL,
      channelid BIGINT NOT NULL
    );
    CREATE INDEX untracked_channels_guilds ON untracked_channels (guildid);
    """
    untracked_channels = Table('untracked_channels')
