from data import Registry, RowModel
from data.columns import Integer, String, Timestamp


class ShoutoutData(Registry):
    class CustomShoutout(RowModel):
        """
        Schema
        ------
        CREATE TABLE shoutouts(
            userid BIGINT PRIMARY KEY,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        _tablename_ = 'shoutouts'
        _cache_ = {}

        userid = Integer(primary=True)
        content = String()
        created_at = Timestamp()
