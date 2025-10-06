import re
from typing import Optional
from data import Database
from utils.lib import utc_now

from .data import Task, TaskInfo, TaskProfile, TaskData


class TasklistParseCreateError(Exception): ...


class Tasklist:
    """
    Represents the tasklist for a single user.
    """

    profileid: int
    data: TaskData
    id_tasks: dict[int, TaskInfo]
    label_ids: dict[int, int]
    current: Optional[int]
    plan: list[int]

    taskspec_re = re.compile(r"^(?P<start>\d+)((\s*(?P<range>-)\s*)(?P<end>\d*))?$")

    def __init__(
        self,
        profileid: int,
        tasks: list[TaskInfo],
        data: TaskData,
        update_callback=None,
    ):
        self.profileid = profileid
        self.data = data
        self._set_tasks(tasks)

        self._callback = update_callback

    async def refresh(self):
        tasks = await TaskInfo.fetch_where(profileid=self.profileid)
        self._set_tasks(tasks)

    def _set_tasks(self, tasks: list[TaskInfo]):
        self.id_tasks = {task.taskid: task for task in tasks}
        self.label_ids = {task.tasklabel: task.taskid for task in tasks}
        self.current = next((task.taskid for task in tasks if task.is_running), None)
        plan = [task for task in tasks if task.is_planned]
        plan.sort(key=lambda task: task.order_idx)
        self.plan = [task.taskid for task in plan]

    async def on_update(self):
        await self.refresh()
        if self._callback is not None:
            await self._callback(self)

    async def create_tasks(self, *contents, **kwargs) -> list[TaskInfo]:
        if not contents:
            return []

        rows = await self.data.tasklist.insert_many(
            ("profileid", "content", *kwargs.keys()),
            *((self.profileid, content, *kwargs.values()) for content in contents),
        )
        taskids = [row["taskid"] for row in rows]
        info = await TaskInfo.fetch_where(taskid=taskids)
        await self.on_update()
        # self.id_tasks.update({task.taskid: task for task in info})
        # self.label_ids.update({task.tasklabel: task.taskid for task in info})
        return info

    async def edit_task(self, taskid, new_content):
        await self.data.tasklist.update_where(taskid=taskid).set(content=new_content)
        await self.on_update()

    async def delete_tasks(self, *taskids):
        """
        Mark the given taskids as deleted.
        """
        if taskids:
            if self.current in taskids:
                await self.unset_now()
            planids = set(self.plan).intersection(taskids)
            if planids:
                await self.data.taskplan.delete_where(taskid=taskids)

            await self.data.tasklist.update_where(taskid=taskids).set(
                deleted_at=utc_now()
            )
            await self.on_update()

    def get_plan(self) -> list[TaskInfo]:
        return [self.id_tasks[id] for id in self.plan]

    async def push_plan_head(self, *taskids: int):
        plan = self.get_plan()
        min_idx = min([task.order_idx for task in plan], default=0)
        shift = len(taskids)
        plan_data = zip(taskids, range(min_idx - shift, min_idx))
        await self.data.taskplan.delete_where(taskid=taskids)
        await self.data.taskplan.insert_many(("taskid", "order_idx"), *plan_data)
        # Refreshing here instead of modifying cache
        # Because the planned flag will be wrong on the saved taskinfo as well
        await self.on_update()

    async def push_plan_tail(self, *taskids: int):
        plan = self.get_plan()
        max_idx = max([task.order_idx for task in plan], default=0)
        shift = len(taskids)
        plan_data = zip(taskids, range(max_idx + 1, max_idx + shift + 1))
        await self.data.taskplan.delete_where(taskid=taskids)
        await self.data.taskplan.insert_many(("taskid", "order_idx"), *plan_data)
        await self.on_update()

    async def set_plan(self, *taskids: int):
        # TODO: Should really be in a transaction
        # TODO: Should change how the plan works for data health
        if self.plan:
            await self.data.taskplan.delete_where(taskid=self.plan)
        if taskids:
            plan_data = zip(taskids, range(len(taskids)))
            await self.data.taskplan.insert_many(("taskid", "order_idx"), *plan_data)
        await self.on_update()

    def get_current(self) -> Optional[TaskInfo]:
        return self.id_tasks[self.current] if self.current is not None else None

    async def set_now(self, taskid: int):
        # Unset current task if it exists
        await self.unset_now()
        task = self.id_tasks[taskid]
        await self.data.nowlist.insert(
            taskid=taskid, last_started=None if task.is_complete else utc_now()
        )
        if task.started_at is None:
            await self.data.tasklist.update_where(taskid=taskid).set(
                started_at=utc_now()
            )

        await self.on_update()

    async def unset_now(self):
        # Unset the current task and update the duration correctly
        # Does not put the current task on the plan
        # TODO: Transaction
        # Todo: Handle deleted tasks? Might want to change the data a little
        current = self.get_current()
        if current is not None:
            now = utc_now()
            if current.last_started is not None:
                duration = (now - current.last_started).total_seconds()
                duration += current.duration
                await self.data.tasklist.update_where(taskid=current.taskid).set(
                    duration=duration
                )
            await self.data.nowlist.delete_where(taskid=current.taskid)
            await self.on_update()

    async def complete_tasks(
        self, *taskids, communityid: int | None = None
    ) -> list[TaskInfo]:
        # Remove any tasks which are already complete
        # TODO: Transaction
        # TODO: Uncomplete tasks
        taskids = [id for id in taskids if not self.id_tasks[id].is_complete]
        if taskids:
            now = utc_now()
            await self.data.tasklist.update_where(taskid=taskids).set(
                completed_at=now, completed_in=communityid
            )
            if self.current in taskids:
                current = self.get_current()
                assert current is not None
                assert current.last_started is not None

                duration = (
                    utc_now() - current.last_started
                ).total_seconds() + current.duration
                await self.data.tasklist.update_where(taskid=self.current).set(
                    duration=duration
                )
                await self.data.nowlist.update_where(taskid=self.current).set(
                    last_started=None
                )
            await self.on_update()

        # Return tasks which were actually completed
        return [self.id_tasks[taskid] for taskid in taskids]

    async def parse_taskspec(
        self, taskspec: str, multiple=True, create=True
    ) -> list[TaskInfo]:
        """
        Parse a user provide taskspec string.
        TasklistParseError
        TasklistParseNoCreateError

        taskspec is comma (not escaped) or semicolon tasks. Can't mix these, and prefer semicolon.
        No way of writing an actual semicolon, but that's too bad.

        Tasklabels (numerical indexes) may also be specified in ranges.

        NOTE: The tasklabels will include completed tasks, even if they aren't shown.
        This is inevitable, but important to note.
        """
        # First split the userstring
        if "\n" in taskspec:
            splits = taskspec.split("\n")
        elif ";" in taskspec:
            splits = taskspec.split(";")
        else:
            splits = taskspec.split(",")
        splits = [split.strip(",; \n") for split in splits]
        splits = [split for split in splits if split]

        taskids: list[Optional[int]] = []
        seen = set()
        to_create: list[tuple[int, str]] = []
        parsed: list[Optional[int]] = []

        # Get max label for use on unterminated ends
        maxlabel = max(self.label_ids.keys(), default=None)

        i = 0  # Insertion index for parsed, used in to_create
        for split in splits:
            match = self.taskspec_re.match(split)
            if match:
                # Task looks like a range or numeric
                start = int(match["start"])
                ranged = match["range"]
                end = int(match["end"] or maxlabel or -1)
                if ranged:
                    labels = list(range(start, end + 1))
                else:
                    labels = [start]
                for label in labels:
                    if label in self.label_ids:
                        taskid = self.label_ids[label]
                        if taskid not in seen:
                            i += 1
                            taskids.append(taskid)
                            seen.add(taskid)
                    else:
                        # We choose to ignore tasklabels provided which don't exist
                        pass
            else:
                # Presume it is a task we need to create
                to_create.append((i, split))
                taskids.append(None)
                i += 1
                if not create:
                    raise TasklistParseCreateError()

        for i, content in to_create:
            (task,) = await self.create_tasks(content)
            taskids[i] = task.taskid

        assert all(taskid is not None for taskid in taskids)

        return [self.id_tasks[taskid] for taskid in taskids]


class TaskRegistry:
    def __init__(self, data: TaskData, update_callback=None):
        # TODO: Also need to pass some way of fetching the UserProfile
        # Possibly community as well, in general
        # i.e. pass in the ProfileRegistry
        self.data = data
        self._callback = update_callback

    async def setup(self):
        await self.data.init()

    async def get_task_profile(self, profileid: int) -> TaskProfile:
        # TODO: If we add anything to the TaskProfile, we probably want to make this smarter
        return await TaskProfile.fetch_or_create(profileid)

    async def get_current_task(self, profileid: int) -> Optional[TaskInfo]:
        info = await TaskInfo.fetch_where(profileid=profileid, is_running=True)
        return info[0] if info else None

    async def get_tasklist(self, profileid: int):
        tasks = await TaskInfo.fetch_where(profileid=profileid)
        tasklist = Tasklist(profileid, tasks, self.data, update_callback=self._callback)
        return tasklist

    async def get_nowlist(self) -> list[TaskInfo]:
        return await TaskInfo.fetch_where(is_running=True)
