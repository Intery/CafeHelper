from data import Registry, RowModel
from data.columns import Integer, String, Timestamp


class TagData(Registry):
    class Tag(RowModel):
        """
        Schema
        ------
        CREATE TABLE channel_tags(
            tagid SERIAL PRIMARY KEY,
            channelid BIGINT NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        );
        CREATE UNIQUE INDEX channel_tags_channelid_name ON channel_tags (channelid, name);
        """
        _tablename_ = 'channel_tags'
        _cache_ ={}

        tagid = Integer(primary=True)
        channelid = Integer()
        name = String()
        content = String()
        created_by = Integer()
        created_at = Timestamp()
        updated_at = Timestamp()
