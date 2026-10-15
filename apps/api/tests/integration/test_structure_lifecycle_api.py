"""Archive/restore preserves project structure and all transactional boundaries."""

from typing import Any
from uuid import UUID

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.db.session import Database
from cairn_api.projects.models import OutboxEvent
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from .test_project_structure_api import revision
from .test_projects_api import _create_project, _create_task, api_settings, client
from .test_task_editing_api import assert_error

# pyright: reportPrivateUsage=false

__all__ = ["api_settings", "client"]
pytestmark = pytest.mark.integration


def counts(database: Database) -> tuple[int, int]:
    with database.session_factory() as session:
        return (
            int(
                session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.resource_type.in_(("project", "task", "stage", "milestone")))
                )
                or 0
            ),
            int(session.scalar(select(func.count()).select_from(OutboxEvent)) or 0),
        )


def structure(client: TestClient) -> tuple[str, dict[str, Any], dict[str, Any]]:
    project = _create_project(client, "Lifecycle")
    path = f"/api/v1/projects/{project['id']}"
    stage = client.post(
        f"{path}/stages", json={"name": "Design", "position": 0, "expectedProjectRevision": 1}
    ).json()
    milestone = client.post(
        f"{path}/milestones",
        json={"name": "Review", "stageId": stage["id"], "expectedProjectRevision": 2},
    ).json()
    return path, stage, milestone


def patch(
    client: TestClient, path: str, row: dict[str, Any], archived: bool, project_revision: int
) -> Response:
    result = client.patch(
        f"{path}/{row['id']}",
        json={
            "archived": archived,
            "expectedRevision": row["revision"],
            "expectedProjectRevision": project_revision,
        },
    )

    assert result.headers["x-request-id"]
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["access-control-allow-origin"] == "http://localhost:5500"
    return result


def test_lifecycle_revisions_events_noop_and_parent_restore(
    client: TestClient, database: Database
) -> None:
    path, stage, milestone = structure(client)
    assert stage["archived"] is False and milestone["archived"] is False
    before = counts(database)
    assert patch(client, f"{path}/stages", stage, False, 3).json() == stage
    assert patch(client, f"{path}/milestones", milestone, False, 3).json() == milestone
    assert_error(patch(client, f"{path}/stages", stage, True, 3), 409, "structure_in_use")
    assert counts(database) == before and revision(client, path) == 3
    result = patch(client, f"{path}/milestones", milestone, True, 3)
    assert result.status_code == 200
    milestone = result.json()
    assert milestone["archived"] is True and milestone["revision"] == 2
    after_milestone = counts(database)
    assert patch(client, f"{path}/milestones", milestone, True, 4).json() == milestone
    assert counts(database) == after_milestone and revision(client, path) == 4
    result = patch(client, f"{path}/stages", stage, True, 4)
    assert result.status_code == 200
    stage = result.json()
    assert stage["archived"] is True and stage["revision"] == 2
    after = counts(database)
    assert patch(client, f"{path}/stages", stage, True, 5).json() == stage
    assert counts(database) == after and revision(client, path) == 5
    assert_error(patch(client, f"{path}/stages", stage, True, 4), 409, "revision_conflict")
    assert_error(
        patch(client, f"{path}/stages", {**stage, "revision": 1}, True, 5), 409, "revision_conflict"
    )
    assert client.get(f"{path}/stages").json()["items"][0]["archived"] is True
    assert client.get(f"{path}/milestones").json()["items"][0]["archived"] is True
    assert_error(
        patch(client, f"{path}/milestones", milestone, False, 5), 409, "structure_archived"
    )
    for resource, row in (("stages", stage), ("milestones", milestone)):
        assert_error(
            client.patch(
                f"{path}/{resource}/{row['id']}",
                json={"name": "Forbidden", "expectedRevision": 2, "expectedProjectRevision": 5},
            ),
            409,
            "structure_archived",
        )
    assert counts(database) == after
    stage = patch(client, f"{path}/stages", stage, False, 5).json()
    assert stage["revision"] == 3
    assert client.get(f"{path}/milestones").json()["items"][0]["archived"] is True
    milestone = patch(client, f"{path}/milestones", milestone, False, 6).json()
    assert milestone["revision"] == 3 and not milestone["archived"]
    assert revision(client, path) == 7
    with database.session_factory() as session:
        events = list(
            session.scalars(
                select(OutboxEvent.event_type).where(
                    OutboxEvent.aggregate_id == UUID(path.rsplit("/", 1)[1])
                )
            )
        )
        for action in (
            "milestone.archived",
            "stage.archived",
            "stage.restored",
            "milestone.restored",
        ):
            assert events.count(action) == 1
            assert (
                session.scalar(
                    select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
                )
                == 1
            )


@pytest.mark.parametrize("status", ["backlog", "done", "cancelled"])
def test_any_associated_task_blocks_archiving(
    client: TestClient, database: Database, status: str
) -> None:
    from cairn_api.projects.models import Task

    path, stage, milestone = structure(client)
    result = client.post(
        f"{path}/tasks",
        json={
            "title": "Keep association",
            "stageId": stage["id"],
            "milestoneId": milestone["id"],
            "expectedProjectRevision": 3,
        },
    )
    assert result.status_code == 201
    with database.session_factory.begin() as session:
        task = session.get(Task, UUID(result.json()["id"]))
        assert task is not None
        task.status = status
    before = counts(database)
    for resource, row in (("stages", stage), ("milestones", milestone)):
        assert_error(patch(client, f"{path}/{resource}", row, True, 4), 409, "structure_in_use")
    assert counts(database) == before and revision(client, path) == 4
    cleared = client.patch(
        f"/api/v1/tasks/{result.json()['id']}",
        json={
            "stageId": None,
            "milestoneId": None,
            "expectedRevision": 1,
            "expectedProjectRevision": 4,
        },
    )
    assert cleared.status_code == 200
    assert patch(client, f"{path}/milestones", milestone, True, 5).status_code == 200
    assert patch(client, f"{path}/stages", stage, True, 6).status_code == 200


def test_archived_assignment_rejected_at_all_writers(
    client: TestClient, database: Database
) -> None:
    path, stage, milestone = structure(client)
    task = _create_task(client, path.rsplit("/", 1)[1], "Ungrouped")
    milestone = patch(client, f"{path}/milestones", milestone, True, 4).json()
    stage = patch(client, f"{path}/stages", stage, True, 5).json()
    before = counts(database)
    requests = [
        client.post(
            f"{path}/tasks",
            json={"title": "No", "stageId": stage["id"], "expectedProjectRevision": 6},
        ),
        client.post(
            f"{path}/tasks",
            json={"title": "No", "milestoneId": milestone["id"], "expectedProjectRevision": 6},
        ),
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"stageId": stage["id"], "expectedRevision": 1, "expectedProjectRevision": 6},
        ),
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={
                "milestoneId": milestone["id"],
                "expectedRevision": 1,
                "expectedProjectRevision": 6,
            },
        ),
        client.post(
            f"{path}/milestones",
            json={"name": "No", "stageId": stage["id"], "expectedProjectRevision": 6},
        ),
    ]
    other = client.post(
        f"{path}/milestones", json={"name": "Active", "expectedProjectRevision": 6}
    ).json()
    requests.append(
        client.patch(
            f"{path}/milestones/{other['id']}",
            json={"stageId": stage["id"], "expectedRevision": 1, "expectedProjectRevision": 7},
        )
    )
    for response in requests:
        assert_error(response, 409, "structure_archived")
    assert counts(database) == (before[0] + 1, before[1] + 1)
    assert revision(client, path) == 7


@pytest.mark.parametrize("resource", ["stages", "milestones"])
@pytest.mark.parametrize("archived", [True, False])
@pytest.mark.parametrize(
    "failure,status,code",
    [("database", 503, "database_unavailable"), ("unexpected", 500, "internal_error")],
)
def test_lifecycle_rolls_back_after_audit_and_outbox(
    client: TestClient,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    archived: bool,
    failure: str,
    status: int,
    code: str,
) -> None:
    from cairn_api.projects.service import ProjectService

    path, stage, milestone = structure(client)
    if resource == "stages":
        milestone = patch(client, f"{path}/milestones", milestone, True, 3).json()
    row = stage if resource == "stages" else milestone
    if not archived:
        row = patch(client, f"{path}/{resource}", row, True, revision(client, path)).json()
    expected = revision(client, path)
    before = counts(database)
    original = ProjectService._outbox

    def broken(
        self: ProjectService,
        *,
        org_id: UUID,
        event_type: str,
        project_id: UUID,
        payload: dict[str, object],
    ) -> None:
        original(self, org_id=org_id, event_type=event_type, project_id=project_id, payload=payload)
        self._session.flush()
        if failure == "database":
            raise OperationalError("private SQL", {}, Exception("offline"))
        raise RuntimeError("private marker")

    monkeypatch.setattr(ProjectService, "_outbox", broken)
    assert_error(patch(client, f"{path}/{resource}", row, archived, expected), status, code)
    assert counts(database) == before and revision(client, path) == expected
    stored = client.get(f"{path}/{resource}").json()["items"][0]
    assert stored["archived"] is row["archived"] and stored["revision"] == row["revision"]


@pytest.mark.parametrize("resource", ["stages", "milestones"])
def test_lifecycle_validation_auth_scope_and_project_acl(
    client: TestClient, database: Database, api_settings: Settings, resource: str
) -> None:
    from cairn_api.authorization.models import ResourceAclEntry
    from cairn_api.authorization.types import MembershipRole
    from cairn_api.organizations.models import Membership

    from .authorization_helpers import authenticated_client, seed_actor

    path, stage, milestone = structure(client)
    row = stage if resource == "stages" else milestone
    endpoint = f"{path}/{resource}/{row['id']}"
    base = {"expectedRevision": 1, "expectedProjectRevision": 3}
    before = counts(database)
    for body in ({**base, "archived": value} for value in (None, "true", 1)):
        result = client.patch(endpoint, json=body)
        assert_error(result, 422, "validation_error")
        assert result.headers["access-control-allow-origin"] == "http://localhost:5500"
    assert_error(
        client.patch(endpoint, json={**base, "archived": True, "name": "Mixed"}),
        422,
        "validation_error",
    )
    assert_error(
        client.patch(endpoint, headers={"X-CSRF-Token": "wrong"}, json={**base, "archived": True}),
        403,
        "csrf_failed",
    )
    other = _create_project(client, "Other")
    assert_error(
        client.patch(
            f"/api/v1/projects/{other['id']}/{resource}/{row['id']}",
            json={**base, "archived": True},
        ),
        404,
        "not_found",
    )
    identity = client.get("/api/v1/session").json()
    member = seed_actor(database, MembershipRole.MEMBER, UUID(identity["organization"]["id"]))
    with database.session_factory.begin() as session:
        session.add(
            ResourceAclEntry(
                org_id=member.organization_id,
                resource_type="project",
                resource_id=UUID(path.rsplit("/", 1)[1]),
                principal_type="user",
                principal_id=str(member.user_id),
                permission="read",
                granted_by_type="system",
            )
        )
    with authenticated_client(api_settings, database, member) as reader:
        assert reader.get(f"{path}/{resource}").status_code == 200
        assert_error(reader.patch(endpoint, json={**base, "archived": True}), 404, "not_found")
    foreign = seed_actor(database, MembershipRole.OWNER)
    with authenticated_client(api_settings, database, foreign) as outsider:
        assert_error(outsider.patch(endpoint, json={**base, "archived": True}), 404, "not_found")
    with database.session_factory.begin() as session:
        membership = session.get(Membership, UUID(identity["membership"]["id"]))
        assert membership is not None
        membership.role = "viewer"
    assert client.get(f"{path}/{resource}").status_code == 200
    assert_error(client.patch(endpoint, json={**base, "archived": True}), 404, "not_found")
    assert revision(client, path) == 3
    assert counts(database) == (before[0] + 1, before[1] + 1)
    client.cookies.clear()
    assert_error(client.patch(endpoint, json={**base, "archived": True}), 401, "session_invalid")


@pytest.mark.parametrize("status", ["backlog", "done", "cancelled"])
def test_stage_task_occupancy_without_milestones(
    client: TestClient, database: Database, status: str
) -> None:
    from cairn_api.projects.models import Task

    project = _create_project(client, "Stage occupancy")
    path = f"/api/v1/projects/{project['id']}"
    stage = client.post(
        f"{path}/stages", json={"name": "Only stage", "position": 0, "expectedProjectRevision": 1}
    ).json()
    created = client.post(
        f"{path}/tasks",
        json={"title": "Linked", "stageId": stage["id"], "expectedProjectRevision": 2},
    ).json()
    with database.session_factory.begin() as session:
        task = session.get(Task, UUID(created["id"]))
        assert task is not None
        task.status = status
    before = counts(database)
    assert_error(patch(client, f"{path}/stages", stage, True, 3), 409, "structure_in_use")
    assert counts(database) == before and revision(client, path) == 3
    assert client.get(f"{path}/stages").json()["items"][0]["archived"] is False


@pytest.mark.parametrize("resource", ["stages", "milestones"])
@pytest.mark.parametrize("archived", [True, False])
def test_http_creation_rejects_archived_state_without_business_writes(
    client: TestClient, database: Database, resource: str, archived: bool
) -> None:
    project = _create_project(client, "Creation lifecycle validation")
    path = f"/api/v1/projects/{project['id']}"
    before = counts(database)
    result = client.post(
        f"{path}/{resource}",
        json={
            "name": "Forbidden",
            "expectedProjectRevision": 1,
            "archived": archived,
            **({"position": 0} if resource == "stages" else {}),
        },
    )
    assert_error(result, 422, "validation_error")
    assert result.headers["access-control-allow-origin"] == "http://localhost:5500"
    assert revision(client, path) == 1
    assert client.get(f"{path}/{resource}").json()["items"] == []
    assert counts(database) == before
