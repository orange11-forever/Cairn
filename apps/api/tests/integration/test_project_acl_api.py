from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from time import monotonic, sleep
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization import repository
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.schemas import AclEntryResponse
from cairn_api.authorization.service import ProjectAclService
from cairn_api.authorization.types import ActorType, MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects.models import OutboxEvent, Project
from cairn_api.settings import Settings
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, SessionTransaction

from .authorization_helpers import APP_ORIGIN, SeededActor, authenticated_client, seed_actor

WAIT_SECONDS = 5.0
FUTURE_SECONDS = 10.0
POLL_SECONDS = 0.01
WorkerRole = Literal["holder", "waiter"]


@pytest.fixture()
def api_settings(test_database_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=test_database_url,
        app_url=APP_ORIGIN,
        cors_origins=[APP_ORIGIN],
        csrf_secret="test-only-csrf-secret-with-at-least-32-bytes",
        auth_rate_limit_secret="test-only-auth-rate-limit-secret-with-at-least-32-bytes",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


def _private_project(database: Database, org_id: UUID, *, name: str = "Private ACL") -> UUID:
    project_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(Project(id=project_id, org_id=org_id, name=name))
    return project_id


def _acl_change_counts(database: Database) -> tuple[int, int]:
    with database.session_factory() as session:
        audits = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action.like("project.acl_%"))
        )
        events = session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type.like("project.acl_%"))
        )
    return int(audits or 0), int(events or 0)


def _identity(actor: SeededActor) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(
            id=actor.user_id,
            email=actor.email,
            display_name=f"Test {actor.role.value}",
        ),
        organization=OrganizationResponse(
            id=actor.organization_id,
            slug=f"actor-{actor.organization_id}",
            name="Authorization test organization",
        ),
        membership=MembershipResponse(id=actor.membership_id, role=actor.role),
        csrf_token="not-used-by-service-test",
    )


def _audit(trace_id: str) -> RequestAuditContext:
    return RequestAuditContext(
        trace_id=trace_id,
        ip="198.51.100.26",
        user_agent="acl-race-test",
    )


def _assert_waiter_blocked_on_holder(
    engine: Engine,
    *,
    holder_pid: int,
    waiter_pid: int,
) -> None:
    deadline = monotonic() + WAIT_SECONDS
    with engine.connect() as connection:
        while monotonic() < deadline:
            blockers = cast(
                list[int],
                connection.scalar(
                    text("SELECT pg_blocking_pids(:waiter_pid)"),
                    {"waiter_pid": waiter_pid},
                ),
            )
            if holder_pid in blockers:
                return
            sleep(POLL_SECONDS)
    raise AssertionError(
        "waiter did not block on the holder's tenant-scoped project lock: "
        f"holder_pid={holder_pid}, waiter_pid={waiter_pid}"
    )


@pytest.mark.integration
def test_revoked_manager_waiting_on_project_lock_cannot_restore_own_manage_acl(
    database: Database,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a stale pre-lock ACL predicate permits self-regrant after revocation."""
    owner = seed_actor(database, MembershipRole.OWNER)
    member = seed_actor(database, MembershipRole.MEMBER, owner.organization_id)
    owner_identity = _identity(owner)
    member_identity = _identity(member)
    project_id = _private_project(database, owner.organization_id, name="ACL lock race")
    with database.session_factory.begin() as session:
        session.add(
            ResourceAclEntry(
                org_id=owner.organization_id,
                resource_type="project",
                resource_id=project_id,
                principal_type="user",
                principal_id=str(member.user_id),
                permission="manage",
                granted_by_type="system",
            )
        )

    holder_revoked = Event()
    waiter_transaction_started = Event()
    release_holder = Event()
    pids: dict[WorkerRole, int] = {}
    pid_guard = Lock()
    real_revoke_entry = repository.revoke_entry

    def gated_revoke_entry(
        session: Session,
        *,
        entry: ResourceAclEntry,
        actor_type: ActorType,
        actor_id: UUID | None,
    ) -> None:
        real_revoke_entry(
            session,
            entry=entry,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        if entry.principal_type == "user" and entry.principal_id == str(member.user_id):
            holder_revoked.set()
            if not release_holder.wait(WAIT_SECONDS):
                raise AssertionError("owner revocation holder was not released")

    monkeypatch.setattr(repository, "revoke_entry", gated_revoke_entry)

    def install_pid_capture(session: Session, role: WorkerRole) -> None:
        def capture_pid(
            _session: Session,
            _transaction: SessionTransaction,
            connection: Connection,
        ) -> None:
            pid = connection.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            connection.execute(
                text(
                    "SELECT set_config('lock_timeout', '6000ms', true), "
                    "set_config('statement_timeout', '8000ms', true)"
                )
            ).one()
            with pid_guard:
                pids[role] = pid
            if role == "waiter":
                waiter_transaction_started.set()

        event.listen(session, "after_begin", capture_pid)

    def revoke_member_manage() -> None:
        with database.session_factory() as session:
            install_pid_capture(session, "holder")
            ProjectAclService(session).revoke_acl(
                identity=owner_identity,
                project_id=project_id,
                principal_type="user",
                principal_id=str(member.user_id),
                audit=_audit("req-acl-race-revoked"),
            )

    def restore_own_manage() -> AclEntryResponse | ApiProblem:
        with database.session_factory() as session:
            install_pid_capture(session, "waiter")
            try:
                return ProjectAclService(
                    session,
                    policy=AuthorizationPolicy(session),
                ).set_acl(
                    identity=member_identity,
                    project_id=project_id,
                    principal_type="user",
                    principal_id=str(member.user_id),
                    permission=ProjectPermission.MANAGE,
                    audit=_audit("req-acl-race-self-regrant"),
                )
            except ApiProblem as problem:
                return problem

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            holder = executor.submit(revoke_member_manage)
            assert holder_revoked.wait(WAIT_SECONDS)
            waiter = executor.submit(restore_own_manage)
            assert waiter_transaction_started.wait(WAIT_SECONDS)
            with pid_guard:
                holder_pid = pids["holder"]
                waiter_pid = pids["waiter"]
            _assert_waiter_blocked_on_holder(
                migrated_engine,
                holder_pid=holder_pid,
                waiter_pid=waiter_pid,
            )
            release_holder.set()
            holder_result = holder.result(timeout=FUTURE_SECONDS)
            waiter_result = waiter.result(timeout=FUTURE_SECONDS)
        finally:
            release_holder.set()

    assert holder_result is None
    assert isinstance(waiter_result, ApiProblem)
    assert (waiter_result.status_code, waiter_result.code, waiter_result.message) == (
        404,
        "not_found",
        "资源不存在",
    )
    with database.session_factory() as session:
        history = session.scalars(
            select(ResourceAclEntry).where(
                ResourceAclEntry.resource_id == project_id,
                ResourceAclEntry.principal_type == "user",
                ResourceAclEntry.principal_id == str(member.user_id),
            )
        ).all()
        audits = session.scalars(
            select(AuditLog).where(AuditLog.resource_id == project_id)
        ).all()
        events = session.scalars(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == project_id)
        ).all()

    assert len(history) == 1
    assert history[0].revoked_at is not None
    assert [audit.trace_id for audit in audits] == ["req-acl-race-revoked"]
    assert [audit.action for audit in audits] == ["project.acl_revoked"]
    assert [event.event_type for event in events] == ["project.acl_revoked"]


@pytest.mark.integration
@pytest.mark.parametrize("role", [MembershipRole.OWNER, MembershipRole.ADMIN])
def test_privileged_roles_can_list_set_and_revoke_project_acl(
    role: MembershipRole,
    database: Database,
    api_settings: Settings,
) -> None:
    actor = seed_actor(database, role)
    project_id = _private_project(database, actor.organization_id)
    path = f"/api/v1/projects/{project_id}/acl/role/member"

    with authenticated_client(api_settings, database, actor) as client:
        granted = client.put(path, json={"permission": "write"})
        listed = client.get(f"/api/v1/projects/{project_id}/acl")
        revoked = client.delete(path)

    assert granted.status_code == listed.status_code == 200
    assert granted.json()["principalType"] == "role"
    assert granted.json()["principalId"] == "member"
    assert [item["id"] for item in listed.json()["items"]] == [granted.json()["id"]]
    assert revoked.status_code == 204


@pytest.mark.integration
def test_member_with_manage_acl_can_manage_project_acl(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    member = seed_actor(database, MembershipRole.MEMBER, owner.organization_id)
    project_id = _private_project(database, owner.organization_id)
    with database.session_factory.begin() as session:
        session.add(
            ResourceAclEntry(
                org_id=owner.organization_id,
                resource_type="project",
                resource_id=project_id,
                principal_type="user",
                principal_id=str(member.user_id),
                permission="manage",
                granted_by_type="system",
            )
        )
    path = f"/api/v1/projects/{project_id}/acl/role/admin"

    with authenticated_client(api_settings, database, member) as client:
        assert client.get(f"/api/v1/projects/{project_id}/acl").status_code == 200
        granted = client.put(path, json={"permission": "read"})
        revoked = client.delete(path)

    assert granted.status_code == 200
    assert revoked.status_code == 204


@pytest.mark.integration
@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (MembershipRole.MEMBER, "read"),
        (MembershipRole.MEMBER, "write"),
        (MembershipRole.VIEWER, "manage"),
    ],
)
def test_non_managers_receive_same_not_found_as_absent_project(
    role: MembershipRole,
    permission: str,
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    actor = seed_actor(database, role, owner.organization_id)
    project_id = _private_project(database, owner.organization_id)
    with database.session_factory.begin() as session:
        session.add(
            ResourceAclEntry(
                org_id=owner.organization_id,
                resource_type="project",
                resource_id=project_id,
                principal_type="user",
                principal_id=str(actor.user_id),
                permission=permission,
                granted_by_type="system",
            )
        )

    with authenticated_client(api_settings, database, actor) as client:
        existing = client.get(f"/api/v1/projects/{project_id}/acl")
        absent = client.get(f"/api/v1/projects/{uuid4()}/acl")
        put = client.put(
            f"/api/v1/projects/{project_id}/acl/role/member",
            json={"permission": "read"},
        )
        delete = client.delete(f"/api/v1/projects/{project_id}/acl/role/member")

    for response in (existing, absent, put, delete):
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        assert response.json()["message"] == "资源不存在"


@pytest.mark.integration
def test_duplicate_put_returns_same_entry_without_duplicate_side_effects(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = _private_project(database, owner.organization_id)
    path = f"/api/v1/projects/{project_id}/acl/role/member"

    with authenticated_client(api_settings, database, owner) as client:
        first = client.put(path, json={"permission": "write"})
        counts_after_first = _acl_change_counts(database)
        second = client.put(path, json={"permission": "write"})
        counts_after_second = _acl_change_counts(database)

    assert first.status_code == second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert counts_after_first == counts_after_second == (1, 1)


@pytest.mark.integration
def test_replacing_permission_keeps_one_active_row_and_revoked_history(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = _private_project(database, owner.organization_id)
    path = f"/api/v1/projects/{project_id}/acl/role/member"

    with authenticated_client(api_settings, database, owner) as client:
        first = client.put(path, json={"permission": "read"})
        second = client.put(path, json={"permission": "write"})

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    with database.session_factory() as session:
        history = list(
            session.scalars(
                select(ResourceAclEntry)
                .where(
                    ResourceAclEntry.resource_id == project_id,
                    ResourceAclEntry.principal_type == "role",
                    ResourceAclEntry.principal_id == "member",
                )
                .order_by(ResourceAclEntry.granted_at, ResourceAclEntry.id)
            ).all()
        )
        actions = list(
            session.scalars(
                select(AuditLog.action)
                .where(AuditLog.resource_id == project_id)
                .order_by(AuditLog.created_at, AuditLog.id)
            ).all()
        )

    assert len(history) == 2
    assert [(entry.permission, entry.revoked_at is None) for entry in history] == [
        ("read", False),
        ("write", True),
    ]
    assert actions == ["project.acl_granted", "project.acl_granted"]


@pytest.mark.integration
def test_duplicate_delete_is_successful_without_duplicate_side_effects(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = _private_project(database, owner.organization_id)
    path = f"/api/v1/projects/{project_id}/acl/role/member"

    with authenticated_client(api_settings, database, owner) as client:
        granted = client.put(path, json={"permission": "manage"})
        first = client.delete(path)
        counts_after_first = _acl_change_counts(database)
        second = client.delete(path)
        counts_after_second = _acl_change_counts(database)

    assert granted.status_code == 200
    assert first.status_code == second.status_code == 204
    assert counts_after_first == counts_after_second == (2, 2)
    with database.session_factory() as session:
        revoke_audits = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "project.acl_revoked")
        )
        revoke_events = session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type == "project.acl_revoked")
        )
    assert (revoke_audits, revoke_events) == (1, 1)


@pytest.mark.integration
def test_invalid_principals_share_one_contract_and_do_not_write(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    outside = seed_actor(database, MembershipRole.MEMBER)
    project_id = _private_project(database, owner.organization_id)
    candidates = [
        ("user", str(outside.user_id)),
        ("user", str(uuid4())),
        ("user", "not-a-uuid"),
        ("group", "engineering"),
        ("unknown", "value"),
    ]

    with authenticated_client(api_settings, database, owner) as client:
        responses = [
            client.put(
                f"/api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}",
                json={"permission": "read"},
            )
            for principal_type, principal_id in candidates
        ]

    assert {
        (response.status_code, response.json()["code"], response.json()["message"])
        for response in responses
    } == {(422, "invalid_principal", "授权主体无效")}
    assert _acl_change_counts(database) == (0, 0)
    with database.session_factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(ResourceAclEntry)
            .where(ResourceAclEntry.resource_id == project_id)
        ) == 0


@pytest.mark.integration
def test_acl_page_uses_granted_at_and_id_cursor_and_rejects_malformed_cursor(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = _private_project(database, owner.organization_id)
    base = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
    entry_ids = [uuid4(), uuid4(), uuid4()]
    entry_ids.sort()
    with database.session_factory.begin() as session:
        session.add_all(
            [
                ResourceAclEntry(
                    id=entry_id,
                    org_id=owner.organization_id,
                    resource_type="project",
                    resource_id=project_id,
                    principal_type="role",
                    principal_id=principal_id,
                    permission="read",
                    granted_by_type="system",
                    granted_at=granted_at,
                )
                for entry_id, principal_id, granted_at in zip(
                    entry_ids,
                    ("owner", "admin", "member"),
                    (base, base, base + timedelta(seconds=1)),
                    strict=True,
                )
            ]
        )

    with authenticated_client(api_settings, database, owner) as client:
        first = client.get(
            f"/api/v1/projects/{project_id}/acl",
            params={"limit": 2},
        )
        assert first.status_code == 200
        second = client.get(
            f"/api/v1/projects/{project_id}/acl",
            params={"limit": 2, "cursor": first.json()["nextCursor"]},
        )
        malformed = client.get(
            f"/api/v1/projects/{project_id}/acl",
            params={"cursor": "not-a-cursor"},
        )

    assert [item["id"] for item in first.json()["items"]] == [
        str(entry_ids[0]),
        str(entry_ids[1]),
    ]
    assert first.json()["nextCursor"] is not None
    assert [item["id"] for item in second.json()["items"]] == [str(entry_ids[2])]
    assert second.json()["nextCursor"] is None
    assert (malformed.status_code, malformed.json()["code"]) == (422, "invalid_cursor")


@pytest.mark.integration
def test_acl_mutations_require_origin_and_session_csrf_before_writing(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = _private_project(database, owner.organization_id)
    path = f"/api/v1/projects/{project_id}/acl/role/member"

    with authenticated_client(api_settings, database, owner) as client:
        valid_csrf = client.headers.pop("X-CSRF-Token")
        missing_put = client.put(path, json={"permission": "read"})
        missing_delete = client.delete(path)
        client.headers["X-CSRF-Token"] = "wrong-token"
        wrong_put = client.put(path, json={"permission": "read"})
        wrong_delete = client.delete(path)
        client.headers["X-CSRF-Token"] = valid_csrf
        client.headers["Origin"] = "http://wrong-origin.example"
        wrong_origin_put = client.put(path, json={"permission": "read"})

    for response in (
        missing_put,
        missing_delete,
        wrong_put,
        wrong_delete,
        wrong_origin_put,
    ):
        assert response.status_code == 403
        assert response.json()["code"] == "csrf_failed"
    assert _acl_change_counts(database) == (0, 0)
    with database.session_factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(ResourceAclEntry)
            .where(ResourceAclEntry.resource_id == project_id)
        ) == 0
