from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.projects.models import OutboxEvent, Project, Task
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from .authorization_helpers import SeededActor, seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_project_conversations import assert_error

SchedulingFixture = tuple[TestClient, SeededActor, UUID]


@pytest.fixture
def scheduling(database: Database, test_database_url: str) -> Iterator[SchedulingFixture]:
    actor = seed_actor(database, MembershipRole.MEMBER)
    pid = seed_project(database, actor, permission="write")
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        yield client, actor, pid


@pytest.mark.integration
def test_effort_edits_capacity_and_scenario_are_reproducible_and_revision_guarded(
    database: Database, scheduling: SchedulingFixture
) -> None:
    client, _, pid = scheduling
    created = client.post(
        f"/api/v1/projects/{pid}/tasks",
        json={"title": "实现", "estimatedEffortMinutes": 300, "remainingEffortMinutes": 600},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["estimatedEffortMinutes"] == 300 and task["remainingEffortMinutes"] == 600
    project = client.get(f"/api/v1/projects/{pid}").json()
    path = f"/api/v1/projects/{pid}/capacity"
    payload = {
        "expectedProjectRevision": project["revision"],
        "dailyCapacityMinutes": 480,
        "workingWeekdays": [5, 4, 3, 2, 1],
    }
    response = client.patch(path, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["workingWeekdays"] == [1, 2, 3, 4, 5]
    assert response.json()["revision"] == project["revision"] + 1
    assert_error(client.patch(path, json=payload), 409, "revision_conflict")
    scenario = client.get(f"/api/v1/projects/{pid}/schedule-scenario?startDate=2026-10-24")
    assert scenario.status_code == 200, scenario.text
    body = scenario.json()
    assert body["startDate"] == "2026-10-24" and body["effectiveStartDate"] == "2026-10-26"
    assert body["completionDate"] == "2026-10-27"
    assert body["tasks"][0]["remainingEffortMinutes"] == 600
    assert body["project"]["revision"] == response.json()["revision"]
    assert body["schedule"][0]["endOffsetMinutes"] == 600
    assert body["criticalChain"]["remainingMinutes"] == 600
    assert body["canWrite"] is True
    assert (
        scenario.headers["x-request-id"]
        and scenario.headers["cache-control"] == "private, no-store"
    )
    edited = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={
            "expectedRevision": task["revision"],
            "remainingEffortMinutes": 0,
            "estimatedEffortMinutes": None,
        },
    )
    assert edited.status_code == 200, edited.text
    assert (
        edited.json()["remainingEffortMinutes"] == 0
        and edited.json()["estimatedEffortMinutes"] is None
    )
    assert edited.json()["revision"] == task["revision"] + 1
    assert_error(
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"expectedRevision": task["revision"], "remainingEffortMinutes": 10},
        ),
        409,
        "revision_conflict",
    )
    with database.session_factory() as session:
        actual = session.get(Task, task["id"])
        assert actual is not None and actual.status == "backlog"
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "project.capacity_updated")
            )
            == 1
        )


@pytest.mark.integration
@pytest.mark.parametrize("value", [-1, True, 1.5, 2_147_483_648])
def test_effort_boundary_rejects_invalid_minutes_without_mutation(
    scheduling: SchedulingFixture, value: object
) -> None:
    client, _, pid = scheduling
    assert (
        client.post(
            f"/api/v1/projects/{pid}/tasks",
            json={"title": "无效工作量", "remainingEffortMinutes": value},
        ).status_code
        == 422
    )


@pytest.mark.integration
@pytest.mark.parametrize("weekdays", [[], [0], [8], [1, 1], [True]])
def test_capacity_boundary_rejects_invalid_calendar(
    scheduling: SchedulingFixture, weekdays: list[int]
) -> None:
    client, _, pid = scheduling
    assert (
        client.patch(
            f"/api/v1/projects/{pid}/capacity",
            json={
                "expectedProjectRevision": 1,
                "dailyCapacityMinutes": 480,
                "workingWeekdays": weekdays,
            },
        ).status_code
        == 422
    )


@pytest.mark.integration
def test_read_access_can_calculate_but_cannot_set_capacity_and_csrf_is_required(
    database: Database, scheduling: SchedulingFixture
) -> None:
    client, _, pid = scheduling
    payload = {
        "expectedProjectRevision": 1,
        "dailyCapacityMinutes": 480,
        "workingWeekdays": [1, 2, 3, 4, 5],
    }
    assert (
        client.patch(
            f"/api/v1/projects/{pid}/capacity", json=payload, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    with database.session_factory.begin() as session:
        session.execute(
            update(ResourceAclEntry)
            .where(ResourceAclEntry.resource_id == pid)
            .values(permission="read")
        )
    scenario = client.get(f"/api/v1/projects/{pid}/schedule-scenario?startDate=2026-10-26")
    assert scenario.status_code == 200 and scenario.json()["canWrite"] is False
    assert scenario.json()["completionDate"] is None
    assert "missing_capacity" in {issue["code"] for issue in scenario.json()["gaps"]}
    assert_error(client.patch(f"/api/v1/projects/{pid}/capacity", json=payload), 404, "not_found")
    assert_error(
        client.get(f"/api/v1/projects/{uuid4()}/schedule-scenario?startDate=2026-10-26"),
        404,
        "not_found",
    )
    assert (
        client.get(
            f"/api/v1/projects/{pid}/schedule-scenario?startDate=2026-10-26T00:00:00Z"
        ).status_code
        == 422
    )


@pytest.mark.integration
def test_schedule_reads_complete_project_or_explicitly_rejects_size(
    database: Database, scheduling: SchedulingFixture
) -> None:
    client, actor, pid = scheduling
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Task(
                    org_id=actor.organization_id,
                    project_id=pid,
                    title=f"任务{n}",
                    remaining_effort_minutes=0,
                )
                for n in range(1001)
            ]
        )
    response = client.get(f"/api/v1/projects/{pid}/schedule-scenario?startDate=2026-10-26")
    assert_error(response, 422, "project_graph_too_large")


@pytest.mark.integration
@pytest.mark.parametrize("field", ["effort", "capacity", "calendar"])
def test_schedule_migration_refuses_loss_of_recorded_inputs(
    database: Database, test_database_url: str, scheduling: SchedulingFixture, field: str
) -> None:
    from alembic import command
    from alembic.config import Config

    client, actor, pid = scheduling
    with database.session_factory.begin() as session:
        project = session.get(Project, pid)
        assert project is not None
        if field == "effort":
            session.add(
                Task(
                    org_id=actor.organization_id,
                    project_id=pid,
                    title="估算",
                    estimated_effort_minutes=0,
                )
            )
        elif field == "capacity":
            project.daily_capacity_minutes = 0
        else:
            project.working_weekdays = [1]
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="recorded scheduling inputs"):
        command.downgrade(config, "0022_project_operations")
    assert (
        client.get(f"/api/v1/projects/{pid}/schedule-scenario?startDate=2026-10-26").status_code
        == 200
    )
