from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.projects.models import Project
from cairn_api.settings import Settings
from sqlalchemy import select

from .authorization_helpers import (
    APP_ORIGIN,
    authenticated_client,
    load_active_acl_entries,
    seed_actor,
)


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


@pytest.mark.integration
@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_non_viewer_roles_can_create_projects(
    role: str, database: Database, api_settings: Settings
) -> None:
    actor = seed_actor(database, MembershipRole(role))
    with authenticated_client(api_settings, database, actor) as client:
        response = client.post("/api/v1/projects", json={"name": role})
        assert response.status_code == 201


@pytest.mark.integration
def test_viewer_project_creation_is_forbidden(
    database: Database, api_settings: Settings
) -> None:
    actor = seed_actor(database, MembershipRole.VIEWER)
    with authenticated_client(api_settings, database, actor) as client:
        response = client.post(
            "/api/v1/projects",
            headers={"X-Request-ID": "req-viewer-create"},
            json={"name": "Forbidden"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"
        assert response.json()["traceId"] == "req-viewer-create"


@pytest.mark.integration
def test_project_creation_persists_default_org_read_and_creator_manage(
    database: Database, api_settings: Settings
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    with authenticated_client(api_settings, database, actor) as client:
        response = client.post("/api/v1/projects", json={"name": "Defaults"})
    assert response.status_code == 201
    project_id = UUID(response.json()["id"])
    entries = load_active_acl_entries(database, project_id)
    assert {
        (entry.principal_type, entry.principal_id, entry.permission) for entry in entries
    } == {
        ("org", str(actor.organization_id), "read"),
        ("user", str(actor.user_id), "manage"),
    }


@pytest.mark.integration
def test_default_org_reader_can_read_but_all_mutations_are_concealed_and_revocation_hides_detail(
    database: Database, api_settings: Settings
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    member = seed_actor(database, MembershipRole.MEMBER, owner.organization_id)
    with authenticated_client(api_settings, database, owner) as client:
        project_response = client.post("/api/v1/projects", json={"name": "Shared read"})
        assert project_response.status_code == 201
        project_id = UUID(project_response.json()["id"])
        first_task = client.post(
            f"/api/v1/projects/{project_id}/tasks", json={"title": "First"}
        )
        second_task = client.post(
            f"/api/v1/projects/{project_id}/tasks", json={"title": "Second"}
        )
        assert first_task.status_code == second_task.status_code == 201

    with authenticated_client(api_settings, database, member) as client:
        page = client.get("/api/v1/projects")
        detail = client.get(f"/api/v1/projects/{project_id}")
        tasks = client.get(f"/api/v1/projects/{project_id}/tasks")
        create = client.post(
            f"/api/v1/projects/{project_id}/tasks", json={"title": "Forbidden"}
        )
        transition = client.patch(
            f"/api/v1/tasks/{first_task.json()['id']}/status", json={"status": "todo"}
        )
        dependency = client.post(
            f"/api/v1/tasks/{second_task.json()['id']}/dependencies",
            json={"predecessorTaskId": first_task.json()["id"]},
        )
        assert page.status_code == detail.status_code == tasks.status_code == 200
        assert [item["id"] for item in page.json()["items"]] == [str(project_id)]
        assert create.status_code == transition.status_code == dependency.status_code == 404
        assert {create.json()["code"], transition.json()["code"], dependency.json()["code"]} == {
            "not_found"
        }

    with database.session_factory.begin() as session:
        org_grant = session.scalars(
            select(ResourceAclEntry).where(
                ResourceAclEntry.resource_id == project_id,
                ResourceAclEntry.principal_type == "org",
                ResourceAclEntry.revoked_at.is_(None),
            )
        ).one()
        org_grant.revoked_at = datetime.now(UTC)
        org_grant.revoked_by_type = "system"

    with authenticated_client(api_settings, database, member) as client:
        hidden = client.get(f"/api/v1/projects/{project_id}")
        assert hidden.status_code == 404
        assert hidden.json()["code"] == "not_found"


@pytest.mark.integration
def test_self_dependency_on_inaccessible_successor_is_concealed(
    database: Database,
    api_settings: Settings,
) -> None:
    """Break caught: self-link validation reveals an inaccessible successor task."""
    owner = seed_actor(database, MembershipRole.OWNER)
    member = seed_actor(database, MembershipRole.MEMBER, owner.organization_id)
    with authenticated_client(api_settings, database, owner) as client:
        project = client.post("/api/v1/projects", json={"name": "Self link conceal"})
        assert project.status_code == 201
        task = client.post(
            f"/api/v1/projects/{project.json()['id']}/tasks",
            json={"title": "Private mutation"},
        )
        assert task.status_code == 201

    task_id = task.json()["id"]
    with authenticated_client(api_settings, database, member) as client:
        response = client.post(
            f"/api/v1/tasks/{task_id}/dependencies",
            headers={"X-Request-ID": "req-self-link-concealed"},
            json={"predecessorTaskId": task_id},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert response.json()["traceId"] == "req-self-link-concealed"


@pytest.mark.integration
def test_viewer_manage_acl_is_capped_at_read(
    database: Database, api_settings: Settings
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    viewer = seed_actor(database, MembershipRole.VIEWER, owner.organization_id)
    project_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(Project(id=project_id, org_id=owner.organization_id, name="Viewer managed"))
        session.add(
            ResourceAclEntry(
                org_id=owner.organization_id,
                resource_type="project",
                resource_id=project_id,
                principal_type="user",
                principal_id=str(viewer.user_id),
                permission="manage",
                granted_by_type="system",
            )
        )
    with authenticated_client(api_settings, database, viewer) as client:
        assert client.get(f"/api/v1/projects/{project_id}").status_code == 200
        response = client.post(
            f"/api/v1/projects/{project_id}/tasks", json={"title": "Forbidden"}
        )
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


@pytest.mark.integration
@pytest.mark.parametrize("role", [MembershipRole.OWNER, MembershipRole.ADMIN])
def test_privileged_roles_manage_private_projects_without_acl_rows(
    role: MembershipRole, database: Database, api_settings: Settings
) -> None:
    actor = seed_actor(database, role)
    project_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(Project(id=project_id, org_id=actor.organization_id, name="Private"))
    with authenticated_client(api_settings, database, actor) as client:
        assert client.get(f"/api/v1/projects/{project_id}").status_code == 200
        created = client.post(
            f"/api/v1/projects/{project_id}/tasks", json={"title": "Allowed"}
        )
        assert created.status_code == 201


@pytest.mark.integration
def test_project_acl_filter_is_applied_before_cursor_limit(
    database: Database, api_settings: Settings
) -> None:
    member = seed_actor(database, MembershipRole.MEMBER)
    base = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
    project_ids = [uuid4(), uuid4(), uuid4()]
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Project(
                    id=project_id,
                    org_id=member.organization_id,
                    name=name,
                    created_at=base + timedelta(seconds=index),
                    updated_at=base + timedelta(seconds=index),
                )
                for index, (project_id, name) in enumerate(
                    zip(project_ids, ("Visible A", "Hidden B", "Visible C"), strict=True)
                )
            ]
        )
        session.add_all(
            [
                ResourceAclEntry(
                    org_id=member.organization_id,
                    resource_type="project",
                    resource_id=project_id,
                    principal_type="user",
                    principal_id=str(member.user_id),
                    permission="read",
                    granted_by_type="system",
                )
                for project_id in (project_ids[0], project_ids[2])
            ]
        )
    with authenticated_client(api_settings, database, member) as client:
        response = client.get("/api/v1/projects", params={"limit": 2})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        str(project_ids[0]),
        str(project_ids[2]),
    ]
    assert response.json()["nextCursor"] is None
