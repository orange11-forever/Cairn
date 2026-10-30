"""Deterministic shared-capacity scenario; never changes actual task status."""

import heapq
from datetime import date, timedelta
from uuid import UUID

from cairn_api.projects.schedule_schemas import (
    DependencyCriticalChain,
    ScheduleCalculation,
    ScheduledTask,
    ScheduleIssue,
    ScheduleTaskInput,
)

_PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def workday_at(start: date, index: int, weekdays: list[int]) -> date:
    """Index a working-day calendar with at most two partial-week walks."""
    while start.isoweekday() not in weekdays:
        start += timedelta(days=1)
    weeks, remainder = divmod(index, len(weekdays))
    day = start + timedelta(days=weeks * 7)
    while remainder:
        day += timedelta(days=1)
        if day.isoweekday() in weekdays:
            remainder -= 1
    return day


def calculate_schedule(
    *,
    tasks: list[ScheduleTaskInput],
    edges: list[tuple[UUID, UUID]],
    capacity: int | None,
    weekdays: list[int],
    start: date,
) -> ScheduleCalculation:
    by_id = {task.id: task for task in tasks}
    gaps: list[ScheduleIssue] = []
    warnings: list[ScheduleIssue] = []
    active = [task for task in tasks if task.status not in {"done", "cancelled"}]
    known = sum(task.remaining_effort_minutes or 0 for task in active)
    if capacity is None:
        gaps.append(
            ScheduleIssue(code="missing_capacity", message="请设置项目每日可用产能。", taskIds=[])
        )
    elif capacity == 0:
        gaps.append(
            ScheduleIssue(
                code="unavailable_capacity", message="每日可用产能为0，当前无法排程。", taskIds=[]
            )
        )
    for task in active:
        if task.remaining_effort_minutes is None:
            gaps.append(
                ScheduleIssue(
                    code="missing_remaining",
                    message="未完成任务缺少剩余工作量。",
                    taskIds=[task.id],
                )
            )
        if task.status == "blocked":
            gaps.append(
                ScheduleIssue(
                    code="blocked_task", message="任务已阻塞，尚无解除阻塞日期。", taskIds=[task.id]
                )
            )
        if task.estimated_effort_minutes is None:
            warnings.append(
                ScheduleIssue(
                    code="missing_estimate",
                    message="任务缺少初始估算；仍可使用已记录的剩余量计算情景。",
                    taskIds=[task.id],
                )
            )
    predecessors: dict[UUID, list[UUID]] = {task.id: [] for task in tasks}
    successors: dict[UUID, list[UUID]] = {task.id: [] for task in tasks}
    for predecessor, successor in edges:
        if predecessor not in by_id or successor not in by_id:
            gaps.append(
                ScheduleIssue(
                    code="invalid_dependencies",
                    message="任务依赖结构不完整，无法计算情景。",
                    taskIds=[],
                )
            )
            return ScheduleCalculation(knownRemainingMinutes=known, gaps=gaps, warnings=warnings)
        predecessors[successor].append(predecessor)
        successors[predecessor].append(successor)
        if (
            by_id[successor].status not in {"done", "cancelled"}
            and by_id[predecessor].status == "cancelled"
        ):
            gaps.append(
                ScheduleIssue(
                    code="cancelled_predecessor",
                    message="未完成任务的前置任务已取消，依赖尚未满足。",
                    taskIds=[predecessor, successor],
                )
            )
    counts = {task.id: len(predecessors[task.id]) for task in tasks}
    ready = [
        (_PRIORITY[task.priority], task.created_at, task.id)
        for task in tasks
        if counts[task.id] == 0
    ]
    heapq.heapify(ready)
    ordered: list[UUID] = []
    while ready:
        _, _, task_id = heapq.heappop(ready)
        ordered.append(task_id)
        for successor in successors[task_id]:
            counts[successor] -= 1
            if counts[successor] == 0:
                task = by_id[successor]
                heapq.heappush(ready, (_PRIORITY[task.priority], task.created_at, successor))
    if len(ordered) != len(tasks):
        gaps.append(
            ScheduleIssue(
                code="invalid_dependencies", message="任务依赖存在循环，无法计算情景。", taskIds=[]
            )
        )
    result = ScheduleCalculation(knownRemainingMinutes=known, gaps=gaps, warnings=warnings)
    if gaps:
        return result
    assert capacity is not None and capacity > 0
    # Done dependencies are already satisfied regardless of their former prerequisites.
    active_ids = {task.id for task in active}
    counts = {task.id: sum(p in active_ids for p in predecessors[task.id]) for task in active}
    ready = [
        (_PRIORITY[task.priority], task.created_at, task.id)
        for task in active
        if counts[task.id] == 0
    ]
    heapq.heapify(ready)
    schedule: list[ScheduledTask] = []
    longest: dict[UUID, int] = {}
    chains: dict[UUID, list[UUID]] = {}
    offset = 0
    try:
        effective = workday_at(start, 0, weekdays)
        while ready:
            _, _, task_id = heapq.heappop(ready)
            task = by_id[task_id]
            effort = task.remaining_effort_minutes
            assert effort is not None
            chain_parent = max(
                (p for p in predecessors[task_id] if p in active_ids),
                key=lambda p: (longest[p], -p.int),
                default=None,
            )
            longest[task_id] = (longest[chain_parent] if chain_parent is not None else 0) + effort
            chains[task_id] = [*(chains[chain_parent] if chain_parent is not None else []), task_id]
            # A zero-work milestone at a full-day boundary occurs at the previous
            # task's completion, rather than consuming the next working day.
            start_day = offset // capacity if effort else max(offset - 1, 0) // capacity
            end = offset + effort
            schedule.append(
                ScheduledTask(
                    taskId=task_id,
                    startOffsetMinutes=offset,
                    endOffsetMinutes=end,
                    startDate=workday_at(effective, start_day, weekdays),
                    endDate=workday_at(effective, max(end - 1, 0) // capacity, weekdays),
                )
            )
            offset = end
            for successor in successors[task_id]:
                if successor in active_ids:
                    counts[successor] -= 1
                    if counts[successor] == 0:
                        next_task = by_id[successor]
                        heapq.heappush(
                            ready, (_PRIORITY[next_task.priority], next_task.created_at, successor)
                        )
        completion = workday_at(effective, max(offset - 1, 0) // capacity, weekdays)
    except OverflowError:
        result.gaps.append(
            ScheduleIssue(
                code="date_out_of_range",
                message="情景超出支持日期范围（0001–9999年），请调整开始日期、工作量或产能。",
                taskIds=[],
            )
        )
        return result
    last = max(longest, key=lambda task_id: (longest[task_id], -task_id.int), default=None)
    critical_minutes = longest[last] if last is not None else 0
    result.effective_start_date = effective
    result.completion_date = completion
    result.schedule = schedule
    result.critical_chain = DependencyCriticalChain(
        taskIds=chains[last] if last is not None else [],
        remainingMinutes=critical_minutes,
        workdayLowerBound=critical_minutes / capacity,
    )
    return result
