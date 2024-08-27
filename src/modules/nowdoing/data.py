from data import Registry, RowModel
from data.columns import Integer, Timestamp, String


class NowListData(Registry):
    class Task(RowModel):
        """
        Schema
        ------
        CREATE TABLE nowlist_tasks(
            userid BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            task TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            done_at TIMESTAMPTZ
        );
        """
        _tablename_ = 'nowlist_tasks'
        _cache_ = {}

        userid = Integer(primary=True)
        name = String()
        task = String()
        started_at = Timestamp()
        done_at = Timestamp()

        @property
        def is_done(self):
            return self.done_at is not None
