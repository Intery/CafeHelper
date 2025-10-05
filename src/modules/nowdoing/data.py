import datetime as dt

from data import Registry, RowModel, Table
from data.columns import String, Timestamp, Integer, Bool


class Task(RowModel):
    """
    Schema
    ------
    """

    _tablename_ = "taskslist"
    _cache_ = {}

    taskid = Integer(primary=True)
    profileid = Integer()
    content = String()
    created_at = Timestamp()
    deleted_at = Timestamp()
    duration = Integer()
    started_at = Timestamp()
    completed_at = Timestamp()
    completed_in = Integer()
    _timestamp = Timestamp()


class TaskProfile(RowModel):
    """
    Schema
    ------
    """

    _tablename_ = "task_profiles"
    _cache_ = {}

    profileid = Integer(primary=True)
    show_tips = Bool()
    show_encouragement = Bool()


class TaskInfo(RowModel):
    _tablename_ = "taskslist_info"

    taskid = Integer(primary=True)
    profileid = Integer()
    content = String()
    created_at = Timestamp()
    duration = Integer()
    started_at = Timestamp()
    completed_at = Timestamp()
    completed_in = Integer()

    last_started = Timestamp()
    order_idx = Integer()
    is_running = Bool()
    is_planned = Bool()
    is_complete = Bool()

    show_tips = Bool()
    show_encouragement = Bool()

    tasklabel = Integer()

    @property
    def total_duration(self):
        dur = self.duration
        if self.is_running and self.last_started:
            dur += (dt.datetime.now(tz=dt.UTC) - self.last_started).total_seconds()
        return int(dur)

    def format(self, length=40):
        if len(self.content) > length:
            content = self.content[: length - 3] + "..."
        else:
            content = self.content
        return f"#{self.tasklabel}: {content}"


class TaskData(Registry):
    tasklist = Task.table
    task_profiles = TaskProfile.table
    tasklist_info = TaskInfo.table

    nowlist = Table("nowlist")
    taskplan = Table("taskplan")
