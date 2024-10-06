from data import Registry, RowModel
from data.columns import Integer, String, Timestamp


class ProfileData(Registry):
    class UserProfileRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE user_profiles(
            profileid SERIAL PRIMARY KEY,
            nickname TEXT,
            migrated INTEGER REFERENCES user_profiles (profileid) ON DELETE CASCADE ON UPDATE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        _tablename_ = 'user_profiles'
        _cache_ = {}

        profileid = Integer(primary=True)
        nickname = String()
        migrated = Integer()
        created_at = Timestamp()


    class DiscordProfileRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE profiles_discord(
          linkid SERIAL PRIMARY KEY,
          profileid INTEGER NOT NULL REFERENCES user_profiles (profileid) ON DELETE CASCADE ON UPDATE CASCADE,
          userid BIGINT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX profiles_discord_profileid ON profiles_discord (profileid);
        CREATE UNIQUE INDEX profiles_discord_userid ON profiles_discord (userid);
        """
        _tablename_ = 'profiles_discord'
        _cache_ = {}

        linkid = Integer(primary=True)
        profileid = Integer()
        userid = Integer()
        created_at = Integer()

        @classmethod
        async def fetch_profile(cls, profileid: int):
            rows = await cls.fetch_where(profiled=profileid)
            return next(rows, None)


    class TwitchProfileRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE profiles_twitch(
          linkid SERIAL PRIMARY KEY,
          profileid INTEGER NOT NULL REFERENCES user_profiles (profileid) ON DELETE CASCADE ON UPDATE CASCADE,
          userid TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX profiles_twitch_profileid ON profiles_twitch (profileid);
        CREATE UNIQUE INDEX profiles_twitch_userid ON profiles_twitch (userid);
        """
        _tablename_ = 'profiles_twitch'
        _cache_ = {}

        linkid = Integer(primary=True)
        profileid = Integer()
        userid = String()
        created_at = Timestamp()

        @classmethod
        async def fetch_profile(cls, profileid: int):
            rows = await cls.fetch_where(profiled=profileid)
            return next(rows, None)

    class CommunityRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE communities(
          communityid SERIAL PRIMARY KEY,
          migrated INTEGER REFERENCES user_profiles (profileid) ON DELETE CASCADE ON UPDATE CASCADE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        _tablename_ = 'communities'
        _cache_ = {}

        communityid = Integer(primary=True)
        migrated = Integer()
        created_at = Timestamp()

    class DiscordCommunityRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE communities_discord(
          guildid BIGINT PRIMARY KEY,
          communityid INTEGER NOT NULL REFERENCES communities (communityid) ON DELETE CASCADE ON UPDATE CASCADE,
          linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        _tablename_ = 'communities_discord'
        _cache_ = {}

        guildid = Integer(primary=True)
        communityid = Integer()
        linked_at = Timestamp()

        @classmethod
        async def fetch_community(cls, communityid: int):
            rows = await cls.fetch_where(communityd=communityid)
            return next(rows, None)

    class TwitchCommunityRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE communities_twitch(
          channelid TEXT PRIMARY KEY,
          communityid INTEGER NOT NULL REFERENCES communities (communityid) ON DELETE CASCADE ON UPDATE CASCADE,
          linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        _tablename_ = 'communities_twitch'
        _cache_ = {}

        channelid = String(primary=True)
        communityid = Integer()
        linked_at = Timestamp()

        @classmethod
        async def fetch_community(cls, communityid: int):
            rows = await cls.fetch_where(communityd=communityid)
            return next(rows, None)

    class CommunityMemberRow(RowModel):
        """
        Schema
        ------
        CREATE TABLE community_members(
          memberid SERIAL PRIMARY KEY,
          communityid INTEGER NOT NULL REFERENCES communities (communityid) ON DELETE CASCADE ON UPDATE CASCADE,
          profileid INTEGER NOT NULL REFERENCES user_profiles (profileid) ON DELETE CASCADE ON UPDATE CASCADE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE UNIQUE INDEX community_members_communityid_profileid ON community_members (communityid, profileid);
        """
        _tablename_ = 'community_members'
        _cache_ = {}

        memberid = Integer(primary=True)
        communityid = Integer()
        profileid = Integer()
        created_at = Timestamp()
