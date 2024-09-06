from data import Registry, RowModel
from data.columns import Integer, String, Timestamp


class TwitchAuthData(Registry):
    class UserAuthRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE twitch_tokens(
          userid BIGINT PRIMARY KEY,
          access_token TEXT NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL,
          refresh_token TEXT NOT NULL,
          obtained_at TIMESTAMPTZ
        );

        """
        _tablename_ = 'twitch_tokens'
        _cache_ = {}

        userid = Integer(primary=True)
        access_token = String()
        expires_at = Timestamp()
        refresh_token = String()
        obtained_at = Timestamp()

# TODO: Scopes
