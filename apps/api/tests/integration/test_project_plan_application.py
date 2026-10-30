import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.db.session import Database
from cairn_api.knowledge.models import KnowledgeResource
from cairn_api.projects.models import Milestone, OutboxEvent, ProjectStage, Task, TaskDependency
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select, update

from .authorization_helpers import SeededActor
from .concurrency_helpers import LockGate, assert_waiting_on_lock, wait_for_race_event
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_knowledge_search import SearchEmbedding
from .test_project_analysis import seed_structure
from .test_project_conversations import assert_error, seed_conversation_boundary
from .test_project_plan_preview import PlanProvider

PlanningFixture = tuple[TestClient, SeededActor, UUID, UUID, UUID, dict[str, Any]]


@pytest.fixture
def planning(database: Database, test_database_url: str) -> Iterator[PlanningFixture]:
    actor, pid, rid = seed_conversation_boundary(database)
    tid = seed_structure(database, actor.organization_id, pid)
    with database.session_factory.begin() as session:
        session.execute(
            update(ResourceAclEntry)
            .where(ResourceAclEntry.resource_id == pid)
            .values(permission="write")
        )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        PlanProvider(),
    ) as client:
        response = client.post(f"/api/v1/projects/{pid}/plan-preview")
        assert response.status_code == 200, response.text
        assert response.json()["canApply"] is True
        yield (
            client,
            actor,
            pid,
            rid,
            tid,
            {"operationId": str(uuid4()), "preview": response.json()},
        )


@pytest.mark.integration
def test_apply_plan_creates_atomic_structure_and_replays_saved_result(
    database: Database, planning: PlanningFixture
) -> None:
    client, _, pid, _, _, payload = planning
    payload["preview"]["plan"]["tasks"][0]["title"] = "用户调整后的窗口确认"
    path = f"/api/v1/projects/{pid}/plans"
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["operationId"] == payload["operationId"]
    assert body["plan"]["tasks"][0]["title"] == "用户调整后的窗口确认"
    assert set(body["taskIds"]) == {"T1", "T2"}
    assert "excerpt" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-request-id"]
    replay = client.post(path, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json() == body
    assert client.get(f"{path}/{payload['operationId']}").json() == body
    assert client.get(path).json()["items"] == [body]
    with database.session_factory() as session:
        tasks = list(session.scalars(select(Task).where(Task.project_id == pid)))
        assert len(tasks) == 4
        created = {str(t.id): t for t in tasks}
        first, second = (created[body["taskIds"][key]] for key in ("T1", "T2"))
        assert first.title == "用户调整后的窗口确认"
        assert str(first.stage_id) == body["stageIds"]["P1"]
        assert str(first.milestone_id) == body["milestoneIds"]["M1"]
        assert first.status == "backlog" and first.assignee_user_id is None and first.due_at is None
        edge = session.scalar(
            select(TaskDependency).where(TaskDependency.successor_task_id == second.id)
        )
        assert edge is not None and edge.predecessor_task_id == first.id
        assert (
            session.scalar(
                select(func.count()).select_from(ProjectStage).where(ProjectStage.project_id == pid)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count()).select_from(Milestone).where(Milestone.project_id == pid)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "project.plan_applied")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "project.plan_applied")
            )
            == 1
        )
    changed = deepcopy(payload)
    changed["preview"]["plan"]["tasks"][0]["title"] = "不同请求"
    assert_error(client.post(path, json=changed), 409, "plan_operation_conflict")


@pytest.mark.integration
@pytest.mark.parametrize("change", ["task", "stage", "permission", "evidence"])
def test_apply_plan_rejects_stale_inputs_and_revoked_write(
    database: Database, planning: PlanningFixture, change: str
) -> None:
    client, actor, pid, rid, tid, payload = planning
    with database.session_factory.begin() as session:
        if change == "task":
            session.execute(update(Task).where(Task.id == tid).values(title="新任务名称"))
        elif change == "stage":
            session.execute(
                update(ProjectStage).where(ProjectStage.project_id == pid).values(name="已更新阶段")
            )
        elif change == "permission":
            session.execute(
                update(ResourceAclEntry)
                .where(ResourceAclEntry.resource_id == pid)
                .values(permission="read")
            )
        else:
            session.execute(
                update(KnowledgeResource)
                .where(KnowledgeResource.id == rid)
                .values(deleted_at=datetime.now(UTC), deleted_by=actor.user_id)
            )
    expected = (404, "not_found") if change == "permission" else (409, "project_analysis_changed")
    assert_error(client.post(f"/api/v1/projects/{pid}/plans", json=payload), *expected)
    with database.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(Task).where(Task.project_id == pid))
            == 2
        )


@pytest.mark.integration
def test_apply_plan_rolls_back_all_objects_after_final_write_failure(
    database: Database, planning: PlanningFixture
) -> None:
    client, _, pid, _, _, payload = planning
    engine = database.engine

    def fail_final_write(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.startswith("INSERT INTO project_plan_applications"):
            raise RuntimeError("injected final persistence failure")

    event.listen(engine, "before_cursor_execute", fail_final_write)
    try:
        response = client.post(f"/api/v1/projects/{pid}/plans", json=payload)
    finally:
        event.remove(engine, "before_cursor_execute", fail_final_write)
    assert_error(response, 500, "internal_error")
    with database.session_factory() as session:
        for model, count in ((Task, 2), (ProjectStage, 1), (Milestone, 1), (TaskDependency, 1)):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.project_id == pid)
                )
                == count
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "project.plan_applied")
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "project.plan_applied")
            )
            == 0
        )


@pytest.mark.integration
def test_apply_plan_requires_csrf_and_valid_graph(planning: PlanningFixture) -> None:
    client, _, pid, _, _, payload = planning
    path = f"/api/v1/projects/{pid}/plans"
    assert client.post(path, json=payload, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    payload["preview"]["plan"]["tasks"][0]["dependsOn"] = ["T2"]
    assert client.post(path, json=payload).status_code == 422


@pytest.mark.integration
def test_simultaneous_confirmation_creates_one_plan(
    database: Database,
    test_database_url: str,
    planning: PlanningFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api.projects.plan_service import ProjectPlanService

    first_client, actor, pid, _, _, payload = planning
    gate, guard = LockGate(), Lock()
    original = ProjectPlanService._guard  # pyright: ignore[reportPrivateUsage]
    registered = 0

    def gated(self: ProjectPlanService, project_id: UUID, *, write: bool = False) -> None:
        nonlocal registered
        if not write:
            return original(self, project_id, write=write)
        with guard:
            role = "holder" if registered == 0 else "waiter"
            registered += 1
        gate.register(self._session, role)  # pyright: ignore[reportPrivateUsage]
        gate.before_locked_read(self._session)  # pyright: ignore[reportPrivateUsage]
        original(self, project_id, write=write)
        gate.after_locked_read(role)

    monkeypatch.setattr(ProjectPlanService, "_guard", gated)
    with (
        knowledge_client(
            knowledge_settings(test_database_url),
            database,
            actor,
            MemoryObjectStore(),
            SearchEmbedding(),
            PlanProvider(),
        ) as second_client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        futures: list[Future[httpx2.Response]] = []
        try:
            futures.append(
                executor.submit(first_client.post, f"/api/v1/projects/{pid}/plans", json=payload)
            )
            wait_for_race_event(
                gate.holder_locked, futures, awaited_condition="first application lock"
            )
            futures.append(
                executor.submit(second_client.post, f"/api/v1/projects/{pid}/plans", json=payload)
            )
            wait_for_race_event(
                gate.waiter_entered, futures, awaited_condition="second application request"
            )
            assert_waiting_on_lock(database.engine, gate, futures)
        finally:
            gate.release_holder.set()
        responses = [future.result(timeout=10) for future in futures]
        assert [r.status_code for r in responses] == [201, 200], [r.text for r in responses]
        assert responses[0].json() == responses[1].json()
    with database.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(Task).where(Task.project_id == pid))
            == 4
        )


@pytest.mark.integration
def test_applied_plan_migration_refuses_data_loss_and_keeps_original_mapping(
    planning: PlanningFixture, test_database_url: str
) -> None:
    from alembic import command
    from alembic.config import Config

    client, _, pid, _, _, payload = planning
    path = f"/api/v1/projects/{pid}/plans"
    applied = client.post(path, json=payload)
    assert applied.status_code == 201
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="populated project plan applications"):
        command.downgrade(config, "0020_password_reset")
    assert client.get(f"{path}/{payload['operationId']}").json() == applied.json()


@pytest.mark.integration
def test_confirmed_plan_is_private_and_current_access_is_required(
    database: Database, test_database_url: str, planning: PlanningFixture
) -> None:
    from cairn_api.authorization.types import MembershipRole

    from .authorization_helpers import seed_actor

    client, actor, pid, _, _, payload = planning
    path = f"/api/v1/projects/{pid}/plans"
    assert client.post(path, json=payload).status_code == 201
    other = seed_actor(database, MembershipRole.MEMBER, org_id=actor.organization_id)
    with database.session_factory.begin() as session:
        session.add(
            ResourceAclEntry(
                org_id=actor.organization_id,
                resource_type="project",
                resource_id=pid,
                principal_type="user",
                principal_id=str(other.user_id),
                permission="write",
                granted_by_type="system",
            )
        )
    with knowledge_client(
        knowledge_settings(test_database_url), database, other, MemoryObjectStore()
    ) as other_client:
        assert other_client.get(path).json()["items"] == []
        assert_error(other_client.get(f"{path}/{payload['operationId']}"), 404, "not_found")
    with database.session_factory.begin() as session:
        session.execute(
            update(ResourceAclEntry)
            .where(ResourceAclEntry.resource_id == pid)
            .values(permission="read")
        )
    assert_error(client.post(path, json=payload), 404, "not_found")
    assert client.get(f"{path}/{payload['operationId']}").status_code == 200


@pytest.mark.integration
def test_plan_migration_metadata_matches_database_in_fresh_process(
    migrated_engine: Engine, test_database_url: str
) -> None:
    del migrated_engine
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", "check"],
        env={**os.environ, "DATABASE_URL": test_database_url},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
