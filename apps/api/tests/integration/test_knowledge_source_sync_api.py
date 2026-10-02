from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.models import IngestionJob
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.projects.models import OutboxEvent
from psycopg.errors import CheckViolation
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project


@pytest.mark.integration
def test_admin_queues_coalesces_and_polls_source_sync(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            KnowledgeSource(
                id=source_id,
                org_id=actor.organization_id,
                project_id=project_id,
                name="Manual sync",
                external_id="DocSync1",
                credential_ref="sync_credential",
                access_policy="project_members",
            )
        )
    path = f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs"
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        csrf = client.post(path, json={}, headers={"X-CSRF-Token": "wrong"})
        missing = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/{uuid4()}/syncs", json={}
        )
        invalid = client.post(path, json={"unexpected": True})
        queued = client.post(path, json={}, headers={"X-Request-ID": "req-sync-queue"})
        repeated = client.post(path, json={})
        history = client.get(path)
        polled = client.get(f"{path}/{queued.json()['id']}")
        with database.session_factory.begin() as session:
            source = session.get(KnowledgeSource, source_id)
            assert source is not None
            source.status = "disabled"
            source.disabled_at = datetime.now(UTC)
        disabled_post = client.post(path, json={})
        historical = client.get(f"{path}/{queued.json()['id']}")
        with database.session_factory.begin() as session:
            session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
        unauthenticated = client.get(f"{path}/{queued.json()['id']}")

    assert csrf.status_code == 403
    assert missing.status_code == 404
    assert history.status_code == 200 and history.json() == {"items": [queued.json()], "nextCursor": None}
    assert invalid.status_code == 422
    assert invalid.json()["traceId"] == invalid.headers["x-request-id"]
    assert queued.status_code == repeated.status_code == 202
    assert polled.status_code == historical.status_code == 200
    assert disabled_post.status_code == 404
    assert unauthenticated.status_code == 401
    assert queued.headers["x-request-id"] == "req-sync-queue"
    assert queued.headers["cache-control"] == "private, no-store"
    assert queued.json() == repeated.json() == polled.json() == historical.json()
    assert queued.json() == {
        "id": queued.json()["id"],
        "projectId": str(project_id),
        "sourceId": str(source_id),
        "status": "queued",
        "attempt": 0,
        "createdAt": queued.json()["createdAt"],
        "completedAt": None,
        "errorCode": None,
        "resourceId": None,
        "resourceVersionId": None,
        "trigger": "manual",
        "failureCode": None,
        "nextAttemptAt": None,
        "resourceStatus": None,
    }
    with database.session_factory() as session:
        audits = list(
            session.scalars(
                select(AuditLog).where(AuditLog.action == "knowledge.source_sync_queued")
            )
        )
        events = list(
            session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "knowledge.source_sync_queued")
            )
        )
    assert len(audits) == len(events) == 1
    assert set(audits[0].details) == {"projectId", "sourceId", "syncId", "jobId", "trigger"}
    assert audits[0].details["trigger"] == "manual"
    assert events[0].payload == audits[0].details
    with (
        pytest.raises(IntegrityError) as caught,
        database.session_factory.begin() as session,
    ):
        stored_sync = session.get(KnowledgeSourceSync, queued.json()["id"])
        assert stored_sync is not None
        stored_sync.resource_version_id = uuid4()
    assert isinstance(caught.value.orig, CheckViolation)
    assert caught.value.orig.diag.constraint_name == "ck_knowledge_source_syncs_result_pair"

    member = seed_actor(database, MembershipRole.MEMBER, org_id=actor.organization_id)
    other_project = seed_project(database, actor, permission=None)
    with database.session_factory.begin() as session:
        session.add(
            ResourceAclEntry(
                org_id=actor.organization_id,
                resource_type="project",
                resource_id=project_id,
                principal_type="user",
                principal_id=str(member.user_id),
                permission="manage",
                granted_by_type="system",
            )
        )
    with knowledge_client(
        knowledge_settings(test_database_url), database, member, MemoryObjectStore()
    ) as member_client:
        nonadmin = member_client.post(path, json={})
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as owner_client:
        cross_project = owner_client.post(
            f"/api/v1/projects/{other_project}/knowledge/sources/{source_id}/syncs",
            json={},
        )
    assert nonadmin.status_code == cross_project.status_code == 404


# These assertions cover the public contract at both newly added entrypoints.
def _assert_contract(
    response: Any,
    status: int,
    code: str | None = None,
    *,
    allow: str | None = None,
    origin: bool = True,
) -> None:
    assert response.status_code == status, response.text
    assert response.headers["x-request-id"] == "req-sync-contract"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-type"] == "application/json"
    assert response.headers["access-control-allow-credentials"] == "true"
    if origin:
        assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
        assert "Origin" in response.headers["vary"]
    else:
        assert "access-control-allow-origin" not in response.headers
    if allow is None:
        assert "allow" not in response.headers
    else:
        assert response.headers["allow"] == allow
    assert "retry-after" not in response.headers
    # Delayed invalid-session responses must not clear a newer login's cookie.
    assert "set-cookie" not in response.headers
    assert response.headers["access-control-expose-headers"] == "X-Request-ID, Retry-After"
    if code:
        assert set(response.json()) == {"message", "code", "traceId"}
        assert response.json()["code"] == code
        assert isinstance(response.json()["message"], str) and response.json()["message"]
        assert response.json()["traceId"] == response.headers["x-request-id"]
    else:
        assert set(response.json()) == {
            "id",
            "projectId",
            "sourceId",
            "status",
            "attempt",
            "createdAt",
            "completedAt",
            "errorCode",
            "resourceId",
            "resourceVersionId",
            "trigger",
            "failureCode",
            "nextAttemptAt",
            "resourceStatus",
        }


def _seed_sync_source(database: Database, actor: Any, project_id: UUID) -> UUID:
    source_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            KnowledgeSource(
                id=source_id,
                org_id=actor.organization_id,
                project_id=project_id,
                name="Manual sync",
                external_id=f"Doc{source_id.hex}",
                credential_ref="sync_credential",
                access_policy="project_members",
            )
        )
    return source_id


@pytest.mark.integration
def test_separate_transactions_concurrently_coalesce_one_sync_job_and_queued_event(
    database: Database,
    test_database_url: str,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import ExitStack
    from threading import Barrier

    from cairn_api.knowledge.source_service import KnowledgeSourceService
    from sqlalchemy import text

    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    source_id = _seed_sync_source(database, actor, project_id)
    path = f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs"
    gate = Barrier(2)
    pids: list[int] = []
    original = KnowledgeSourceService._require_administrator  # pyright: ignore[reportPrivateUsage]

    def concurrent_authorization(service: Any, *args: Any, **kwargs: Any) -> None:
        session = service._session
        session.execute(text("SET LOCAL statement_timeout = '8s'"))
        session.execute(text("SET LOCAL lock_timeout = '6s'"))
        pids.append(session.scalar(text("SELECT pg_backend_pid()")))
        gate.wait(timeout=5)
        original(service, *args, **kwargs)

    with ExitStack() as stack:
        clients = [
            stack.enter_context(
                knowledge_client(
                    knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
                )
            )
            for _ in range(2)
        ]
        with (
            patch.object(
                KnowledgeSourceService, "_require_administrator", concurrent_authorization
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [
                executor.submit(
                    client.post, path, json={}, headers={"X-Request-ID": "req-sync-contract"}
                )
                for client in clients
            ]
            responses = [future.result(timeout=10) for future in futures]
    assert len(set(pids)) == 2  # Distinct PostgreSQL transactions genuinely overlap.
    for response in responses:
        _assert_contract(response, 202)
    assert responses[0].json() == responses[1].json()
    with database.session_factory() as session:
        syncs = list(session.scalars(select(KnowledgeSourceSync)))
        jobs = list(session.scalars(select(IngestionJob)))
        audits = list(
            session.scalars(
                select(AuditLog).where(AuditLog.action == "knowledge.source_sync_queued")
            )
        )
        events = list(
            session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "knowledge.source_sync_queued")
            )
        )
        assert len(syncs) == len(jobs) == len(audits) == len(events) == 1
        assert jobs[0].target_id == syncs[0].id and jobs[0].status == "queued"
        assert (
            audits[0].details
            == events[0].payload
            == {
                "projectId": str(project_id),
                "sourceId": str(source_id),
                "syncId": str(syncs[0].id),
                "jobId": str(jobs[0].id),
                "trigger": "manual",
            }
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "scenario",
    [
        "cross_tenant",
        "wrong_project",
        "wrong_source",
        "unknown_sync",
        "member_manage",
        "demoted",
        "promoted",
        "session_revoked",
        "disabled",
    ],
)
def test_sync_endpoints_enforce_current_auth_and_tenant_source_scope(
    database: Database,
    test_database_url: str,
    scenario: str,
) -> None:
    from cairn_api.organizations.models import Membership

    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, owner, permission=None)
    source_id = _seed_sync_source(database, owner, project_id)
    path = f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs"
    settings = knowledge_settings(test_database_url)
    with knowledge_client(settings, database, owner, MemoryObjectStore()) as client:
        queued = client.post(path, json={})
        assert queued.status_code == 202
        sync_id = queued.json()["id"]
    actor = owner
    if scenario == "cross_tenant":
        actor = seed_actor(database, MembershipRole.OWNER)
    elif scenario in {"member_manage", "promoted"}:
        actor = seed_actor(database, MembershipRole.MEMBER, org_id=owner.organization_id)
        with database.session_factory.begin() as session:
            session.add(
                ResourceAclEntry(
                    org_id=owner.organization_id,
                    resource_type="project",
                    resource_id=project_id,
                    principal_type="user",
                    principal_id=str(actor.user_id),
                    permission="manage",
                    granted_by_type="system",
                )
            )
    if scenario == "wrong_project":
        other_project = seed_project(database, owner, permission=None)
        path = f"/api/v1/projects/{other_project}/knowledge/sources/{source_id}/syncs"
    elif scenario == "wrong_source":
        other_source = _seed_sync_source(database, owner, project_id)
        path = f"/api/v1/projects/{project_id}/knowledge/sources/{other_source}/syncs"
    elif scenario == "unknown_sync":
        sync_id = str(uuid4())
    with knowledge_client(settings, database, actor, MemoryObjectStore()) as client:
        client.headers["X-Request-ID"] = "req-sync-contract"
        with database.session_factory.begin() as session:
            if scenario in {"demoted", "promoted"}:
                membership = session.get(Membership, actor.membership_id)
                assert membership is not None
                membership.role = "member" if scenario == "demoted" else "admin"
            elif scenario == "session_revoked":
                session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
            elif scenario == "disabled":
                source = session.get(KnowledgeSource, source_id)
                assert source is not None
                source.status, source.disabled_at = "disabled", datetime.now(UTC)
        cookies = dict(client.cookies)
        get = client.get(f"{path}/{sync_id}")
        # Each revoked-session request independently presents the original cookie.
        client.cookies.update(cookies)
        post = client.post(path, json={})
    get_status = (
        200
        if scenario in {"promoted", "disabled"}
        else (401 if scenario == "session_revoked" else 404)
    )
    post_status = (
        202
        if scenario in {"promoted", "wrong_source", "unknown_sync"}
        else (401 if scenario == "session_revoked" else 404)
    )
    for response, status in ((get, get_status), (post, post_status)):
        _assert_contract(
            response,
            status,
            "session_invalid" if status == 401 else "not_found" if status == 404 else None,
        )


@pytest.mark.integration
@pytest.mark.parametrize("method", ["POST", "GET"])
@pytest.mark.parametrize("failure_type", ["database", "unexpected"])
def test_sync_endpoint_dependency_failures_have_safe_complete_contract(
    database: Database,
    test_database_url: str,
    method: str,
    failure_type: str,
) -> None:
    from sqlalchemy.exc import OperationalError

    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    path = f"/api/v1/projects/{project_id}/knowledge/sources/{uuid4()}/syncs"
    if method == "GET":
        path += f"/{uuid4()}"
    failure = (
        OperationalError("private query", {}, Exception("private database"))
        if (failure_type == "database")
        else RuntimeError("private unexpected")
    )
    with (
        knowledge_client(
            knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
        ) as client,
        patch(
            "cairn_api.knowledge.source_service.KnowledgeSourceService."
            + ("queue_sync" if method == "POST" else "get_sync"),
            side_effect=failure,
        ),
    ):
        response = client.request(
            method,
            path,
            json={} if method == "POST" else None,
            headers={"X-Request-ID": "req-sync-contract"},
        )
    _assert_contract(
        response,
        503 if failure_type == "database" else 500,
        "database_unavailable" if failure_type == "database" else "internal_error",
    )
    assert "private" not in response.text


@pytest.mark.integration
@pytest.mark.parametrize(
    "case",
    [
        "extra",
        "array",
        "null",
        "malformed",
        "post_uuid",
        "get_uuid",
        "post_method",
        "get_method",
        "missing_csrf",
        "wrong_csrf",
        "wrong_origin",
        "get_without_csrf",
    ],
)
def test_sync_validation_csrf_and_method_contract(
    database: Database,
    test_database_url: str,
    case: str,
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    source_id = _seed_sync_source(database, actor, project_id)
    path = f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs"
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        queued = client.post(path, json={})
        assert queued.status_code == 202
        poll = f"{path}/{queued.json()['id']}"
        client.headers["X-Request-ID"] = "req-sync-contract"
        if case in {"missing_csrf", "get_without_csrf"}:
            client.headers.pop("X-CSRF-Token")
        elif case == "wrong_csrf":
            client.headers["X-CSRF-Token"] = "wrong"
        elif case == "wrong_origin":
            client.headers["Origin"] = "https://evil.example"
        if case in {"extra", "array", "null", "malformed"}:
            body = {"extra": '{"forged":true}', "array": "[]", "null": "null", "malformed": "{"}[
                case
            ]
            response = client.post(path, content=body, headers={"Content-Type": "application/json"})
        elif case == "post_uuid":
            response = client.post(path.replace(str(source_id), "not-a-uuid"), json={})
        elif case == "get_uuid":
            response = client.get(f"{path}/not-a-uuid")
        elif case in {"post_method", "get_method"}:
            response = client.put(path if case == "post_method" else poll, json={})
        elif case == "get_without_csrf":
            response = client.get(poll)
        else:
            response = client.post(path, json={})
    if case in {"post_method", "get_method"}:
        _assert_contract(
            response, 405, "method_not_allowed", allow="GET, POST" if case == "post_method" else "GET"
        )
    elif case in {"missing_csrf", "wrong_csrf", "wrong_origin"}:
        _assert_contract(response, 403, "csrf_failed", origin=case != "wrong_origin")
    elif case == "get_without_csrf":
        _assert_contract(response, 200)
    else:
        _assert_contract(response, 422, "validation_error")


@pytest.mark.integration
@pytest.mark.parametrize("dependency", ["add_audit_log", "OutboxEvent"])
def test_queue_event_failure_rolls_back_sync_and_job(
    database: Database,
    test_database_url: str,
    dependency: str,
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    source_id = _seed_sync_source(database, actor, project_id)
    with (
        knowledge_client(
            knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
        ) as client,
        patch(
            f"cairn_api.knowledge.source_sync_queue.{dependency}", side_effect=RuntimeError("private")
        ),
    ):
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs",
            json={},
            headers={"X-Request-ID": "req-sync-contract"},
        )
    _assert_contract(response, 500, "internal_error")
    with database.session_factory() as session:
        for model in (KnowledgeSourceSync, IngestionJob, OutboxEvent):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "knowledge.source_sync_queued")
            )
            == 0
        )


def test_sync_openapi_exact_operations_schemas_statuses_and_headers() -> None:
    from cairn_api.app import create_app

    schema = create_app().openapi()
    path = "/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs"
    response_ref = {"$ref": "#/components/schemas/KnowledgeSourceSyncResponse"}
    for url, method, success, extra, expected_ref in (
        (path, "post", "202", {"403"}, response_ref),
        (path, "get", "200", set[str](), {"$ref": "#/components/schemas/KnowledgeSourceSyncPage"}),
        (path + "/{sync_id}", "get", "200", set[str](), response_ref),
    ):
        assert set(schema["paths"][url]) == ({"get", "post"} if url == path else {"get"})
        operation = schema["paths"][url][method]
        assert operation["operationId"] == (
            "queue_source_sync_api_v1_projects__project_id__knowledge_sources__source_id__syncs_post"
            if method == "post" else
            "list_source_syncs_api_v1_projects__project_id__knowledge_sources__source_id__syncs_get"
            if url == path else
            "get_source_sync_api_v1_projects__project_id__knowledge_sources__source_id__syncs__sync_id__get"
        )
        assert (
            set(operation["responses"])
            == {success, "401", "404", "405", "422", "500", "503"} | extra
        )
        for status, response in operation["responses"].items():
            assert response["content"]["application/json"]["schema"] == (
                expected_ref if status == success else {"$ref": "#/components/schemas/ErrorBody"}
            )
            assert response["headers"]["Cache-Control"]["schema"]["const"] == "private, no-store"
            assert response["headers"]["X-Request-ID"]["schema"] == {"type": "string"}
            assert ("Allow" in response["headers"]) == (status == "405")
        parameters = {item["name"]: item for item in operation["parameters"]}
        assert set(parameters) == {"project_id", "source_id"} | (
            {"X-CSRF-Token"} if method == "post" else {"sync_id"} if url != path else {"cursor", "limit"}
        )
        assert all(value["required"] for key, value in parameters.items() if key not in {"cursor", "limit"})
        if method == "post":
            assert operation["requestBody"]["required"] is True
            assert operation["requestBody"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/KnowledgeSourceSyncCreateRequest"
            }
    request_schema = schema["components"]["schemas"]["KnowledgeSourceSyncCreateRequest"]
    assert request_schema["properties"] == {} and request_schema["additionalProperties"] is False
    response_schema = schema["components"]["schemas"]["KnowledgeSourceSyncResponse"]
    assert set(response_schema["required"]) == {
        "id",
        "projectId",
        "sourceId",
        "status",
        "attempt",
        "createdAt",
        "completedAt",
        "errorCode",
        "resourceId",
        "resourceVersionId",
        "trigger",
        "failureCode",
        "nextAttemptAt",
        "resourceStatus",
    }
    assert response_schema["properties"]["status"]["enum"] == [
        "queued",
        "running",
        "completed",
        "failed",
    ]


@pytest.mark.integration
@pytest.mark.parametrize("retained_fact", ["request", "job"])
def test_sync_migration_rejects_populated_downgrade_without_deleting_facts(
    database: Database,
    test_database_url: str,
    retained_fact: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    source_id = _seed_sync_source(database, actor, project_id)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs", json={}
        )
    assert response.status_code == 202
    with database.session_factory.begin() as session:
        session.execute(delete(IngestionJob if retained_fact == "request" else KnowledgeSourceSync))
        source = session.get(KnowledgeSource, source_id)
        assert source is not None
        source.access_state = "available"  # Isolate the older 0007 downgrade guard.
        starting_revision = session.scalar(text("SELECT version_num FROM alembic_version"))
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="cannot downgrade while source sync"):
        command.downgrade(config, "0006_knowledge_sources")
    with database.session_factory() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == starting_revision
        assert session.scalar(select(func.count()).select_from(KnowledgeSourceSync)) == int(
            retained_fact == "request"
        )
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == int(
            retained_fact == "job"
        )
        assert session.get(KnowledgeSource, source_id) is not None


@pytest.mark.integration
@pytest.mark.parametrize("method", ["POST", "GET"])
@pytest.mark.parametrize("new_role", ["member", "admin"])
def test_sync_authorization_refreshes_identity_after_authentication(
    database: Database,
    test_database_url: str,
    method: str,
    new_role: str,
) -> None:
    from cairn_api.knowledge.source_service import KnowledgeSourceService
    from cairn_api.organizations.models import Membership

    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    source_id = _seed_sync_source(database, actor, project_id)
    path = f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs"
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        queued = client.post(path, json={})
        assert queued.status_code == 202
        with database.session_factory.begin() as session:
            membership = session.get(Membership, actor.membership_id)
            assert membership is not None
            membership.role = "admin" if new_role == "member" else "member"
            session.add(
                ResourceAclEntry(
                    org_id=actor.organization_id,
                    resource_type="project",
                    resource_id=project_id,
                    principal_type="user",
                    principal_id=str(actor.user_id),
                    permission="manage",
                    granted_by_type="system",
                )
            )
        operation = "queue_sync" if method == "POST" else "get_sync"
        original = getattr(KnowledgeSourceService, operation)

        def change_after_auth(service: Any, **kwargs: Any) -> Any:
            assert kwargs["identity"].membership.role.value != new_role
            with database.session_factory.begin() as session:
                membership = session.get(Membership, actor.membership_id)
                assert membership is not None
                membership.role = new_role
            return original(service, **kwargs)

        with patch.object(KnowledgeSourceService, operation, change_after_auth):
            response = client.request(
                method,
                path if method == "POST" else f"{path}/{queued.json()['id']}",
                json={} if method == "POST" else None,
                headers={"X-Request-ID": "req-sync-contract"},
            )
    _assert_contract(
        response,
        404 if new_role == "member" else 202 if method == "POST" else 200,
        "not_found" if new_role == "member" else None,
    )
