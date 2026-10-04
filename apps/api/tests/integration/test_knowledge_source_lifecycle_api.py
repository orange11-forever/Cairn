"""Consumer-visible lifecycle and history contracts for Feishu sources."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from cairn_api.auth.models import AuthSession
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.models import IngestionJob, JobKind
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.knowledge.source_service import KnowledgeSourceService
from cairn_worker.feishu_schedule import schedule_due_sources
from httpx2 import Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_source_revocation import (
    _seed_feishu_resource,  # pyright: ignore[reportPrivateUsage]
)


def _path(project_id: object, source_id: object) -> str:
    return f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}"


def _contract(response: Response, status: int, code: str | None = None, *, allow: str | None = None) -> None:
    assert response.status_code == status, response.text
    assert response.headers["x-request-id"] == "req-feishu-lifecycle"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-expose-headers"] == "X-Request-ID, Retry-After"
    assert response.headers.get("allow") == allow
    if code is not None:
        body = response.json()
        assert set(body) == {"message", "code", "traceId"}
        assert body["code"] == code and body["traceId"] == "req-feishu-lifecycle"
        assert isinstance(body["message"], str) and body["message"]


@pytest.mark.integration
def test_patch_interval_disable_restore_and_history_preserve_explicit_sharing(
    database: Database, test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        client.headers["X-Request-ID"] = "req-feishu-lifecycle"
        created = client.post(f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json={
            "name": "Docs", "documentId": "DocSync1", "credentialRef": "team",
            "accessPolicy": "project_members", "syncIntervalSeconds": 300,
        })
        _contract(created, 201)
        source_id = created.json()["id"]
        assert created.json()["accessState"] == "unverified"
        assert created.json()["syncIntervalSeconds"] == 300
        assert datetime.fromisoformat(created.json()["nextSyncAt"])
        assert all(created.json()[key] is None for key in ("lastCheckedAt", "lastSuccessAt", "lastErrorCode"))

        interval = client.patch(_path(project_id, source_id), json={"syncIntervalSeconds": None})
        _contract(interval, 200)
        assert interval.json()["syncIntervalSeconds"] is None
        assert interval.json()["nextSyncAt"] is None
        queued = client.post(_path(project_id, source_id) + "/syncs", json={})
        _contract(queued, 202)
        history = client.get(_path(project_id, source_id) + "/syncs", params={"limit": 1})
        _contract(history, 200)
        assert history.json() == {"items": [queued.json()], "nextCursor": None}

        disabled = client.patch(_path(project_id, source_id), json={"status": "disabled"})
        _contract(disabled, 200)
        assert disabled.json()["status"] == "disabled"
        assert disabled.json()["disabledAt"] is not None
        assert disabled.json()["accessState"] == "unverified"
        _contract(client.post(_path(project_id, source_id) + "/syncs", json={}), 404, "not_found")
        _contract(client.get(_path(project_id, source_id) + "/syncs"), 200)
        _contract(client.patch(_path(project_id, source_id), json={"status": "configured"}), 422, "validation_error")
        restored = client.patch(_path(project_id, source_id), json={"status": "configured", "accessPolicy": "project_members"})
        _contract(restored, 200)
        assert restored.json()["status"] == "configured"
        assert restored.json()["accessState"] == "unverified"
        assert restored.json()["disabledAt"] is None
        assert restored.json()["nextSyncAt"] is None
    with database.session_factory() as session:
        source = session.get(KnowledgeSource, source_id)
        assert source is not None and source.generation == 3


@pytest.mark.integration
@pytest.mark.parametrize("body", [
    {}, {"accessPolicy": "project_members"}, {"name": None}, {"name": ""},
    {"credentialRef": "changed"}, {"status": "configured"},
    {"syncIntervalSeconds": True}, {"syncIntervalSeconds": 299},
    {"syncIntervalSeconds": 604801}, {"syncIntervalSeconds": "300"},
    {"documentId": "Another"},
])
def test_patch_rejects_invalid_requests_without_source_mutation(
    database: Database, test_database_url: str, body: dict[str, object],
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        created = client.post(f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json={
            "name": "Docs", "documentId": "DocSync1", "credentialRef": "team", "accessPolicy": "project_members",
        })
        source_id = created.json()["id"]
        client.headers["X-Request-ID"] = "req-feishu-lifecycle"
        before = client.get(_path(project_id, source_id)).json()
        response = client.patch(_path(project_id, source_id), json=body)
        _contract(response, 422, "validation_error")
        assert client.get(_path(project_id, source_id)).json() == before


@pytest.mark.integration
def test_patch_and_history_authorization_conflict_failure_and_method_contracts(
    database: Database, test_database_url: str,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, owner, permission=None)
    with knowledge_client(knowledge_settings(test_database_url), database, owner, MemoryObjectStore()) as client:
        a = client.post(f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json={
            "name": "A", "documentId": "DocSync1", "credentialRef": "one", "accessPolicy": "project_members",
        }).json()["id"]
        b = client.post(f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json={
            "name": "B", "documentId": "DocSync1", "credentialRef": "two", "accessPolicy": "project_members",
        }).json()["id"]
        client.headers["X-Request-ID"] = "req-feishu-lifecycle"
        _contract(client.patch(_path(project_id, b), json={"credentialRef": "one", "accessPolicy": "project_members"}), 409, "source_conflict")
        _contract(client.put(_path(project_id, a), json={}), 405, "method_not_allowed", allow="DELETE, GET, PATCH")
        _contract(client.put(_path(project_id, a) + "/syncs", json={}), 405, "method_not_allowed", allow="GET, POST")
        _contract(client.get(_path(project_id, a) + "/syncs", params={"limit": 0}), 422, "validation_error")
        _contract(client.get(_path(project_id, a) + "/syncs", params={"cursor": "bad"}), 422, "invalid_cursor")
        _contract(client.patch(_path(project_id, uuid4()), json={"name": "Unknown"}), 404, "not_found")
        client.headers.pop("X-CSRF-Token")
        _contract(client.patch(_path(project_id, a), json={"name": "Blocked"}), 403, "csrf_failed")
        _contract(client.get(_path(project_id, a) + "/syncs"), 200)

    member = seed_actor(database, MembershipRole.MEMBER, org_id=owner.organization_id)
    with knowledge_client(knowledge_settings(test_database_url), database, member, MemoryObjectStore()) as client:
        client.headers["X-Request-ID"] = "req-feishu-lifecycle"
        _contract(client.patch(_path(project_id, a), json={"name": "Blocked"}), 404, "not_found")
        _contract(client.get(_path(project_id, a) + "/syncs"), 404, "not_found")

    for operation in ("patch_source", "list_syncs"):
        for failure, status, code in (
            (OperationalError("private", {}, Exception("private DB")), 503, "database_unavailable"),
            (RuntimeError("private unexpected"), 500, "internal_error"),
        ):
            with (
                knowledge_client(knowledge_settings(test_database_url), database, owner, MemoryObjectStore()) as client,
                patch(f"cairn_api.knowledge.source_service.KnowledgeSourceService.{operation}", side_effect=failure),
            ):
                client.headers["X-Request-ID"] = "req-feishu-lifecycle"
                response = (client.patch(_path(project_id, a), json={"name": "Changed"})
                    if operation == "patch_source" else client.get(_path(project_id, a) + "/syncs"))
            _contract(response, status, code)
            assert "private" not in response.text

    with knowledge_client(knowledge_settings(test_database_url), database, owner, MemoryObjectStore()) as client:
        with database.session_factory.begin() as session:
            session.execute(delete(AuthSession).where(AuthSession.user_id == owner.user_id))
        client.headers["X-Request-ID"] = "req-feishu-lifecycle"
        _contract(client.patch(_path(project_id, a), json={"name": "Blocked"}), 401, "session_invalid")
        _contract(client.get(_path(project_id, a) + "/syncs"), 401, "session_invalid")


def test_lifecycle_openapi_declares_runtime_methods_and_schemas() -> None:
    from cairn_api.app import create_app

    schema = create_app().openapi()
    path = "/api/v1/projects/{project_id}/knowledge/sources/{source_id}"
    sync_path = path + "/syncs"
    assert set(schema["paths"][path]) == {"get", "patch", "delete"}
    assert set(schema["paths"][sync_path]) == {"get", "post"}
    for operation, component, statuses, parameters in (
        (schema["paths"][path]["patch"], "KnowledgeSourceResponse",
         {"200", "401", "403", "404", "405", "409", "422", "500", "503"},
         {"project_id", "source_id", "X-CSRF-Token"}),
        (schema["paths"][sync_path]["get"], "KnowledgeSourceSyncPage",
         {"200", "401", "404", "405", "422", "500", "503"},
         {"project_id", "source_id", "cursor", "limit"}),
    ):
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{component}"
        }
        assert set(operation["responses"]) == statuses
        assert {item["name"] for item in operation["parameters"]} == parameters
        for response in operation["responses"].values():
            assert response["headers"]["X-Request-ID"]["schema"] == {"type": "string"}
            assert response["headers"]["Cache-Control"]["schema"]["const"] == "private, no-store"
    assert schema["paths"][path]["patch"]["requestBody"]["required"] is True
    assert schema["paths"][path]["patch"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FeishuSourcePatchRequest"
    }


@pytest.mark.integration
def test_scheduler_and_manual_http_race_coalesce_one_generation(
    database: Database, test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    now = datetime.now(UTC)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        created = client.post(f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json={
            "name": "Docs", "documentId": "DocSync1", "credentialRef": "team",
            "accessPolicy": "project_members", "syncIntervalSeconds": 300,
        })
    source_id = created.json()["id"]
    with database.session_factory.begin() as session:
        source = session.get(KnowledgeSource, source_id)
        assert source is not None
        source.next_sync_at = now
    manual_locked, release_manual = Event(), Event()
    manual_pid: list[int] = []
    original = KnowledgeSourceService._require_administrator  # pyright: ignore[reportPrivateUsage]

    def hold_manual_project_lock(service: KnowledgeSourceService, identity: object, current_project_id: object, *, for_update: bool) -> None:
        original(service, identity, current_project_id, for_update=for_update)  # type: ignore[arg-type]
        if for_update:
            session = service._session  # pyright: ignore[reportPrivateUsage]
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            manual_pid.append(pid)
            manual_locked.set()
            assert release_manual.wait(10)

    def manual() -> Response:
        with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
            return client.post(_path(project_id, source_id) + "/syncs", json={})

    def scheduled() -> int:
        return schedule_due_sources(database.session_factory, now)

    with patch.object(KnowledgeSourceService, "_require_administrator", hold_manual_project_lock), ThreadPoolExecutor(max_workers=2) as executor:
        manual_future = executor.submit(manual)
        assert manual_locked.wait(10)
        schedule_future = executor.submit(scheduled)
        try:
            deadline = monotonic() + 5
            blocked_pid: int | None = None
            while monotonic() < deadline:
                with database.engine.connect() as connection:
                    blocked_pid = connection.scalar(text("SELECT pid FROM pg_stat_activity WHERE :holder = ANY(pg_blocking_pids(pid)) LIMIT 1"), {"holder": manual_pid[0]})
                if blocked_pid is not None:
                    break
                if schedule_future.done():
                    schedule_future.result()
                sleep(0.01)
            assert blocked_pid is not None  # Distinct scheduler transaction is blocked on manual's project lock.
            assert blocked_pid != manual_pid[0]
        finally:
            release_manual.set()
        response, scheduled_count = manual_future.result(timeout=15), schedule_future.result(timeout=15)
    assert response.status_code == 202
    assert scheduled_count == 1
    with database.session_factory() as session:
        syncs = list(session.scalars(select(KnowledgeSourceSync)))
        source = session.get(KnowledgeSource, source_id)
        assert len(syncs) == 1 and str(syncs[0].id) == response.json()["id"]
        assert syncs[0].trigger in {"manual", "scheduled"}
        assert source is not None and source.next_sync_at == now + timedelta(seconds=300)
        assert session.scalar(select(func.count()).select_from(KnowledgeSourceSync)) == 1


@pytest.mark.integration
def test_sync_history_cursor_is_stable_for_equal_timestamps_and_disabled_source(
    database: Database, test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        created = client.post(f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json={
            "name": "Docs", "documentId": "DocSync1", "credentialRef": "team", "accessPolicy": "project_members",
        })
    source_id = UUID(created.json()["id"])
    at = datetime.now(UTC)
    ids = [UUID(int=value) for value in (301, 302, 303, 304)]
    timestamps = [at - timedelta(seconds=1), at, at, at + timedelta(seconds=1)]
    with database.session_factory.begin() as session:
        for sync_id, created_at in zip(ids, timestamps, strict=True):
            session.add(KnowledgeSourceSync(id=sync_id, org_id=actor.organization_id,
                project_id=project_id, source_id=source_id, requested_by=actor.user_id,
                created_at=created_at, trigger="manual", source_generation=1))
            session.add(IngestionJob(org_id=actor.organization_id, project_id=project_id,
                job_kind=JobKind.SYNC_FEISHU_SOURCE, target_id=sync_id,
                profile_version="feishu-sync-v1", next_attempt_at=at))
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        client.headers["X-Request-ID"] = "req-feishu-lifecycle"
        _contract(client.patch(_path(project_id, source_id), json={"status": "disabled"}), 200)
        cursor: str | None = None
        observed: list[str] = []
        for index in range(4):
            page = client.get(_path(project_id, source_id) + "/syncs", params={"limit": 1, **({"cursor": cursor} if cursor else {})})
            _contract(page, 200)
            assert len(page.json()["items"]) == 1
            observed.append(page.json()["items"][0]["id"])
            cursor = page.json()["nextCursor"]
            assert (cursor is not None) == (index < 3)
    assert observed == [str(item) for item in reversed(ids)]


@pytest.mark.integration
def test_sync_history_first_page_contains_newest_when_more_than_fifty_runs_exist(
    database: Database, test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        created = client.post(f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json={
            "name": "Docs", "documentId": "DocSync1", "credentialRef": "team", "accessPolicy": "project_members",
        })
    source_id = UUID(created.json()["id"])
    started = datetime.now(UTC) - timedelta(minutes=1)
    ids = [UUID(int=1000 + index) for index in range(55)]
    with database.session_factory.begin() as session:
        for index, sync_id in enumerate(ids):
            at = started + timedelta(seconds=index)
            session.add(KnowledgeSourceSync(
                id=sync_id, org_id=actor.organization_id, project_id=project_id,
                source_id=source_id, requested_by=actor.user_id, created_at=at,
                trigger="manual", source_generation=1,
            ))
            session.add(IngestionJob(
                org_id=actor.organization_id, project_id=project_id,
                job_kind=JobKind.SYNC_FEISHU_SOURCE, target_id=sync_id,
                profile_version="feishu-sync-v1", next_attempt_at=at,
            ))
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        client.headers["X-Request-ID"] = "req-feishu-lifecycle"
        first = client.get(_path(project_id, source_id) + "/syncs")
        _contract(first, 200)
        assert len(first.json()["items"]) == 50
        assert first.json()["items"][0]["id"] == str(ids[-1])
        cursor = first.json()["nextCursor"]
        assert cursor is not None
        second = client.get(_path(project_id, source_id) + "/syncs", params={"cursor": cursor})
        _contract(second, 200)
        assert second.json()["nextCursor"] is None
    observed = [row["id"] for page in (first, second) for row in page.json()["items"]]
    assert observed == [str(item) for item in reversed(ids)]


@pytest.mark.integration
def test_sync_response_exposes_retry_and_ready_resource_status(
    database: Database, test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        created = client.post(f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json={
            "name": "Docs", "documentId": "DocSync1", "credentialRef": "team", "accessPolicy": "project_members",
        })
        source_id = UUID(created.json()["id"])
        queued = client.post(_path(project_id, source_id) + "/syncs", json={})
        sync_id = UUID(queued.json()["id"])
    retry_at = datetime.now(UTC) + timedelta(minutes=2)
    with database.session_factory.begin() as session:
        sync = session.get(KnowledgeSourceSync, sync_id)
        job = session.scalar(select(IngestionJob).where(IngestionJob.target_id == sync_id))
        assert sync is not None and job is not None
        sync.failure_code = "feishu_rate_limited"
        job.attempt = 1
        job.next_attempt_at = retry_at
        job.last_error_code = "parser_failed"
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        pending = client.get(_path(project_id, source_id) + f"/syncs/{sync_id}")
        assert pending.status_code == 200
        assert pending.json()["failureCode"] == "feishu_rate_limited"
        assert pending.json()["errorCode"] == "parser_failed"
        assert datetime.fromisoformat(pending.json()["nextAttemptAt"]) == retry_at
        assert pending.json()["resourceStatus"] is None
    with database.session_factory() as session:
        source = session.get(KnowledgeSource, source_id)
        assert source is not None
    resource_id, version_id, _ = _seed_feishu_resource(database,
        org_id=actor.organization_id, project_id=project_id, source=source, title="Ready doc")
    with database.session_factory.begin() as session:
        sync = session.get(KnowledgeSourceSync, sync_id)
        job = session.scalar(select(IngestionJob).where(IngestionJob.target_id == sync_id))
        assert sync is not None and job is not None
        sync.resource_id = resource_id
        sync.resource_version_id = version_id
        sync.failure_code = None
        job.status = "completed"
        job.last_error_code = None
        job.completed_at = datetime.now(UTC)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore()) as client:
        completed = client.get(_path(project_id, source_id) + f"/syncs/{sync_id}")
        assert completed.status_code == 200
        assert completed.json()["resourceStatus"] == "ready"
        assert completed.json()["nextAttemptAt"] is None
        assert completed.json()["failureCode"] is None
