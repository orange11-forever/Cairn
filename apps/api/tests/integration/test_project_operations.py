import json
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import User
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import AnswerGuidance
from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings
from cairn_api.organizations.models import Membership
from cairn_api.projects.models import OutboxEvent, Task, TaskDependency
from cairn_api.projects.operation_models import ProjectOperation
from cairn_api.projects.operation_schemas import ProjectOperationSuggestion
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, update

from .authorization_helpers import SeededActor, seed_actor
from .concurrency_helpers import LockGate, assert_waiting_on_lock, wait_for_race_event
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_project_analysis import AnalysisProvider, seed_structure
from .test_project_conversations import assert_error, seed_conversation_boundary


class OperationProvider(AnalysisProvider):
    def __init__(self) -> None:
        super().__init__()
        self.action: dict[str, Any] | None = {
            "type": "create_task",
            "title": "确认发布窗口",
            "priority": "high",
        }
        self.status = "proposed"
        self.requests: list[tuple[str, str, AnswerGuidance]] = []

    def suggest_project_operation(
        self, *, intent: str, snapshot: str, guidance: AnswerGuidance
    ) -> ProjectOperationSuggestion:
        self.requests.append((intent, snapshot, guidance))
        self.change()
        return ProjectOperationSuggestion.model_validate(
            {
                "status": self.status,
                "explanation": "根据用户本次要求调整项目",
                "action": self.action,
            }
        )


OperationsFixture = tuple[TestClient, SeededActor, UUID, UUID, OperationProvider]


@pytest.fixture
def operations(database: Database, test_database_url: str) -> Iterator[OperationsFixture]:
    actor, pid, _ = seed_conversation_boundary(database)
    tid = seed_structure(database, actor.organization_id, pid)
    with database.session_factory.begin() as session:
        session.execute(
            update(ResourceAclEntry)
            .where(ResourceAclEntry.resource_id == pid)
            .values(permission="write")
        )
    provider = OperationProvider()
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        answer_provider=provider,
    ) as client:
        yield client, actor, pid, tid, provider


def preview_payload(operations: OperationsFixture) -> dict[str, Any]:
    client, _, pid, _, _ = operations
    response = client.post(
        f"/api/v1/projects/{pid}/operation-preview",
        json={"intent": "创建一个确认发布窗口的高优先级任务"},
    )
    assert response.status_code == 200, response.text
    return {"operationId": str(uuid4()), "confirmed": True, "preview": response.json()}


@pytest.mark.integration
def test_dispatch_suggestion_uses_private_agents_and_cannot_execute_as_a_member_operation(
    database: Database, operations: OperationsFixture,
) -> None:
    client, actor, pid, tid, provider = operations
    agent_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(KnowledgeAssistantSettings(
            id=agent_id, org_id=actor.organization_id, project_id=pid, owner_id=actor.user_id,
            name="开发助手", instructions="", enabled_skill_ids=[], revision=1, is_active=True,
        ))
    provider.action = {"type": "dispatch_task", "taskId": str(tid), "assistantId": str(agent_id),
                       "assistantName": "伪造名称"}
    payload = preview_payload(operations)
    assert payload["preview"]["suggestion"]["action"]["assistantName"] == "开发助手"
    assert json.loads(provider.requests[-1][1])["codingAssistants"] == [
        {"assistantId": str(agent_id), "name": "开发助手"}]
    assert client.post(f"/api/v1/projects/{pid}/operations", json=payload).status_code == 422
    with database.session_factory() as session:
        task = session.get(Task, tid)
        assert task is not None and task.assignee_user_id is None
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0
    provider.action["assistantId"] = str(uuid4())
    assert_error(client.post(f"/api/v1/projects/{pid}/operation-preview", json={"intent": "交给其他 Agent"}),
                 503, "answer_unavailable")


@pytest.mark.integration
@pytest.mark.parametrize("clear", [False, True])
def test_member_assignment_is_explicit_canonical_and_replayable(
    database: Database, operations: OperationsFixture, clear: bool,
) -> None:
    client, actor, pid, tid, provider = operations
    target = seed_actor(database, MembershipRole.OWNER, actor.organization_id)
    with database.session_factory.begin() as session:
        session.execute(update(Task).where(Task.id == tid).values(assignee_user_id=actor.user_id))
    provider.action = {"type": "assign_task", "taskId": str(tid),
                       "assigneeUserId": None if clear else str(target.user_id),
                       "assigneeName": "模型编造的姓名"}
    payload = preview_payload(operations)
    candidates = json.loads(provider.requests[-1][1])["assignees"]
    assert str(target.user_id) in {item["userId"] for item in candidates}
    assert payload["preview"]["suggestion"]["action"]["assigneeName"] == (None if clear else "Test owner")
    with database.session_factory() as session:
        task = session.get(Task, tid)
        assert task is not None and task.assignee_user_id == actor.user_id
    # Labels are display data, never authority for the selected user ID.
    payload["preview"]["suggestion"]["action"]["assigneeName"] = "客户端伪造姓名"
    path = f"/api/v1/projects/{pid}/operations"
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    assert response.headers["x-request-id"]
    assert response.json()["action"]["assigneeName"] == (None if clear else "Test owner")
    assert response.json()["result"]["assigneeUserId"] == (None if clear else str(target.user_id))
    assert client.post(path, json=payload).json() == response.json()
    with database.session_factory() as session:
        task = session.get(Task, tid)
        assert task is not None and task.assignee_user_id == (None if clear else target.user_id)
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 1


@pytest.mark.integration
@pytest.mark.parametrize("change", ["inactive", "no_project_access"])
def test_assignment_rechecks_the_target_member_when_confirmed(
    database: Database, operations: OperationsFixture, change: str,
) -> None:
    client, actor, pid, tid, provider = operations
    target = seed_actor(database, MembershipRole.OWNER, actor.organization_id)
    provider.action = {"type": "assign_task", "taskId": str(tid), "assigneeUserId": str(target.user_id)}
    payload = preview_payload(operations)
    with database.session_factory.begin() as session:
        if change == "inactive":
            session.execute(update(User).where(User.id == target.user_id).values(is_active=False))
        else:
            session.execute(update(Membership).where(Membership.id == target.membership_id).values(role="viewer"))
    response = client.post(f"/api/v1/projects/{pid}/operations", json=payload)
    assert_error(response, 422, "invalid_assignee")
    with database.session_factory() as session:
        task = session.get(Task, tid)
        assert task is not None and task.assignee_user_id is None
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0


@pytest.mark.integration
def test_assignment_suggestions_cannot_target_another_organizations_member(
    database: Database, operations: OperationsFixture,
) -> None:
    client, _, pid, tid, provider = operations
    outside = seed_actor(database, MembershipRole.OWNER)
    provider.action = {"type": "assign_task", "taskId": str(tid), "assigneeUserId": str(outside.user_id)}
    response = client.post(f"/api/v1/projects/{pid}/operation-preview", json={"intent": "将任务分配给外部成员"})
    assert_error(response, 503, "answer_unavailable")
    candidates = json.loads(provider.requests[-1][1])["assignees"]
    assert str(outside.user_id) not in {item["userId"] for item in candidates}


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind", ["create_task", "update_task", "change_status", "add_dependency", "remove_dependency"]
)
def test_confirmed_operation_executes_existing_service_and_replays(
    database: Database, operations: OperationsFixture, kind: str
) -> None:
    client, _, pid, tid, provider = operations
    with database.session_factory() as session:
        edge = session.scalar(select(TaskDependency).where(TaskDependency.project_id == pid))
        assert edge is not None
        edge_id = edge.id
        predecessor_id = edge.predecessor_task_id
    if kind == "update_task":
        provider.action = {
            "type": kind,
            "taskId": str(tid),
            "field": "title",
            "value": "确认部署窗口",
        }
    elif kind == "change_status":
        provider.action = {"type": kind, "taskId": str(tid), "status": "in_progress"}
    elif kind == "add_dependency":
        with database.session_factory.begin() as session:
            extra = Task(org_id=operations[1].organization_id, project_id=pid, title="新前置任务")
            session.add(extra)
            session.flush()
            provider.action = {
                "type": kind,
                "predecessorTaskId": str(extra.id),
                "successorTaskId": str(tid),
            }
    elif kind == "remove_dependency":
        provider.action = {"type": kind, "taskId": str(tid), "dependencyId": str(edge_id)}
    payload = preview_payload(operations)
    path = f"/api/v1/projects/{pid}/operations"
    with database.session_factory() as session:
        before = session.scalar(select(func.count()).select_from(OutboxEvent))
    assert before is not None
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["action"]["type"] == kind
    assert body["operationId"] == payload["operationId"]
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "private, no-store"
    assert client.post(path, json=payload).json() == body
    assert client.get(f"{path}/{payload['operationId']}").json() == body
    assert client.get(path).json()["items"] == [body]
    with database.session_factory() as session:
        task = session.get(Task, tid)
        assert task is not None
        if kind == "create_task":
            created = session.get(Task, body["result"]["id"])
            assert (
                created is not None
                and created.title == "确认发布窗口"
                and created.priority == "high"
            )
        elif kind == "update_task":
            assert task.title == "确认部署窗口"
        elif kind == "change_status":
            assert task.status == "in_progress"
        elif kind == "remove_dependency":
            assert session.get(TaskDependency, edge_id) is None
            assert body["result"]["predecessorTaskId"] == str(predecessor_id)
            assert body["result"]["successorTaskId"] == str(tid)
            assert body["result"]["predecessorTitle"] == "准备验收"
            assert body["result"]["successorTitle"] == "发布版本"
        else:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(TaskDependency)
                    .where(TaskDependency.project_id == pid)
                )
                == 2
            )
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == before + 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "project.operation_applied")
            )
            == 1
        )
    changed = deepcopy(payload)
    changed["preview"]["intent"] = "另一项操作"
    assert_error(client.post(path, json=changed), 409, "operation_conflict")


@pytest.mark.integration
@pytest.mark.parametrize("change", ["task", "permission", "session"])
def test_operation_rechecks_stale_snapshot_authorization_and_session(
    database: Database, operations: OperationsFixture, change: str
) -> None:
    from datetime import UTC, datetime

    from cairn_api.auth.models import AuthSession

    client, actor, pid, tid, _ = operations
    payload = preview_payload(operations)
    with database.session_factory.begin() as session:
        if change == "task":
            session.execute(update(Task).where(Task.id == tid).values(title="已更新任务"))
        elif change == "permission":
            session.execute(
                update(ResourceAclEntry)
                .where(ResourceAclEntry.resource_id == pid)
                .values(permission="read")
            )
        else:
            session.execute(
                update(AuthSession)
                .where(AuthSession.user_id == actor.user_id)
                .values(revoked_at=datetime.now(UTC))
            )
    response = client.post(f"/api/v1/projects/{pid}/operations", json=payload)
    if change == "task":
        assert_error(response, 409, "project_analysis_changed")
    else:
        assert response.status_code in (401, 404)
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0
        assert (
            session.scalar(select(func.count()).select_from(Task).where(Task.project_id == pid))
            == 2
        )


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["cycle", "status", "grouping"])
def test_operation_preserves_existing_business_rejections(
    database: Database, operations: OperationsFixture, kind: str
) -> None:
    client, _, pid, tid, provider = operations
    with database.session_factory() as session:
        edge = session.scalar(select(TaskDependency).where(TaskDependency.project_id == pid))
        assert edge is not None
        predecessor = str(edge.predecessor_task_id)
    if kind == "cycle":
        provider.action = {
            "type": "add_dependency",
            "predecessorTaskId": str(tid),
            "successorTaskId": predecessor,
        }
        code = "dependency_cycle"
    elif kind == "status":
        provider.action = {"type": "change_status", "taskId": str(tid), "status": "backlog"}
        code = "invalid_state_transition"
    else:
        assert provider.action is not None
        provider.action["milestoneId"] = str(uuid4())
        assert_error(
            client.post(f"/api/v1/projects/{pid}/operation-preview", json={"intent": "创建任务"}),
            503,
            "answer_unavailable",
        )
        return
    payload = preview_payload(operations)
    assert_error(client.post(f"/api/v1/projects/{pid}/operations", json=payload), 409, code)


@pytest.mark.integration
def test_operation_rolls_back_actual_write_audit_and_outbox_if_record_fails(
    database: Database, operations: OperationsFixture
) -> None:
    client, _, pid, _, _ = operations
    payload = preview_payload(operations)

    def fail(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.startswith("INSERT INTO project_operations"):
            raise RuntimeError("injected operation persistence failure")

    event.listen(database.engine, "before_cursor_execute", fail)
    try:
        response = client.post(f"/api/v1/projects/{pid}/operations", json=payload)
    finally:
        event.remove(database.engine, "before_cursor_execute", fail)
    assert_error(response, 500, "internal_error")
    with database.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(Task).where(Task.project_id == pid))
            == 2
        )
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action.in_(["task.created", "project.operation_applied"]))
            )
            == 0
        )
    assert_error(
        client.get(f"/api/v1/projects/{pid}/operations/{payload['operationId']}"), 404, "not_found"
    )


@pytest.mark.integration
def test_preview_is_read_only_confirmation_csrf_and_whitelist_are_required(
    database: Database, operations: OperationsFixture
) -> None:
    client, _, pid, _, provider = operations
    payload = preview_payload(operations)
    assert provider.requests[0][0] == payload["preview"]["intent"]
    with database.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(Task).where(Task.project_id == pid))
            == 2
        )
    path = f"/api/v1/projects/{pid}/operations"
    assert client.post(path, json=payload, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    payload["confirmed"] = False
    assert client.post(path, json=payload).status_code == 422
    payload["confirmed"] = True
    payload["preview"]["suggestion"]["action"]["type"] = "run_script"
    assert client.post(path, json=payload).status_code == 422
    provider.status, provider.action = "needs_clarification", None
    response = client.post(
        f"/api/v1/projects/{pid}/operation-preview", json={"intent": "处理这个项目"}
    )
    assert response.status_code == 200 and response.json()["suggestion"]["action"] is None
    payload["preview"] = response.json()
    assert client.post(path, json=payload).status_code == 422


@pytest.mark.integration
def test_operation_history_is_private_and_migration_retains_records(
    database: Database, test_database_url: str, operations: OperationsFixture
) -> None:
    from alembic import command
    from alembic.config import Config

    client, actor, pid, _, _ = operations
    payload = preview_payload(operations)
    path = f"/api/v1/projects/{pid}/operations"
    response = client.post(path, json=payload)
    assert response.status_code == 201
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
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="populated project operations"):
        command.downgrade(config, "0021_project_plan_applications")
    assert client.get(f"{path}/{payload['operationId']}").json() == response.json()


@pytest.mark.integration
def test_concurrent_confirmation_creates_exactly_one_operation(
    database: Database,
    test_database_url: str,
    operations: OperationsFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api.projects.operation_service import ProjectOperationService

    client, actor, pid, _, _ = operations
    payload = preview_payload(operations)
    gate, guard = LockGate(), Lock()
    original, registered = ProjectOperationService._guard, 0  # pyright: ignore[reportPrivateUsage]

    def gated(self: ProjectOperationService, project_id: UUID, *, write: bool = False) -> None:
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

    monkeypatch.setattr(ProjectOperationService, "_guard", gated)
    with (
        knowledge_client(
            knowledge_settings(test_database_url),
            database,
            actor,
            MemoryObjectStore(),
            answer_provider=OperationProvider(),
        ) as second,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        futures: list[Future[httpx2.Response]] = []
        try:
            futures.append(
                executor.submit(client.post, f"/api/v1/projects/{pid}/operations", json=payload)
            )
            wait_for_race_event(
                gate.holder_locked, futures, awaited_condition="first operation lock"
            )
            futures.append(
                executor.submit(second.post, f"/api/v1/projects/{pid}/operations", json=payload)
            )
            wait_for_race_event(
                gate.waiter_entered, futures, awaited_condition="second operation request"
            )
            assert_waiting_on_lock(database.engine, gate, futures)
        finally:
            gate.release_holder.set()
        responses = [f.result(timeout=10) for f in futures]
    assert [r.status_code for r in responses] == [201, 200], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    with database.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(Task).where(Task.project_id == pid))
            == 3
        )
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 1
