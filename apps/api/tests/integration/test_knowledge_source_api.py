import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from cairn_api.app import create_app
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.knowledge.source_models import KnowledgeSource
from cairn_api.organizations.models import Membership
from cairn_api.projects import repository as project_repository
from cairn_api.projects.models import OutboxEvent, Project
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .authorization_helpers import seed_actor
from .concurrency_helpers import (
    FUTURE_SECONDS,
    LockGate,
    assert_waiting_on_lock,
    install_race_session_deadlines,
    shutdown_race_executor,
    terminate_race_backends,
    wait_for_race_event,
)
from .knowledge_helpers import (
    MemoryObjectStore,
    knowledge_client,
    knowledge_settings,
    seed_project,
)


def _payload(**overrides: object) -> dict[str, object]:
    return {
        "name": "Engineering handbook",
        "documentId": "Doc123",
        "credentialRef": "engineering_feishu",
        "accessPolicy": "project_members",
        **overrides,
    }


def _assert_protected_headers(response: Response, request_id: str) -> None:
    assert response.headers["x-request-id"] == request_id
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"


@pytest.mark.integration
def test_feishu_source_routes_are_registered() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    assert "/api/v1/projects/{project_id}/knowledge/sources/feishu" in paths
    assert "/api/v1/projects/{project_id}/knowledge/sources" in paths
    assert "/api/v1/projects/{project_id}/knowledge/sources/{source_id}" in paths
    create = paths["/api/v1/projects/{project_id}/knowledge/sources/feishu"]["post"]
    source_list = paths["/api/v1/projects/{project_id}/knowledge/sources"]["get"]
    detail = paths["/api/v1/projects/{project_id}/knowledge/sources/{source_id}"]
    assert set(create["requestBody"]["content"]) == {"application/json"}
    for operation, statuses in (
        (create, {"201", "401", "403", "404", "405", "409", "422", "500", "503"}),
        (source_list, {"200", "401", "404", "405", "422", "500", "503"}),
        (detail["get"], {"200", "401", "404", "405", "422", "500", "503"}),
        (detail["delete"], {"204", "401", "403", "404", "405", "422", "500", "503"}),
    ):
        assert set(operation["responses"]) == statuses
        for response in operation["responses"].values():
            assert "X-Request-ID" in response["headers"]
            assert "Cache-Control" in response["headers"]
    parameters = {parameter["name"]: parameter for parameter in source_list["parameters"]}
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 50,
        "title": "Limit",
    }
    assert source_list["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/KnowledgeSourcePage")
    assert any(
        parameter["name"] == "X-CSRF-Token" and parameter["required"] is True
        for parameter in create["parameters"]
    )
    assert any(
        parameter["name"] == "X-CSRF-Token" and parameter["required"] is True
        for parameter in detail["delete"]["parameters"]
    )


@pytest.mark.integration
def test_feishu_source_create_list_detail_disable_flow_is_atomic_and_traced(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    settings = knowledge_settings(test_database_url)
    with knowledge_client(settings, database, actor, MemoryObjectStore()) as client:
        created = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
            json=_payload(name="  Engineering handbook  "),
            headers={"X-Request-ID": "req-source-create"},
        )
        assert created.status_code == 201
        _assert_protected_headers(created, "req-source-create")
        source = created.json()
        assert source == {
            "id": source["id"],
            "projectId": str(project_id),
            "provider": "feishu",
            "name": "Engineering handbook",
            "documentId": "Doc123",
            "credentialRef": "engineering_feishu",
            "accessPolicy": "project_members",
            "status": "configured",
            "createdAt": source["createdAt"],
            "updatedAt": source["updatedAt"],
            "disabledAt": None,
            "syncIntervalSeconds": None,
            "nextSyncAt": None,
            "lastCheckedAt": None,
            "lastSuccessAt": None,
            "lastErrorCode": None,
            "accessState": "unverified",
        }

        listed = client.get(
            f"/api/v1/projects/{project_id}/knowledge/sources",
            headers={"X-Request-ID": "req-source-list"},
        )
        assert listed.status_code == 200
        _assert_protected_headers(listed, "req-source-list")
        assert listed.json() == {"items": [source], "nextCursor": None}

        detail = client.get(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source['id']}",
            headers={"X-Request-ID": "req-source-detail"},
        )
        assert detail.status_code == 200
        _assert_protected_headers(detail, "req-source-detail")
        assert detail.json() == source

        disabled = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source['id']}",
            headers={"X-Request-ID": "req-source-disable"},
        )
        assert disabled.status_code == 204
        _assert_protected_headers(disabled, "req-source-disable")
        assert disabled.content == b""
        repeated = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source['id']}"
        )
        assert repeated.status_code == 204

        after = client.get(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source['id']}"
        )
        assert after.status_code == 200
        assert after.json()["status"] == "disabled"
        assert after.json()["disabledAt"] is not None

        duplicate = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
            json=_payload(),
            headers={"X-Request-ID": "req-source-conflict"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json() == {
            "message": "知识来源已登记",
            "code": "source_conflict",
            "traceId": "req-source-conflict",
        }

    with database.session_factory() as session:
        stored = session.get(KnowledgeSource, source["id"])
        assert stored is not None and stored.status == "disabled"
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.resource_id == stored.id,
            )
        ) == 2
        events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == project_id,
                    OutboxEvent.event_type.in_(
                        ["knowledge.source_created", "knowledge.source_disabled"]
                    ),
                )
            )
        )
        assert [event.event_type for event in events] == [
            "knowledge.source_created",
            "knowledge.source_disabled",
        ]
        assert all(
            set(event.payload)
            == {"sourceId", "projectId", "provider", "status", "accessPolicy"}
            for event in events
        )


@pytest.mark.integration
@pytest.mark.parametrize("role", [MembershipRole.MEMBER, MembershipRole.VIEWER])
def test_feishu_sources_conceal_configuration_from_non_administrators(
    role: MembershipRole,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, role)
    project_id = seed_project(database, actor, permission="manage")
    source_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            KnowledgeSource(
                id=source_id,
                org_id=actor.organization_id,
                project_id=project_id,
                name="Existing source",
                external_id="ExistingDoc",
                credential_ref="existing_source",
                access_policy="project_members",
            )
        )
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        responses = [
            client.post(
                f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json=_payload()
            ),
            client.get(f"/api/v1/projects/{project_id}/knowledge/sources"),
            client.get(f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}"),
            client.delete(f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}"),
        ]

    assert all(response.status_code == 404 for response in responses)
    assert all(response.json()["code"] == "not_found" for response in responses)
    with database.session_factory() as session:
        source = session.get(KnowledgeSource, source_id)
        assert source is not None and source.status == "configured"


@pytest.mark.integration
def test_feishu_source_validation_and_csrf_fail_without_persisting(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        invalid = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
            json=_payload(token="private-token"),
            headers={"X-Request-ID": "req-source-validation"},
        )
        csrf = client.headers.pop("X-CSRF-Token")
        rejected = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
            json=_payload(),
            headers={"X-Request-ID": "req-source-csrf"},
        )
        client.headers["X-CSRF-Token"] = csrf

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
    assert "private-token" not in invalid.text
    _assert_protected_headers(invalid, "req-source-validation")
    assert invalid.json()["traceId"] == invalid.headers["x-request-id"]
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "csrf_failed"
    _assert_protected_headers(rejected, "req-source-csrf")
    assert rejected.json()["traceId"] == rejected.headers["x-request-id"]
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeSource)) == 0


@pytest.mark.integration
def test_disable_rejects_invalid_csrf_and_origin_without_side_effects(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        created = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json=_payload()
        )
        source_id = created.json()["id"]
        csrf = client.headers.pop("X-CSRF-Token")
        missing_csrf = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}",
            headers={"X-Request-ID": "req-source-delete-csrf"},
        )
        client.headers["X-CSRF-Token"] = csrf
        wrong_origin = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}",
            headers={
                "Origin": "https://evil.example",
                "X-Request-ID": "req-source-delete-origin",
            },
        )

    assert missing_csrf.status_code == 403
    _assert_protected_headers(missing_csrf, "req-source-delete-csrf")
    assert missing_csrf.json()["traceId"] == missing_csrf.headers["x-request-id"]
    assert wrong_origin.status_code == 403
    assert wrong_origin.headers["x-request-id"] == "req-source-delete-origin"
    assert wrong_origin.headers["cache-control"] == "private, no-store"
    assert "access-control-allow-origin" not in wrong_origin.headers
    assert wrong_origin.json()["traceId"] == wrong_origin.headers["x-request-id"]
    with database.session_factory() as session:
        source = session.get(KnowledgeSource, source_id)
        assert source is not None and source.status == "configured"
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.resource_id == source.id)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.aggregate_id == project_id,
                OutboxEvent.event_type.like("knowledge.source_%"),
            )
        ) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    ("suffix", "expected_allow"),
    [
        ("", "GET"),
        ("/feishu", "DELETE, GET, PATCH, POST"),
        (f"/{uuid4()}", "DELETE, GET, PATCH"),
    ],
)
def test_source_method_not_allowed_lists_all_framework_matched_methods(
    suffix: str,
    expected_allow: str,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.put(
            f"/api/v1/projects/{project_id}/knowledge/sources{suffix}",
            json={},
            headers={"X-Request-ID": "req-source-method"},
        )

    assert response.status_code == 405
    assert response.headers["allow"] == expected_allow
    _assert_protected_headers(response, "req-source-method")
    assert response.json()["traceId"] == response.headers["x-request-id"]
    assert response.json() == {
        "message": "请求方法不被允许",
        "code": "method_not_allowed",
        "traceId": "req-source-method",
    }


@pytest.mark.integration
def test_knowledge_source_database_enforces_tenant_and_status_constraints(
    database: Database,
) -> None:
    first = seed_actor(database, MembershipRole.OWNER)
    second = seed_actor(database, MembershipRole.OWNER)
    second_project_id = seed_project(database, second, permission=None)
    with pytest.raises(IntegrityError), database.session_factory.begin() as session:
        session.add(
            KnowledgeSource(
                org_id=first.organization_id,
                project_id=second_project_id,
                name="Cross tenant",
                external_id="DocCrossTenant",
                credential_ref="cross_tenant",
                access_policy="project_members",
            )
        )
        session.flush()

    first_project_id = seed_project(database, first, permission=None)
    with pytest.raises(IntegrityError), database.session_factory.begin() as session:
        session.add(
            KnowledgeSource(
                org_id=first.organization_id,
                project_id=first_project_id,
                name="Invalid status state",
                external_id="DocInvalidStatus",
                credential_ref="invalid_status",
                access_policy="project_members",
                status="disabled",
                disabled_at=None,
            )
        )
        session.flush()


@pytest.mark.integration
def test_feishu_source_list_paginates_and_rejects_invalid_cursor(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with database.session_factory.begin() as session:
        session.add_all(
            [
                KnowledgeSource(
                    org_id=actor.organization_id,
                    project_id=project_id,
                    name=f"Source {index}",
                    external_id=f"Doc{index}",
                    credential_ref="pagination_source",
                    access_policy="project_members",
                )
                for index in range(51)
            ]
        )
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        default_page = client.get(f"/api/v1/projects/{project_id}/knowledge/sources")
        assert default_page.status_code == 200
        assert len(default_page.json()["items"]) == 50
        assert default_page.json()["nextCursor"] is not None
        maximum_page = client.get(
            f"/api/v1/projects/{project_id}/knowledge/sources", params={"limit": 100}
        )
        assert maximum_page.status_code == 200
        assert len(maximum_page.json()["items"]) == 51
        first = client.get(
            f"/api/v1/projects/{project_id}/knowledge/sources", params={"limit": 1}
        )
        assert first.status_code == 200
        assert len(first.json()["items"]) == 1
        assert first.json()["nextCursor"] is not None
        second = client.get(
            f"/api/v1/projects/{project_id}/knowledge/sources",
            params={"limit": 1, "cursor": first.json()["nextCursor"]},
        )
        assert second.status_code == 200
        assert len(second.json()["items"]) == 1
        assert second.json()["items"][0]["id"] != first.json()["items"][0]["id"]
        invalid_limits = [
            client.get(
                f"/api/v1/projects/{project_id}/knowledge/sources",
                params={"limit": limit},
                headers={"X-Request-ID": f"req-source-limit-{limit}"},
            )
            for limit in (0, 101)
        ]
        invalid = client.get(
            f"/api/v1/projects/{project_id}/knowledge/sources",
            params={"cursor": "not-a-cursor"},
            headers={"X-Request-ID": "req-source-cursor"},
        )

    assert invalid.status_code == 422
    assert invalid.json() == {
        "message": "分页游标无效",
        "code": "invalid_cursor",
        "traceId": "req-source-cursor",
    }
    _assert_protected_headers(invalid, "req-source-cursor")
    for limit, response in zip((0, 101), invalid_limits, strict=True):
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert response.json()["traceId"] == response.headers["x-request-id"]
        _assert_protected_headers(response, f"req-source-limit-{limit}")


@pytest.mark.integration
def test_feishu_source_authorization_uses_current_membership_role(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        initial = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json=_payload()
        )
        assert initial.status_code == 201
        source_id = initial.json()["id"]
        with database.session_factory.begin() as session:
            membership = session.get(Membership, actor.membership_id)
            assert membership is not None
            membership.role = MembershipRole.MEMBER.value
        responses = [
            client.post(
                f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
                json=_payload(documentId="AnotherDoc"),
            ),
            client.get(f"/api/v1/projects/{project_id}/knowledge/sources"),
            client.get(f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}"),
            client.delete(f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}"),
        ]

    assert all(response.status_code == 404 for response in responses)
    with database.session_factory() as session:
        source = session.get(KnowledgeSource, source_id)
        assert source is not None and source.status == "configured"


@pytest.mark.integration
@pytest.mark.parametrize("operation", ["create", "disable"])
def test_feishu_source_mutation_rechecks_role_after_waiting_for_project_lock(
    operation: str,
    database: Database,
    migrated_engine: Engine,
    test_database_url: str,
) -> None:
    """Break caught: a blocked source mutation must not trust a stale administrator role."""
    owner = seed_actor(database, MembershipRole.OWNER)
    admin = seed_actor(database, MembershipRole.ADMIN, owner.organization_id)
    project_id = seed_project(database, admin, permission="manage")
    source_id = uuid4()
    if operation == "disable":
        with database.session_factory.begin() as session:
            session.add(
                KnowledgeSource(
                    id=source_id,
                    org_id=owner.organization_id,
                    project_id=project_id,
                    name="Source protected by fresh authorization",
                    external_id="ExistingDoc",
                    credential_ref="existing_source",
                    access_policy="project_members",
                )
            )

    gate = LockGate()

    class GatedAuthorizationPolicy(AuthorizationPolicy):
        def __init__(self, session: Session) -> None:
            super().__init__(session)
            self._gate_session = session
            gate.register(session, "waiter")

        def find_project(
            self,
            identity: IdentityContextResponse,
            project_id: UUID,
            required: ProjectPermission,
            *,
            for_update: bool = False,
        ) -> Project | None:
            if not for_update:
                return super().find_project(
                    identity,
                    project_id,
                    required,
                    for_update=for_update,
                )
            role = gate.before_locked_read(self._gate_session)
            project = super().find_project(
                identity,
                project_id,
                required,
                for_update=for_update,
            )
            gate.after_locked_read(role)
            return project

    def hold_project_lock() -> object:
        with database.session_factory.begin() as session:
            install_race_session_deadlines(session)
            gate.register(session, "holder")
            role = gate.before_locked_read(session)
            project = project_repository.get_project(
                session,
                org_id=owner.organization_id,
                project_id=project_id,
                for_update=True,
            )
            assert project is not None
            gate.after_locked_read(role)
        return None

    request_id = f"req-stale-source-{operation}"

    def mutate_source(client: TestClient) -> object:
        if operation == "create":
            return client.post(
                f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
                json=_payload(documentId="MustNotPersist"),
                headers={"X-Request-ID": request_id},
            )
        return client.delete(
            f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}",
            headers={"X-Request-ID": request_id},
        )

    executor = ThreadPoolExecutor(max_workers=2)
    futures: list[Future[object]] = []
    try:
        with (
            patch(
                "cairn_api.knowledge.source_service.AuthorizationPolicy",
                GatedAuthorizationPolicy,
            ),
            knowledge_client(
                knowledge_settings(test_database_url),
                database,
                admin,
                MemoryObjectStore(),
            ) as client,
        ):
            holder = executor.submit(hold_project_lock)
            futures.append(holder)
            wait_for_race_event(
                gate.holder_locked,
                futures,
                awaited_condition="the holder project lock",
            )
            mutation = executor.submit(mutate_source, client)
            futures.append(mutation)
            wait_for_race_event(
                gate.waiter_entered,
                futures,
                awaited_condition="the blocked source mutation",
            )
            assert_waiting_on_lock(migrated_engine, gate, futures)

            with database.session_factory.begin() as session:
                membership = session.get(Membership, admin.membership_id)
                assert membership is not None
                membership.role = MembershipRole.MEMBER.value

            gate.release_holder.set()
            holder.result(timeout=FUTURE_SECONDS)
            result = mutation.result(timeout=FUTURE_SECONDS)
    finally:
        shutdown_race_executor(
            executor,
            futures,
            cancel_signal=gate.release_holder,
            force_cancel=lambda: terminate_race_backends(migrated_engine, gate),
            primary_exception=sys.exception(),
        )

    assert isinstance(result, Response)
    assert result.status_code == 404
    assert result.json() == {
        "message": "资源不存在",
        "code": "not_found",
        "traceId": request_id,
    }
    _assert_protected_headers(result, request_id)
    with database.session_factory() as session:
        sources = list(
            session.scalars(
                select(KnowledgeSource).where(KnowledgeSource.project_id == project_id)
            )
        )
        assert len(sources) == (1 if operation == "disable" else 0)
        if operation == "disable":
            assert sources[0].status == "configured"
            assert sources[0].disabled_at is None
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action.in_(
                    ["knowledge.source_created", "knowledge.source_disabled"]
                )
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.aggregate_id == project_id,
                OutboxEvent.event_type.in_(
                    ["knowledge.source_created", "knowledge.source_disabled"]
                ),
            )
        ) == 0


@pytest.mark.integration
@pytest.mark.parametrize("failing_dependency", ["add_audit_log", "OutboxEvent"])
def test_feishu_source_audit_or_outbox_failure_rolls_back_everything(
    failing_dependency: str,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    with (
        patch(
            f"cairn_api.knowledge.source_service.{failing_dependency}",
            side_effect=RuntimeError("private change record failure"),
        ),
        knowledge_client(
            knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
        ) as client,
    ):
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
            json=_payload(),
            headers={"X-Request-ID": "req-source-audit-failure"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "private change record failure" not in response.text
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeSource)) == 0
        assert session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.event_type.like("knowledge.source_%")
            )
        ) == 0


@pytest.mark.integration
def test_feishu_source_disable_failure_rolls_back_status_audit_and_outbox(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        created = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json=_payload()
        )
        assert created.status_code == 201
        source_id = created.json()["id"]
        with patch(
            "cairn_api.knowledge.source_service.add_audit_log",
            side_effect=RuntimeError("private disable audit failure"),
        ):
            response = client.delete(
                f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}",
                headers={"X-Request-ID": "req-source-disable-rollback"},
            )

    assert response.status_code == 500
    assert "private disable audit failure" not in response.text
    with database.session_factory() as session:
        source = session.get(KnowledgeSource, source_id)
        assert source is not None
        assert source.status == "configured"
        assert source.disabled_at is None
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.resource_id == source.id)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.aggregate_id == project_id,
                OutboxEvent.event_type.like("knowledge.source_%"),
            )
        ) == 1


@pytest.mark.integration
def test_source_routes_return_session_invalid_after_session_revocation(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source_id = uuid4()
    requests = [
        ("POST", f"/api/v1/projects/{project_id}/knowledge/sources/feishu", _payload()),
        ("GET", f"/api/v1/projects/{project_id}/knowledge/sources", None),
        ("GET", f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}", None),
        ("DELETE", f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}", None),
    ]
    responses: list[Response] = []
    for index, (method, path, body) in enumerate(requests):
        with knowledge_client(
            knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
        ) as client:
            with database.session_factory.begin() as session:
                session.query(AuthSession).filter(AuthSession.user_id == actor.user_id).delete()
            responses.append(
                client.request(
                    method,
                    path,
                    json=body,
                    headers={"X-Request-ID": f"req-source-session-{index}"},
                )
            )

    for index, response in enumerate(responses):
        assert response.status_code == 401
        assert response.json()["code"] == "session_invalid"
        assert response.json()["traceId"] == f"req-source-session-{index}"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["access-control-allow-origin"] == "http://localhost:5500"


@pytest.mark.integration
def test_source_routes_conceal_cross_org_and_wrong_project_source_ids(
    database: Database,
    test_database_url: str,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    other = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, owner, permission=None)
    wrong_project_id = seed_project(database, owner, permission=None)
    settings = knowledge_settings(test_database_url)
    with knowledge_client(settings, database, owner, MemoryObjectStore()) as client:
        created = client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json=_payload()
        )
        assert created.status_code == 201
        source_id = created.json()["id"]
        wrong_detail = client.get(
            f"/api/v1/projects/{wrong_project_id}/knowledge/sources/{source_id}"
        )
        wrong_delete = client.delete(
            f"/api/v1/projects/{wrong_project_id}/knowledge/sources/{source_id}"
        )
    with knowledge_client(settings, database, other, MemoryObjectStore()) as client:
        cross_org = [
            client.post(
                f"/api/v1/projects/{project_id}/knowledge/sources/feishu", json=_payload()
            ),
            client.get(f"/api/v1/projects/{project_id}/knowledge/sources"),
            client.get(f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}"),
            client.delete(f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}"),
        ]

    for response in [wrong_detail, wrong_delete, *cross_org]:
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


@pytest.mark.integration
def test_unknown_source_in_authorized_project_returns_traced_not_found(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source_id = uuid4()
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        responses = [
            client.get(
                f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}",
                headers={"X-Request-ID": "req-source-unknown-get"},
            ),
            client.delete(
                f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}",
                headers={"X-Request-ID": "req-source-unknown-delete"},
            ),
        ]

    for method, response in zip(("get", "delete"), responses, strict=True):
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        _assert_protected_headers(response, f"req-source-unknown-{method}")
        assert response.json()["traceId"] == response.headers["x-request-id"]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        (OperationalError("SELECT private", {}, Exception("down")), 503, "database_unavailable"),
        (RuntimeError("private unexpected"), 500, "internal_error"),
    ],
)
def test_all_source_entrypoints_normalize_infrastructure_and_unexpected_failures(
    failure: Exception,
    expected_status: int,
    expected_code: str,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source_id = uuid4()
    cases = [
        (
            "create_feishu_source",
            "POST",
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
            _payload(),
        ),
        ("list_sources", "GET", f"/api/v1/projects/{project_id}/knowledge/sources", None),
        (
            "get_source",
            "GET",
            f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}",
            None,
        ),
        (
            "disable_source",
            "DELETE",
            f"/api/v1/projects/{project_id}/knowledge/sources/{source_id}",
            None,
        ),
    ]
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        responses: list[Response] = []
        for index, (method_name, method, path, body) in enumerate(cases):
            with patch(
                f"cairn_api.knowledge.source_service.KnowledgeSourceService.{method_name}",
                side_effect=failure,
            ):
                responses.append(
                    client.request(
                        method,
                        path,
                        json=body,
                        headers={"X-Request-ID": f"req-source-failure-{index}"},
                    )
                )

    for index, response in enumerate(responses):
        assert response.status_code == expected_status
        assert response.json()["code"] == expected_code
        assert response.json()["traceId"] == f"req-source-failure-{index}"
        assert response.json()["traceId"] == response.headers["x-request-id"]
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
        assert "private" not in response.text


@pytest.mark.integration
def test_feishu_source_database_failure_is_traced_and_sanitized(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    failure = OperationalError("SELECT private_secret", {}, Exception("database down"))
    with (
        patch(
            "cairn_api.knowledge.source_service.KnowledgeSourceService.list_sources",
            side_effect=failure,
        ),
        knowledge_client(
            knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
        ) as client,
    ):
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/sources",
            headers={"X-Request-ID": "req-source-database"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "message": "数据库暂时不可用",
        "code": "database_unavailable",
        "traceId": "req-source-database",
    }
    assert "private_secret" not in response.text


@pytest.mark.integration
def test_concurrent_duplicate_feishu_source_creation_returns_one_conflict(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    settings = knowledge_settings(test_database_url)
    barrier = threading.Barrier(2)

    def create_source(client: TestClient) -> int:
        barrier.wait(timeout=5)
        return client.post(
            f"/api/v1/projects/{project_id}/knowledge/sources/feishu",
            json=_payload(),
        ).status_code

    with ExitStack() as stack:
        clients = [
            stack.enter_context(
                knowledge_client(settings, database, actor, MemoryObjectStore())
            )
            for _index in range(2)
        ]
        for client in clients:
            assert client.get("/openapi.json").status_code == 200
            assert (
                client.get(f"/api/v1/projects/{project_id}/knowledge/sources").status_code
                == 200
            )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create_source, client) for client in clients]
            statuses = [future.result() for future in futures]

    assert sorted(statuses) == [201, 409]
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeSource)) == 1
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "knowledge.source_created"
            )
        ) == 1
