BEGIN;
-- Tasklist data {{{

CREATE TABLE taskslist(
  taskid INTEGER NOT NULL PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  profileid INTEGER NOT NULL REFERENCES user_profiles(profileid) ON DELETE CASCADE ON UPDATE CASCADE,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ,
  duration INTEGER NOT NULL DEFAULT 0,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  completed_in INTEGER REFERENCES communities(communityid) ON DELETE SET NULL,
  _timestamp TIMESTAMPTZ DEFAULT NOW()
);
CREATE TRIGGER tasklist_timestamp BEFORE UPDATE ON tasklist
  FOR EACH ROW EXECUTE FUNCTION update_timestamp_column();


CREATE TABLE nowlist(
  taskid INTEGER PRIMARY KEY REFERENCES taskslist(taskid) ON DELETE CASCADE ON UPDATE CASCADE,
  last_started TIMESTAMPTZ
);

CREATE TABLE taskplan(
  taskid INTEGER PRIMARY KEY REFERENCES taskslist(taskid) ON DELETE CASCADE ON UPDATE CASCADE,
  order_idx INTEGER NOT NULL
);

CREATE TABLE task_profiles(
  profileid INTEGER PRIMARY KEY REFERENCES user_profiles(profileid) ON DELETE CASCADE ON UPDATE CASCADE,
  show_tips BOOLEAN,
  show_encouragement BOOLEAN
);

CREATE VIEW
  taskslist_info
AS
  SELECT
    taskslist.taskid AS taskid,
    taskslist.profileid AS profileid,
    taskslist.content AS content,
    taskslist.created_at AS created_at,
    taskslist.duration AS duration,
    taskslist.started_at AS started_at,
    taskslist.completed_at AS completed_at,
    taskslist.completed_in AS completed_in,
    nowlist.last_started AS last_started,
    taskplan.order_idx AS order_idx,
    task_profiles.show_tips AS show_tips,
    task_profiles.show_encouragement AS show_encouragement,
    (taskslist.completed_at IS NOT NULL) AS is_complete,
    (nowlist.taskid IS NOT NULL) AS is_running,
    (taskplan.order_idx IS NOT NULL) AS is_planned,
    (row_number() OVER (PARTITION BY profileid ORDER BY taskid ASC)) AS tasklabel
  FROM
    taskslist 
    LEFT JOIN nowlist USING (taskid)
    LEFT JOIN taskplan USING (taskid)
    LEFT JOIN task_profiles USING (profileid)
  WHERE deleted_at IS NULL
  ORDER BY (profileid, taskid);


-- }}}

INSERT INTO taskslist (profileid, content, started_at, completed_at)
  SELECT 
    CAST(userid AS INTEGER) AS profileid,
    task AS content,
    started_at AS started_at,
    done_at AS completed_at
  FROM
    nowlist_tasks;

INSERT INTO nowlist (taskid, last_started)
  SELECT 
    taskid,
    CASE WHEN completed_at IS NOT NULL THEN NULL
         ELSE started_at
    END AS last_started
  FROM 
    taskslist;

UPDATE user_profiles
  SET nickname = nowlist_tasks.name 
  FROM nowlist_tasks
  WHERE user_profiles.profileid = CAST(nowlist_tasks.userid AS INTEGER);

COMMIT;
