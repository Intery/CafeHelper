from data import Registry, RowModel
from data.columns import Integer, Timestamp


class VoiceRoleData(Registry):
    class VoiceRole(RowModel):
        """
        Schema
        ------
        CREATE TABLE voice_roles(
            voice_role_id SERIAL PRIMARY KEY,
            channelid BIGINT NOT NULL,
            roleid BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX voice_role_channels on voice_roles (channelid);
        """
        # TODO: Worth associating a guildid to this as well? Denormalises though
        # Makes more theoretical sense to associated configurable channels to the guilds in a join table.
        _tablename_ = 'voice_roles'
        _cache_ = {}

        voice_role_id = Integer(primary=True)
        channelid = Integer()
        roleid = Integer()

        created_at = Timestamp()
