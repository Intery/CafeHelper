from data import Registry, RowModel
from data.columns import Integer, String, Timestamp


class CounterData(Registry):
    class Counter(RowModel):
        """
        Schema
        ------
        CREATE TABLE counters(
            counterid SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE UNIQUE INDEX counters_name ON counters (name);
        """
        _tablename_ = 'counters'
        _cache_ = {}

        counterid = Integer(primary=True)
        name = String()
        created_at = Timestamp()

    class CounterEntry(RowModel):
        """
        Schema
        ------
        CREATE TABLE counter_log(
            entryid SERIAL PRIMARY KEY,
            counterid INTEGER NOT NULL REFERENCES counters (counterid) ON UPDATE CASCADE ON DELETE CASCADE,
            userid INTEGER NOT NULL,
            value INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            context_str TEXT
        );
        CREATE INDEX counter_log_counterid ON counter_log (counterid);
        """
        _tablename_ = 'counter_log'
        _cache_ = {}

        entryid = Integer(primary=True)
        counterid = Integer()
        userid = Integer()
        value = Integer()
        created_at = Timestamp()
        context_str = String()


