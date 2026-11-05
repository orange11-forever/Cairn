from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.db.session import Database
from cairn_api.organizations.models import Membership
from cairn_api.projects.creation_service import ProjectCreationService
from cairn_api.projects.models import OutboxEvent, Project
from cairn_api.projects.operation_models import ProjectOperation
from sqlalchemy import func, select, update

from .concurrency_helpers import LockGate, assert_waiting_on_lock, wait_for_race_event
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_project_conversations import assert_error
from .test_project_operations import OperationsFixture, operations

__all__ = ["operations"]
BASE = "/api/v1/project-creations"


def creation_payload(fixture: OperationsFixture) -> dict[str, Any]:
    client, _, _, _, provider = fixture
    provider.action = {"type": "create_project", "name": "发布工作区", "description": "安排发布验收"}
    response = client.post(BASE + "/preview", json={"intent": "帮我建立发布工作区，用来安排发布验收"})
    assert response.status_code == 200, response.text
    assert response.headers["x-request-id"]
    return {"operationId": str(uuid4()), "confirmed": True, "preview": response.json()}


@pytest.mark.integration
def test_creation_preview_is_read_only_and_confirmation_replays_one_project(
    database: Database, operations: OperationsFixture,
) -> None:
    client, actor, _, _, _ = operations
    with database.session_factory() as session:
        before = session.scalar(select(func.count()).select_from(Project))
    assert before is not None
    payload = creation_payload(operations)
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == before
    response = client.post(BASE, json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    project_id = result["projectId"]
    assert result["action"] == {"type": "create_project", "name": "发布工作区", "description": "安排发布验收"}
    assert result["result"]["id"] == project_id
    assert client.get(f"/api/v1/projects/{project_id}").json()["name"] == "发布工作区"
    replay = client.post(BASE, json=payload)
    assert replay.status_code == 200 and replay.json() == result
    assert client.get(BASE + "/" + payload["operationId"]).json() == result
    assert client.get(f"/api/v1/projects/{project_id}/operations").json()["items"] == [result]
    changed = deepcopy(payload)
    changed["preview"]["suggestion"]["action"]["name"] = "另一个项目"
    assert_error(client.post(BASE, json=changed), 409, "operation_conflict")
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == before + 1
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 1
        assert session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "project.created", AuditLog.org_id == actor.organization_id)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "project.created")) == 1


@pytest.mark.integration
def test_creation_rechecks_membership_after_preview(database: Database, operations: OperationsFixture) -> None:
    client, actor, _, _, _ = operations
    payload = creation_payload(operations)
    with database.session_factory.begin() as session:
        session.execute(update(Membership).where(Membership.id == actor.membership_id).values(role="viewer"))
    assert_error(client.post(BASE, json=payload), 403, "forbidden")
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0


@pytest.mark.integration
def test_creation_rejects_a_project_scoped_action(operations: OperationsFixture) -> None:
    client, _, _, _, provider = operations
    provider.action = {"type": "create_task", "title": "错误类型"}
    assert_error(client.post(BASE + "/preview", json={"intent": "新建项目"}), 503, "answer_unavailable")


@pytest.mark.integration
def test_creation_explains_missing_details_without_writing(database: Database, operations: OperationsFixture) -> None:
    client, _, _, _, provider = operations
    provider.status, provider.action = "needs_clarification", None
    response = client.post(BASE + "/preview", json={"intent": "建一个"})
    assert response.status_code == 200, response.text
    assert response.json()["suggestion"]["action"] is None
    payload = {"operationId": str(uuid4()), "confirmed": True, "preview": response.json()}
    assert client.post(BASE, json=payload).status_code == 422
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectOperation)) == 0


@pytest.mark.integration
def test_creation_rechecks_role_after_the_model_returns(database: Database, operations: OperationsFixture) -> None:
    client, actor, _, _, provider = operations
    provider.action = {"type": "create_project", "name": "发布工作区"}

    def revoke() -> None:
        with database.session_factory.begin() as session:
            session.execute(update(Membership).where(Membership.id == actor.membership_id).values(role="viewer"))

    provider.change = revoke
    assert_error(client.post(BASE + "/preview", json={"intent": "创建发布工作区"}), 403, "forbidden")


@pytest.mark.integration
def test_concurrent_creation_confirmations_return_the_same_project(
    database: Database, test_database_url: str, operations: OperationsFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, actor, _, _, provider = operations
    payload = creation_payload(operations)
    gate, guard = LockGate(), Lock()
    original, registered = ProjectCreationService._creation_guard, 0  # pyright: ignore[reportPrivateUsage]

    def gated(self: ProjectCreationService, *, write: bool = True) -> None:
        nonlocal registered
        with guard:
            role = "holder" if registered == 0 else "waiter"
            registered += 1
        gate.register(self._session, role)  # pyright: ignore[reportPrivateUsage]
        gate.before_locked_read(self._session)  # pyright: ignore[reportPrivateUsage]
        original(self, write=write)
        gate.after_locked_read(role)

    monkeypatch.setattr(ProjectCreationService, "_creation_guard", gated)
    with knowledge_client(knowledge_settings(test_database_url), database, actor,
                          MemoryObjectStore(), answer_provider=provider) as second, ThreadPoolExecutor(max_workers=2) as executor:
        futures: list[Future[httpx2.Response]] = []
        try:
            futures.append(executor.submit(client.post, BASE, json=payload))
            wait_for_race_event(gate.holder_locked, futures, awaited_condition="first creation lock")
            futures.append(executor.submit(second.post, BASE, json=payload))
            wait_for_race_event(gate.waiter_entered, futures, awaited_condition="second creation request")
            assert_waiting_on_lock(database.engine, gate, futures)
        finally:
            gate.release_holder.set()
        responses = [future.result(timeout=10) for future in futures]
    assert [response.status_code for response in responses] == [201, 200], [response.text for response in responses]
    assert responses[0].json() == responses[1].json()
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Project).where(Project.name == "发布工作区")) == 1


@pytest.mark.integration
def test_creation_receipts_are_private_and_do_not_allow_a_different_organization(
    database: Database, test_database_url: str, operations: OperationsFixture,
) -> None:
    from cairn_api.authorization.types import MembershipRole

    from .authorization_helpers import seed_actor

    client, actor, _, _, provider = operations
    payload = creation_payload(operations)
    changed = deepcopy(payload)
    changed["preview"]["organizationId"] = str(uuid4())
    assert_error(client.post(BASE, json=changed), 404, "not_found")
    assert client.post(BASE, json=payload).status_code == 201
    other = seed_actor(database, MembershipRole.OWNER, actor.organization_id)
    with knowledge_client(knowledge_settings(test_database_url), database, other,
                          MemoryObjectStore(), answer_provider=provider) as outsider:
        assert_error(outsider.get(BASE + "/" + payload["operationId"]), 404, "not_found")
