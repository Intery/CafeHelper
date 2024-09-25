import datetime as dt

from data import Registry, RowModel, Table
from data.columns import Integer, String, Timestamp


class TwitchAuthData(Registry):
    class UserAuthRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE twitch_user_auth(
          userid TEXT PRIMARY KEY,
          access_token TEXT NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL,
          refresh_token TEXT NOT NULL,
          obtained_at TIMESTAMPTZ
        );
        """
        _tablename_ = 'twitch_user_auth'
        _cache_ = {}

        userid = Integer(primary=True)
        access_token = String()
        refresh_token = String()
        expires_at = Timestamp()
        obtained_at = Timestamp()

        @classmethod
        async def update_user_auth(
            cls, userid: str, token: str, refresh: str,
            expires_at: dt.datetime, obtained_at: dt.datetime,
            scopes: list[str]
            ):
            if cls._connector is None:
                raise ValueError("Attempting to use uninitialised Registry.")
            async with cls._connector.connection() as conn:
                cls._connector.conn = conn
                async with conn.transaction():
                    # Clear row for this userid
                    await cls.table.delete_where(userid=userid)

                    # Insert new user row
                    row = await cls.create(
                        userid=userid,
                        access_token=token,
                        refresh_token=refresh,
                        expires_at=expires_at,
                        obtained_at=obtained_at
                    )
                    # Insert new scope rows
                    if scopes:
                        await TwitchAuthData.user_scopes.insert_many(
                            ('userid', 'scope'),
                            *((userid, scope) for scope in scopes)
                        )
            return row

        @classmethod
        async def get_scopes_for(cls, userid: str) -> list[str]:
            """
            Get a list of scopes stored for the given user.
            Will return an empty list if the user is not authenticated.
            """
            rows = await TwitchAuthData.user_scopes.select_where(userid=userid)

            return [row.scope for row in rows] if rows else []


    """
    Schema
    ------
    CREATE TABLE twitch_user_scopes(
        userid TEXT REFERENCES twitch_user_auth (userid) ON DELETE CASCADE ON UPDATE CASCADE,
        scope TEXT
    );
    CREATE INDEX twitch_user_scopes_userid ON twitch_user_scopes (userid);
    """
    user_scopes = Table('twitch_token_scopes')
