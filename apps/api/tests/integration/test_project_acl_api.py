from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.projects.models import OutboxEvent, Project
from cairn_api.settings import Settings
from sqlalchemy import func, select

from .authorization_helpers import APP_ORIGIN, authenticated_client, seed_actor


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
