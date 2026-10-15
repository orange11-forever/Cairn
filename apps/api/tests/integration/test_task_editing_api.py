"""Task consumers observe revisions, authorization, pagination and atomic failures."""

from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import User
from cairn_api.db.session import Database
from cairn_api.organizations.models import Membership, Organization
from cairn_api.projects.models import OutboxEvent, Task
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

# pyright: reportPrivateUsage=false
from .test_projects_api import _create_project, _create_task, api_settings, client

__all__ = ["api_settings", "client"]
pytestmark = pytest.mark.integration


def assert_error(response: Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"code", "message", "traceId"}
    assert body["code"] == code
    assert body["traceId"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_task_details_edit_conflict_null_and_legacy_revision(client: TestClient) -> None:
    project = _create_project(client, "Editor")
    task = _create_task(client, str(project["id"]), "Initial")
    path = f"/api/v1/tasks/{task['id']}"
    detail = client.get(path)
    assert detail.status_code == 200
    assert detail.json()["revision"] == 1
    assert detail.json()["description"] is None
    saved = client.patch(
        path,
        json={
            "expectedRevision": 1,
            "title": " Updated ",
            "description": "Details",
            "assigneeUserId": None,
            "priority": "critical",
            "dueAt": "2026-10-06T12:00:00+08:00",
            "acceptanceCriteria": "Observable",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert saved.json()["title"] == "Updated"
    assert saved.json()["description"] == "Details"
    assert saved.json()["priority"] == "critical"
    assert_error(
        client.patch(path, json={"expectedRevision": 1, "title": "Stale"}), 409, "revision_conflict"
    )
    cleared = client.patch(
        path,
        json={
            "expectedRevision": 2,
            "description": None,
            "dueAt": None,
            "acceptanceCriteria": None,
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["title"] == "Updated"
    assert cleared.json()["description"] is None
    moved = client.patch(f"{path}/status", json={"status": "todo"})
    assert moved.status_code == 200
    assert moved.json()["revision"] == 4
    assert_error(
        client.patch(f"{path}/status", json={"status": "in_progress", "expectedRevision": 3}),
        409,
        "revision_conflict",
    )
    listed = client.get(f"/api/v1/projects/{project['id']}/tasks").json()["items"][0]
    assert listed["revision"] == 4 and listed["description"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"expectedRevision": 1},
        {"expectedRevision": 0, "title": "x"},
        {"expectedRevision": 1, "title": None},
        {"expectedRevision": 1, "priority": None},
        {"expectedRevision": 1, "title": "   "},
        {"expectedRevision": 1, "status": "done"},
        {"expectedRevision": 1, "description": "x" * 10001},
        {"expectedRevision": 1, "dueAt": "2026-10-05T00:00:00"},
    ],
)
def test_patch_validation_leaves_task_unchanged(
    client: TestClient, patch: dict[str, object]
) -> None:
    project = _create_project(client, "Validation")
    task = _create_task(client, str(project["id"]), "Valid")
    path = f"/api/v1/tasks/{task['id']}"
    assert_error(client.patch(path, json=patch), 422, "validation_error")
    assert client.get(path).json()["revision"] == 1


def test_dependency_pages_delete_ownership_replay_and_cursor_scope(client: TestClient) -> None:
    project = _create_project(client, "Edges")
    tasks = [
        _create_task(client, str(project["id"]), name)
        for name in ("One", "Two", "Three", "Successor")
    ]
    path = f"/api/v1/tasks/{tasks[-1]['id']}"
    edges: list[dict[str, object]] = []
    for revision, predecessor in enumerate(tasks[:-1], 1):
        response = client.post(
            f"{path}/dependencies",
            json={"predecessorTaskId": predecessor["id"], "expectedRevision": revision},
        )
        assert response.status_code == 201
        edges.append(response.json())
    page = client.get(f"{path}/dependencies?limit=2").json()
    assert len(page["items"]) == 2 and page["nextCursor"]
    last = client.get(f"{path}/dependencies", params={"limit": 2, "cursor": page["nextCursor"]})
    assert len(last.json()["items"]) == 1
    other_path = f"/api/v1/tasks/{tasks[0]['id']}"
    assert_error(
        client.get(f"{other_path}/dependencies", params={"cursor": page["nextCursor"]}),
        422,
        "invalid_cursor",
    )
    assert_error(
        client.delete(f"{other_path}/dependencies/{edges[0]['id']}?expectedRevision=1"),
        404,
        "not_found",
    )
    assert_error(
        client.delete(f"{path}/dependencies/{edges[0]['id']}?expectedRevision=3"),
        409,
        "revision_conflict",
    )
    removed = client.delete(f"{path}/dependencies/{edges[0]['id']}?expectedRevision=4")
    assert removed.status_code == 204 and removed.content == b""
    assert_error(
        client.delete(f"{path}/dependencies/{edges[0]['id']}?expectedRevision=4"),
        409,
        "revision_conflict",
    )
    assert_error(
        client.delete(f"{path}/dependencies/{edges[0]['id']}?expectedRevision=5"), 404, "not_found"
    )
    assert client.get(path).json()["revision"] == 5


def test_assignees_hide_identity_and_validate_membership(
    client: TestClient, database: Database
) -> None:
    project = _create_project(client, "Assignees")
    identity = client.get("/api/v1/session").json()
    org_id = UUID(identity["organization"]["id"])
    with database.session_factory.begin() as session:
        members: list[UUID] = []
        for name, active in (("Available", True), ("Disabled", False)):
            user = User(email=f"{uuid4()}@example.test", display_name=name, is_active=active)
            session.add(user)
            session.flush()
            session.add(Membership(org_id=org_id, user_id=user.id, role="member"))
            members.append(user.id)
        foreign_org = Organization(slug=f"foreign-{uuid4().hex}", name="Foreign")
        foreign = User(display_name="Foreign")
        session.add_all((foreign_org, foreign))
        session.flush()
        session.add(Membership(org_id=foreign_org.id, user_id=foreign.id, role="owner"))
        foreign_id = foreign.id
    page = client.get(f"/api/v1/projects/{project['id']}/assignees?limit=1").json()
    all_items = list(page["items"])
    while page["nextCursor"]:
        page = client.get(
            f"/api/v1/projects/{project['id']}/assignees",
            params={"limit": 1, "cursor": page["nextCursor"]},
        ).json()
        all_items.extend(page["items"])
    assert all(set(item) == {"userId", "displayName", "role"} for item in all_items)
    assert str(members[0]) in {item["userId"] for item in all_items}
    assert str(members[1]) not in {item["userId"] for item in all_items}
    task = _create_task(client, str(project["id"]), "Assign")
    path = f"/api/v1/tasks/{task['id']}"
    for invalid in (members[1], foreign_id, uuid4()):
        assert_error(
            client.patch(path, json={"expectedRevision": 1, "assigneeUserId": str(invalid)}),
            422,
            "invalid_assignee",
        )
    result = client.patch(path, json={"expectedRevision": 1, "assigneeUserId": str(members[0])})
    assert result.status_code == 200 and result.json()["assigneeUserId"] == str(members[0])


@pytest.mark.parametrize(
    "failure,status,code",
    [("database", 503, "database_unavailable"), ("unexpected", 500, "internal_error")],
)
def test_edit_failure_rolls_back_task_audit_and_outbox(
    client: TestClient,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    status: int,
    code: str,
) -> None:
    project = _create_project(client, "Atomic")
    task = _create_task(client, str(project["id"]), "Original")
    from cairn_api.projects.service import ProjectService

    original = ProjectService._outbox

    def fail_after_outbox(
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
            raise OperationalError("private SQL", {}, Exception("unavailable"))
        raise RuntimeError("private unexpected details")

    monkeypatch.setattr(ProjectService, "_outbox", fail_after_outbox)
    assert_error(
        client.patch(
            f"/api/v1/tasks/{task['id']}", json={"expectedRevision": 1, "title": "Must roll back"}
        ),
        status,
        code,
    )
    with database.session_factory() as session:
        stored = session.get(Task, UUID(str(task["id"])))
        assert stored is not None and stored.title == "Original" and stored.revision == 1
        assert (
            session.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == "task.updated")
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "task.updated")
            )
            == 0
        )


def test_task_read_only_auth_csrf_and_protocol_contract(
    client: TestClient, database: Database
) -> None:
    project = _create_project(client, "Authorization")
    task = _create_task(client, str(project["id"]), "Private write")
    path = f"/api/v1/tasks/{task['id']}"
    identity = client.get("/api/v1/session").json()
    for bad_headers in ({"X-CSRF-Token": "invalid"}, {"Origin": "https://wrong.example.test"}):
        assert_error(
            client.patch(
                path, headers=bad_headers, json={"expectedRevision": 1, "title": "Denied"}
            ),
            403,
            "csrf_failed",
        )
    with database.session_factory.begin() as session:
        membership = session.get(Membership, UUID(identity["membership"]["id"]))
        assert membership is not None
        membership.role = "viewer"
    assert client.get(path).status_code == 200
    assert_error(
        client.patch(path, json={"expectedRevision": 1, "title": "Denied"}), 404, "not_found"
    )
    assert_error(
        client.post(
            f"{path}/dependencies", json={"predecessorTaskId": str(uuid4()), "expectedRevision": 1}
        ),
        404,
        "not_found",
    )
    assert_error(
        client.delete(f"{path}/dependencies/{uuid4()}?expectedRevision=1"), 404, "not_found"
    )
    assert_error(client.get(f"/api/v1/tasks/{uuid4()}"), 404, "not_found")
    assert_error(client.get(f"{path}/dependencies?cursor=malformed"), 422, "invalid_cursor")
    protocol = client.put(path, json={})
    assert protocol.status_code == 405
    assert set(protocol.headers["allow"].split(", ")) == {"GET", "PATCH"}
    preflight = client.options(
        path,
        headers={
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "X-CSRF-Token",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5500"
    client.cookies.clear()
    assert_error(client.get(path), 401, "session_invalid")


def test_openapi_task_contract_documents_errors_and_revision(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    for path, methods in {
        "/api/v1/tasks/{task_id}": ("get", "patch"),
        "/api/v1/projects/{project_id}/assignees": ("get",),
        "/api/v1/tasks/{task_id}/dependencies": ("get", "post"),
        "/api/v1/tasks/{task_id}/dependencies/{dependency_id}": ("delete",),
    }.items():
        for method in methods:
            operation = document["paths"][path][method]
            for status in ("401", "422", "503", "500", "404"):
                assert operation["responses"][status]["content"]["application/json"]["schema"][
                    "$ref"
                ].endswith("/ErrorBody")
            if method in ("patch", "post", "delete"):
                assert "403" in operation["responses"]
                assert "409" in operation["responses"]
    event_error = document["paths"]["/api/v1/projects/{project_id}/events"]["get"]["responses"]["401"]
    assert "Cache-Control" not in event_error.get("headers", {})
    fields = document["components"]["schemas"]["TaskResponse"]
    assert set(fields["required"]) >= {"revision", "description", "assigneeUserId"}


@pytest.mark.parametrize(
    "failure,status,code",
    [("database", 503, "database_unavailable"), ("unexpected", 500, "internal_error")],
)
@pytest.mark.parametrize(
    "operation", ["detail", "dependencies", "assignees", "status", "add", "delete"]
)
def test_affected_routes_keep_traced_headers_on_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
    status: int,
    code: str,
    operation: str,
) -> None:
    from cairn_api.projects import repository, task_repository

    project = _create_project(client, "Fault boundary")
    task = _create_task(client, str(project["id"]), "Fault task")
    path = f"/api/v1/tasks/{task['id']}"

    def broken(*_args: object, **_kwargs: object) -> None:
        if failure == "database":
            raise OperationalError("private SQL parameters", {}, Exception("private values"))
        raise RuntimeError("private task title must not log")

    if operation == "assignees":
        monkeypatch.setattr(task_repository, "list_assignees", broken)
    else:
        monkeypatch.setattr(repository, "get_task", broken)
    if operation == "detail":
        response = client.get(path)
    elif operation == "dependencies":
        response = client.get(f"{path}/dependencies")
    elif operation == "assignees":
        response = client.get(f"/api/v1/projects/{project['id']}/assignees")
    elif operation == "status":
        response = client.patch(f"{path}/status", json={"status": "todo", "expectedRevision": 1})
    elif operation == "add":
        response = client.post(
            f"{path}/dependencies", json={"predecessorTaskId": str(uuid4()), "expectedRevision": 1}
        )
    else:
        response = client.delete(f"{path}/dependencies/{uuid4()}?expectedRevision=1")
    assert_error(response, status, code)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
    assert "private SQL" not in caplog.text
    assert "private task title" not in caplog.text


def test_handled_task_500_does_not_escape_asgi_or_log_private_values(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from cairn_api.projects import repository

    project = _create_project(client, "ASGI error")
    task = _create_task(client, str(project["id"]), "ASGI task")

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private-input-marker")

    monkeypatch.setattr(repository, "get_task", broken)
    # Raising transport catches the ServerErrorMiddleware rethrow, including the
    # exception that a real ASGI server otherwise logs after sending the response.
    with TestClient(client.app, raise_server_exceptions=True) as raising:
        raising.cookies.update(client.cookies)
        raising.headers.update(client.headers)
        response = raising.get(f"/api/v1/tasks/{task['id']}")
    assert_error(response, 500, "internal_error")
    assert "private-input-marker" not in caplog.text
