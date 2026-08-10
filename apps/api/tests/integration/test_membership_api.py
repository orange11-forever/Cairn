from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.organizations.models import Membership
from cairn_api.projects.models import OutboxEvent
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


def _role_change_counts(database: Database) -> tuple[int, int]:
    with database.session_factory() as session:
        audits = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "membership.role_changed")
        )
        events = session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type == "membership.role_changed")
        )
    return int(audits or 0), int(events or 0)


@pytest.mark.integration
def test_owner_and_admin_page_member_details_in_stable_creation_order(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    admin = seed_actor(database, MembershipRole.ADMIN, owner.organization_id)
    member = seed_actor(database, MembershipRole.MEMBER, owner.organization_id)
    viewer = seed_actor(database, MembershipRole.VIEWER, owner.organization_id)
    actors = [owner, admin, member, viewer]
    base = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
    with database.session_factory.begin() as session:
        for index, actor in enumerate(actors):
            membership = session.get(Membership, actor.membership_id)
            assert membership is not None
            membership.created_at = base + timedelta(seconds=index)

    path = f"/api/v1/organizations/{owner.organization_id}/memberships"
    with authenticated_client(api_settings, database, owner) as client:
        first = client.get(path, params={"limit": 2})
        assert first.status_code == 200
        second = client.get(path, params={"limit": 2, "cursor": first.json()["nextCursor"]})

    assert second.status_code == 200
    items = first.json()["items"] + second.json()["items"]
    assert [item["id"] for item in items] == [str(actor.membership_id) for actor in actors]
    assert [item["userId"] for item in items] == [str(actor.user_id) for actor in actors]
    assert [item["email"] for item in items] == [actor.email for actor in actors]
    assert [item["displayName"] for item in items] == [
        "Test owner",
        "Test admin",
        "Test member",
        "Test viewer",
    ]
    assert [item["role"] for item in items] == ["owner", "admin", "member", "viewer"]
    assert all(datetime.fromisoformat(item["createdAt"]).tzinfo is not None for item in items)
    assert second.json()["nextCursor"] is None

    with authenticated_client(api_settings, database, admin) as client:
        admin_page = client.get(path)
    assert admin_page.status_code == 200
    assert [item["id"] for item in admin_page.json()["items"]] == [
        str(actor.membership_id) for actor in actors
    ]


@pytest.mark.integration
@pytest.mark.parametrize("role", [MembershipRole.MEMBER, MembershipRole.VIEWER])
def test_known_organization_membership_list_forbids_non_managers(
    role: MembershipRole,
    database: Database,
    api_settings: Settings,
) -> None:
    actor = seed_actor(database, role)
    with authenticated_client(api_settings, database, actor) as client:
        response = client.get(
            f"/api/v1/organizations/{actor.organization_id}/memberships",
            headers={"X-Request-ID": f"req-list-{role.value}"},
        )

    assert response.status_code == 403
    assert response.json() == {
        "message": "没有执行该操作的权限",
        "code": "forbidden",
        "traceId": f"req-list-{role.value}",
    }


@pytest.mark.integration
def test_membership_list_rejects_invalid_cursor(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    with authenticated_client(api_settings, database, owner) as client:
        response = client.get(
            f"/api/v1/organizations/{owner.organization_id}/memberships",
            params={"cursor": "not-a-cursor"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_cursor"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (MembershipRole.OWNER, MembershipRole.ADMIN),
        (MembershipRole.ADMIN, MembershipRole.VIEWER),
        (MembershipRole.MEMBER, MembershipRole.OWNER),
        (MembershipRole.VIEWER, MembershipRole.MEMBER),
    ],
)
def test_owner_can_promote_and_demote_every_membership_role(
    current: MembershipRole,
    requested: MembershipRole,
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    target = seed_actor(database, current, owner.organization_id)
    path = (
        f"/api/v1/organizations/{owner.organization_id}/memberships/"
        f"{target.membership_id}"
    )

    with authenticated_client(api_settings, database, owner) as client:
        response = client.patch(path, json={"role": requested.value})

    assert response.status_code == 200
    assert response.json()["role"] == requested.value
    with database.session_factory() as session:
        persisted = session.get(Membership, target.membership_id)
        assert persisted is not None
        assert persisted.role == requested.value


@pytest.mark.integration
@pytest.mark.parametrize(
    ("current", "requested", "allowed"),
    [
        (MembershipRole.MEMBER, MembershipRole.VIEWER, True),
        (MembershipRole.VIEWER, MembershipRole.MEMBER, True),
        (MembershipRole.MEMBER, MembershipRole.ADMIN, False),
        (MembershipRole.ADMIN, MembershipRole.MEMBER, False),
        (MembershipRole.OWNER, MembershipRole.VIEWER, False),
    ],
)
def test_admin_can_only_switch_member_and_viewer(
    current: MembershipRole,
    requested: MembershipRole,
    allowed: bool,
    database: Database,
    api_settings: Settings,
) -> None:
    admin = seed_actor(database, MembershipRole.ADMIN)
    target = seed_actor(database, current, admin.organization_id)
    path = (
        f"/api/v1/organizations/{admin.organization_id}/memberships/"
        f"{target.membership_id}"
    )

    with authenticated_client(api_settings, database, admin) as client:
        response = client.patch(path, json={"role": requested.value})

    if allowed:
        assert response.status_code == 200
        assert response.json()["role"] == requested.value
    else:
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"


@pytest.mark.integration
def test_last_owner_demotion_is_rejected_without_side_effects(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    counts_before = _role_change_counts(database)
    path = (
        f"/api/v1/organizations/{owner.organization_id}/memberships/"
        f"{owner.membership_id}"
    )

    with authenticated_client(api_settings, database, owner) as client:
        response = client.patch(path, json={"role": "admin"})

    assert response.status_code == 409
    assert response.json()["code"] == "last_owner_required"
    assert _role_change_counts(database) == counts_before == (0, 0)


@pytest.mark.integration
def test_cross_organization_membership_id_is_concealed(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    outsider = seed_actor(database, MembershipRole.MEMBER)
    path = (
        f"/api/v1/organizations/{owner.organization_id}/memberships/"
        f"{outsider.membership_id}"
    )

    with authenticated_client(api_settings, database, owner) as client:
        response = client.patch(path, json={"role": "viewer"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.integration
def test_membership_role_patch_requires_session_csrf_and_origin(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    target = seed_actor(database, MembershipRole.VIEWER, owner.organization_id)
    path = (
        f"/api/v1/organizations/{owner.organization_id}/memberships/"
        f"{target.membership_id}"
    )

    with authenticated_client(api_settings, database, owner) as client:
        del client.headers["X-CSRF-Token"]
        missing = client.patch(
            path,
            headers={"X-Request-ID": "req-membership-csrf"},
            json={"role": "member"},
        )

    assert missing.status_code == 403
    assert missing.json() == {
        "message": "请求来源或 CSRF 令牌无效",
        "code": "csrf_failed",
        "traceId": "req-membership-csrf",
    }


@pytest.mark.integration
def test_role_change_is_visible_to_existing_session_and_records_exact_event(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    target = seed_actor(database, MembershipRole.VIEWER, owner.organization_id)
    path = (
        f"/api/v1/organizations/{owner.organization_id}/memberships/"
        f"{target.membership_id}"
    )

    with (
        authenticated_client(api_settings, database, owner) as owner_client,
        authenticated_client(api_settings, database, target) as target_client,
    ):
        changed = owner_client.patch(path, json={"role": "member"})
        restored = target_client.get("/api/v1/session")

    assert changed.status_code == restored.status_code == 200
    assert restored.json()["membership"]["role"] == "member"
    with database.session_factory() as session:
        audit = session.scalars(
            select(AuditLog).where(AuditLog.action == "membership.role_changed")
        ).one()
        event = session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "membership.role_changed")
        ).one()
    expected_change = {
        "organizationId": str(owner.organization_id),
        "membershipId": str(target.membership_id),
        "oldRole": "viewer",
        "newRole": "member",
    }
    assert audit.resource_type == "membership"
    assert audit.resource_id == target.membership_id
    assert audit.details == expected_change
    assert event.aggregate_type == "organization"
    assert event.aggregate_id == owner.organization_id
    assert event.payload == expected_change


@pytest.mark.integration
def test_role_acl_permission_changes_immediately_with_membership_role(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    target = seed_actor(database, MembershipRole.VIEWER, owner.organization_id)
    membership_path = (
        f"/api/v1/organizations/{owner.organization_id}/memberships/"
        f"{target.membership_id}"
    )

    with authenticated_client(api_settings, database, owner) as owner_client:
        project = owner_client.post("/api/v1/projects", json={"name": "Role ACL refresh"})
        assert project.status_code == 201
        project_id = project.json()["id"]
        task = owner_client.post(
            f"/api/v1/projects/{project_id}/tasks",
            json={"title": "Refresh membership permission"},
        )
        assert task.status_code == 201
        task_id = task.json()["id"]
        grant = owner_client.put(
            f"/api/v1/projects/{project_id}/acl/role/member",
            json={"permission": "write"},
        )
        assert grant.status_code == 200

        with authenticated_client(api_settings, database, target) as target_client:
            promoted = owner_client.patch(membership_path, json={"role": "member"})
            member_session = target_client.get("/api/v1/session")
            allowed = target_client.patch(
                f"/api/v1/tasks/{task_id}/status",
                json={"status": "todo"},
            )
            demoted = owner_client.patch(membership_path, json={"role": "viewer"})
            viewer_session = target_client.get("/api/v1/session")
            concealed = target_client.patch(
                f"/api/v1/tasks/{task_id}/status",
                json={"status": "in_progress"},
            )

    assert promoted.status_code == demoted.status_code == 200
    assert member_session.json()["membership"]["role"] == "member"
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "todo"
    assert viewer_session.json()["membership"]["role"] == "viewer"
    assert concealed.status_code == 404
    assert concealed.json()["code"] == "not_found"


@pytest.mark.integration
def test_authorized_noop_patch_preserves_audit_and_outbox_counts(
    database: Database,
    api_settings: Settings,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    target = seed_actor(database, MembershipRole.VIEWER, owner.organization_id)
    path = (
        f"/api/v1/organizations/{owner.organization_id}/memberships/"
        f"{target.membership_id}"
    )
    counts_before = _role_change_counts(database)

    with authenticated_client(api_settings, database, owner) as client:
        response = client.patch(path, json={"role": "viewer"})

    assert response.status_code == 200
    assert response.json()["role"] == "viewer"
    assert _role_change_counts(database) == counts_before == (0, 0)


@pytest.mark.integration
def test_membership_management_openapi_exposes_only_list_and_role_patch() -> None:
    from cairn_api.app import create_app

    schema = create_app().openapi()
    collection = schema["paths"][
        "/api/v1/organizations/{organization_id}/memberships"
    ]
    item = schema["paths"][
        "/api/v1/organizations/{organization_id}/memberships/{membership_id}"
    ]

    assert set(collection) == {"get"}
    assert set(item) == {"patch"}
    assert "post" not in collection
    assert "delete" not in item
    csrf = next(
        parameter
        for parameter in item["patch"]["parameters"]
        if parameter["name"] == "X-CSRF-Token"
    )
    assert csrf["required"] is True
    request_schema = schema["components"]["schemas"]["MembershipRoleUpdateRequest"]
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["properties"]) == {"role"}
