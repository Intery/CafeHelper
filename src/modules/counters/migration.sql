ALTER TABLE counters ADD COLUMN category TEXT;
ALTER TABLE counter_log ADD COLUMN details TEXT;
CREATE TABLE counter_commands(
  name TEXT PRIMARY KEY,
  counterid INTEGER NOT NULL REFERENCES counters (counterid) ON UPDATE CASCADE ON DELETE CASCADE,
  lbname TEXT,
  undoname TEXT,
  response TEXT NOT NULL
);
