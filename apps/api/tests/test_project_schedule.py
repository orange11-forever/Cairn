from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from cairn_api.projects.schedule_calculator import calculate_schedule, workday_at
from cairn_api.projects.schedule_schemas import ScheduleCalculation, ScheduleTaskInput
from cairn_api.projects.schemas import TaskPriority, TaskStatus


def task(
    n: int,
    minutes: int | None,
    *,
    status: str = "todo",
    priority: str = "medium",
    estimate: int | None = 480,
) -> ScheduleTaskInput:
    return ScheduleTaskInput(
        id=UUID(int=n),
        revision=1,
        title=f"Task {n}",
        status=TaskStatus(status),
        priority=TaskPriority(priority),
        createdAt=datetime(2026, 1, n, tzinfo=UTC),
        estimatedEffortMinutes=estimate,
        remainingEffortMinutes=minutes,
    )


def calculate(
    tasks: list[ScheduleTaskInput],
    edges: Sequence[tuple[UUID, UUID]] = (),
    capacity: int | None = 480,
    weekdays: Sequence[int] = (1, 2, 3, 4, 5),
    start: date = date(2026, 10, 26),
) -> ScheduleCalculation:
    return calculate_schedule(
        tasks=tasks, edges=list(edges), capacity=capacity, weekdays=list(weekdays), start=start
    )


def test_serial_shared_capacity_is_distinct_from_parallel_dependency_lower_bound():
    output = calculate([task(1, 480), task(2, 480)])
    assert output.completion_date == date(2026, 10, 27)
    assert [(t.start_offset_minutes, t.end_offset_minutes) for t in output.schedule] == [
        (0, 480),
        (480, 960),
    ]
    assert output.critical_chain is not None
    assert output.critical_chain.remaining_minutes == 480
    assert output.critical_chain.workday_lower_bound == 1


def test_dependency_beats_priority_and_ready_ties_are_stable():
    tasks = [task(3, 60, priority="critical"), task(2, 60), task(1, 60)]
    output = calculate(tasks, [(UUID(int=1), UUID(int=3))])
    assert [t.task_id.int for t in output.schedule] == [1, 3, 2]
    assert output.critical_chain is not None and output.critical_chain.remaining_minutes == 120
    assert output.critical_chain.task_ids == [UUID(int=1), UUID(int=3)]


def test_partial_days_reuse_capacity_and_weekend_start_advances():
    output = calculate([task(1, 300), task(2, 300)], start=date(2026, 10, 24))
    assert output.effective_start_date == date(2026, 10, 26)
    first, second = output.schedule
    assert first.start_date == first.end_date == date(2026, 10, 26)
    assert second.start_date == date(2026, 10, 26) and second.end_date == date(2026, 10, 27)


def test_zero_task_on_exact_day_boundary_finishes_same_day_without_extra_workday():
    output = calculate([task(1, 480), task(2, 0)], [(UUID(int=1), UUID(int=2))])
    first, zero = output.schedule
    assert zero.start_offset_minutes == zero.end_offset_minutes == 480
    assert (
        first.end_date
        == zero.start_date
        == zero.end_date
        == output.completion_date
        == date(2026, 10, 26)
    )
    output = calculate(
        [task(1, 480), task(2, 0), task(3, 60)],
        [(UUID(int=1), UUID(int=2)), (UUID(int=2), UUID(int=3))],
    )
    assert output.schedule[-1].start_date == date(2026, 10, 27)


def test_zero_first_and_all_zero_tasks_preserve_status_and_consume_no_time():
    tasks = [task(1, 0), task(2, 0)]
    output = calculate(tasks)
    assert output.known_remaining_minutes == 0
    assert all(t.start_date == t.end_date == date(2026, 10, 26) for t in output.schedule)
    assert [t.status for t in tasks] == ["todo", "todo"]


@pytest.mark.parametrize(
    ("tasks", "capacity", "code"),
    [
        ([task(1, None)], 480, "missing_remaining"),
        ([task(1, 30, status="blocked")], 480, "blocked_task"),
        ([task(1, 30)], None, "missing_capacity"),
        ([task(1, 30)], 0, "unavailable_capacity"),
    ],
)
def test_gaps_block_all_dates_and_critical_chain(
    tasks: list[ScheduleTaskInput], capacity: int | None, code: str
) -> None:
    output = calculate(tasks, capacity=capacity)
    assert code in {gap.code for gap in output.gaps}
    assert output.completion_date is None and output.effective_start_date is None
    assert output.schedule == [] and output.critical_chain is None


def test_done_uses_zero_cancelled_is_excluded_but_cancelled_predecessor_is_a_gap():
    tasks = [task(1, None, status="done"), task(2, 120), task(3, 999, status="cancelled")]
    output = calculate(tasks, [(UUID(int=1), UUID(int=2))])
    assert output.known_remaining_minutes == 120
    assert output.completion_date == date(2026, 10, 26)
    assert [row.task_id.int for row in output.schedule] == [2]
    output = calculate(tasks, [(UUID(int=3), UUID(int=2))])
    assert "cancelled_predecessor" in {gap.code for gap in output.gaps}
    assert output.completion_date is None


def test_missing_estimate_is_warning_and_remaining_may_exceed_estimate():
    output = calculate([task(1, 600, estimate=None), task(2, 120, estimate=30)])
    assert not output.gaps and output.completion_date == date(2026, 10, 27)
    assert "missing_estimate" in {warning.code for warning in output.warnings}
    assert output.known_remaining_minutes == 720


def test_sparse_calendar_jumps_whole_weeks_and_dates_fail_clearly_on_overflow():
    assert workday_at(date(2026, 10, 26), 1, [1]) == date(2026, 11, 2)
    assert workday_at(date(2026, 10, 26), 100_000, [1]) == date(3943, 5, 10)
    output = calculate([task(1, 2_147_483_647)], capacity=1, weekdays=(1,))
    assert "date_out_of_range" in {gap.code for gap in output.gaps}
    assert output.completion_date is None and output.schedule == []
    output = calculate([task(1, 481)], start=date.max)
    assert "date_out_of_range" in {gap.code for gap in output.gaps}


@pytest.mark.parametrize(
    "edges",
    [[(UUID(int=1), UUID(int=9))], [(UUID(int=1), UUID(int=2)), (UUID(int=2), UUID(int=1))]],
)
def test_invalid_persisted_graph_is_reported_instead_of_partial_schedule(
    edges: list[tuple[UUID, UUID]],
) -> None:
    output = calculate([task(1, 60), task(2, 60)], edges)
    assert "invalid_dependencies" in {gap.code for gap in output.gaps}
    assert output.completion_date is None and not output.schedule
