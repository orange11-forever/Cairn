"""Observable structure contract, grouping invariants and atomic project revisions."""

from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.db.session import Database
from cairn_api.organizations.models import Membership, Organization
from cairn_api.projects.models import (
    Milestone,
    OutboxEvent,
    Project,
    ProjectStage,
    Task,
    TaskDependency,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from .test_projects_api import _create_project, _create_task, api_settings, client
from .test_task_editing_api import assert_error

# pyright: reportPrivateUsage=false

__all__ = ["api_settings", "client"]
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("field", ["stageId", "milestoneId"])
@pytest.mark.parametrize("mixed", [False, True])
def test_null_grouping_revision_rejected_with_traced_validation_and_no_mutation(
    client: TestClient,
    field: str,
    mixed: bool,
) -> None:
    project = _create_project(client, "Null grouping revision")
    task = _create_task(client, str(project["id"]), "Keep")
    body: dict[str, object] = {"expectedRevision": 1, "expectedProjectRevision": None, field: None}
    if mixed:
        body["title"] = "Must not save"
    response = client.patch(f"/api/v1/tasks/{task['id']}", json=body)
    assert_error(response, 422, "validation_error")
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
    stored = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert stored["revision"] == 1 and stored["title"] == "Keep"
    assert revision(client, f"/api/v1/projects/{project['id']}") == 2


def revision(client: TestClient, path: str) -> int:
    response = client.get(path)
    assert response.status_code == 200
    return response.json()["revision"]


def test_structure_create_edit_paging_and_task_grouping(client: TestClient) -> None:
    project = _create_project(client, "Structure")
    path = f"/api/v1/projects/{project['id']}"
    assert project["revision"] == 1
    stages: list[dict[str, object]] = []
    for index in range(3):
        result = client.post(
            f"{path}/stages",
            json={
                "name": f"Stage {index}",
                "position": index,
                "expectedProjectRevision": index + 1,
            },
        )
        assert result.status_code == 201, result.text
        assert set(result.json()) == {
            "id",
            "projectId",
            "revision",
            "archived",
            "name",
            "position",
            "createdAt",
            "updatedAt",
        }
        assert result.headers["x-request-id"]
        assert result.headers["cache-control"] == "private, no-store"
        assert result.headers["x-content-type-options"] == "nosniff"
        assert result.json()["revision"] == 1 and result.json()["projectId"] == project["id"]
        stages.append(result.json())
    assert_error(
        client.post(
            f"{path}/stages", json={"name": "Stale", "position": 3, "expectedProjectRevision": 1}
        ),
        409,
        "revision_conflict",
    )
    page = client.get(f"{path}/stages?limit=2").json()
    assert len(page["items"]) == 2 and page["nextCursor"]
    assert (
        len(
            client.get(f"{path}/stages", params={"cursor": page["nextCursor"], "limit": 2}).json()[
                "items"
            ]
        )
        == 1
    )
    other = _create_project(client, "Other")
    assert_error(
        client.get(f"/api/v1/projects/{other['id']}/stages", params={"cursor": page["nextCursor"]}),
        422,
        "invalid_cursor",
    )
    assert_error(
        client.get(f"{path}/milestones", params={"cursor": page["nextCursor"]}),
        422,
        "invalid_cursor",
    )
    edit = client.patch(
        f"{path}/stages/{stages[0]['id']}",
        json={"expectedRevision": 1, "expectedProjectRevision": 4, "name": "Design", "position": 5},
    )
    assert edit.status_code == 200 and edit.json()["revision"] == 2
    milestone = client.post(
        f"{path}/milestones",
        json={
            "name": "Review",
            "stageId": stages[0]["id"],
            "description": "Scope",
            "acceptanceCriteria": "Done",
            "dueAt": "2026-10-09T01:00:00+08:00",
            "expectedProjectRevision": 5,
        },
    )
    assert milestone.status_code == 201, milestone.text
    assert set(milestone.json()) == {
        "id",
        "projectId",
        "revision",
        "archived",
        "name",
        "description",
        "acceptanceCriteria",
        "dueAt",
        "stageId",
        "createdAt",
        "updatedAt",
    }
    assert milestone.headers["cache-control"] == "private, no-store"
    assert milestone.headers["x-content-type-options"] == "nosniff"
    milestone_id = milestone.json()["id"]
    task = client.post(
        f"{path}/tasks",
        json={
            "title": "Grouped",
            "stageId": stages[0]["id"],
            "milestoneId": milestone_id,
            "expectedProjectRevision": 6,
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["milestoneId"] == milestone_id
    task_path = f"/api/v1/tasks/{task.json()['id']}"
    assert client.get(f"{path}/tasks").json()["items"][0]["milestoneId"] == milestone_id
    assert_error(
        client.patch(
            f"{path}/milestones/{milestone_id}",
            json={"expectedRevision": 1, "expectedProjectRevision": 7, "stageId": stages[1]["id"]},
        ),
        409,
        "milestone_in_use",
    )
    assert_error(
        client.patch(
            task_path,
            json={"expectedRevision": 1, "expectedProjectRevision": 7, "stageId": stages[1]["id"]},
        ),
        422,
        "invalid_grouping",
    )
    assert revision(client, path) == 7

    assert_error(
        client.post(f"{path}/tasks", json={"title": "Stale", "expectedProjectRevision": 1}),
        409,
        "revision_conflict",
    )
    assert revision(client, path) == 7
    cleared = client.patch(
        task_path,
        json={
            "expectedRevision": 1,
            "expectedProjectRevision": 7,
            "stageId": None,
            "milestoneId": None,
        },
    )
    assert (
        cleared.status_code == 200
        and cleared.json()["stageId"] is None
        and cleared.json()["milestoneId"] is None
    )
    moved = client.patch(
        f"{path}/milestones/{milestone_id}",
        json={
            "expectedRevision": 1,
            "expectedProjectRevision": 8,
            "stageId": stages[1]["id"],
            "description": None,
            "acceptanceCriteria": None,
            "dueAt": None,
        },
    )
    assert (
        moved.status_code == 200 and moved.json()["revision"] == 2 and moved.json()["dueAt"] is None
    )
    assert revision(client, path) == 9


def test_stage_page_bookmark_does_not_skip_unloaded_rows_after_stage_reposition(
    client: TestClient,
) -> None:
    project = _create_project(client, "Position bookmark")
    path = f"/api/v1/projects/{project['id']}"
    stages: list[dict[str, object]] = []
    for index in range(2):
        stages.append(
            client.post(
                f"{path}/stages",
                json={
                    "name": f"Stage {index}",
                    "position": index,
                    "expectedProjectRevision": index + 1,
                },
            ).json()
        )
    page = client.get(f"{path}/stages?limit=1").json()
    assert page["items"][0]["id"] == stages[0]["id"]
    assert (
        client.patch(
            f"{path}/stages/{stages[0]['id']}",
            json={"position": 100, "expectedRevision": 1, "expectedProjectRevision": 3},
        ).status_code
        == 200
    )
    remaining = client.get(f"{path}/stages", params={"cursor": page["nextCursor"]}).json()["items"]
    assert stages[1]["id"] in {row["id"] for row in remaining}


def test_legacy_task_writers_advance_project_once_and_rejections_do_not(client: TestClient) -> None:
    project = _create_project(client, "Legacy revisions")
    path = f"/api/v1/projects/{project['id']}"
    one = _create_task(client, str(project["id"]), "One")
    two = _create_task(client, str(project["id"]), "Two")
    assert revision(client, path) == 3
    task_path = f"/api/v1/tasks/{two['id']}"
    assert (
        client.patch(task_path, json={"expectedRevision": 1, "title": "Edited"}).status_code == 200
    )
    assert revision(client, path) == 4
    assert client.patch(f"{task_path}/status", json={"status": "todo"}).status_code == 200
    assert revision(client, path) == 5
    edge = client.post(f"{task_path}/dependencies", json={"predecessorTaskId": one["id"]})
    assert edge.status_code == 201
    assert revision(client, path) == 6
    assert_error(
        client.post(f"{task_path}/dependencies", json={"predecessorTaskId": one["id"]}),
        409,
        "dependency_exists",
    )
    assert (
        client.delete(
            f"{task_path}/dependencies/{edge.json()['id']}?expectedRevision=4"
        ).status_code
        == 204
    )
    assert revision(client, path) == 7


@pytest.mark.parametrize("resource", ["stages", "milestones"])
@pytest.mark.parametrize(
    "failure,status,code",
    [("database", 503, "database_unavailable"), ("unexpected", 500, "internal_error")],
)
def test_structure_read_faults_keep_error_schema_trace_and_security_headers(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    resource: str,
    failure: str,
    status: int,
    code: str,
) -> None:
    from cairn_api.projects import structure_repository

    project = _create_project(client, "Read faults")

    def broken(*_args: object, **_kwargs: object) -> None:
        if failure == "database":
            raise OperationalError("private SQL marker", {}, Exception("private values"))
        raise RuntimeError("private unexpected marker")

    monkeypatch.setattr(structure_repository, f"list_{resource}", broken)
    response = client.get(f"/api/v1/projects/{project['id']}/{resource}")
    assert_error(response, status, code)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
    assert (
        "private SQL marker" not in caplog.text and "private unexpected marker" not in caplog.text
    )


@pytest.mark.parametrize("foreign_scope", ["project", "tenant"])
def test_cross_scope_structure_references_are_hidden_without_business_writes(
    client: TestClient,
    database: Database,
    foreign_scope: str,
) -> None:
    first = _create_project(client, "First scope")
    second = _create_project(client, "Second scope")
    path = f"/api/v1/projects/{first['id']}"
    foreign_path = f"/api/v1/projects/{second['id']}"
    foreign = client.post(
        f"{foreign_path}/stages",
        json={"name": "Foreign", "position": 0, "expectedProjectRevision": 1},
    ).json()
    foreign_milestone = client.post(
        f"{foreign_path}/milestones",
        json={"name": "Foreign milestone", "stageId": foreign["id"], "expectedProjectRevision": 2},
    ).json()
    if foreign_scope == "tenant":
        with database.session_factory.begin() as session:
            organization = Organization(slug=f"foreign-{uuid4().hex}", name="Foreign")
            session.add(organization)
            session.flush()
            foreign_project = Project(org_id=organization.id, name="Foreign")
            session.add(foreign_project)
            session.flush()
            foreign_stage = ProjectStage(
                org_id=organization.id, project_id=foreign_project.id, name="Foreign", position=0
            )
            session.add(foreign_stage)
            session.flush()
            foreign_row = Milestone(
                org_id=organization.id,
                project_id=foreign_project.id,
                name="Foreign milestone",
                stage_id=foreign_stage.id,
            )
            session.add(foreign_row)
            session.flush()
            foreign = {"id": str(foreign_stage.id)}
            foreign_milestone = {"id": str(foreign_row.id)}
    task = _create_task(client, str(first["id"]), "Stay scoped")
    with database.session_factory() as session:
        audit_count = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.resource_type.in_(("project", "task", "stage", "milestone")))
        )
        outbox_count = session.scalar(select(func.count()).select_from(OutboxEvent))
    requests = [
        client.post(
            f"{path}/milestones",
            json={"name": "Hidden", "stageId": foreign["id"], "expectedProjectRevision": 2},
        ),
        client.patch(
            f"{path}/stages/{foreign['id']}",
            json={"name": "Hidden", "expectedRevision": 1, "expectedProjectRevision": 2},
        ),
        client.patch(
            f"{path}/milestones/{foreign_milestone['id']}",
            json={"name": "Hidden", "expectedRevision": 1, "expectedProjectRevision": 2},
        ),
        client.post(
            f"{path}/tasks",
            json={
                "title": "Hidden",
                "stageId": foreign["id"],
                "milestoneId": foreign_milestone["id"],
                "expectedProjectRevision": 2,
            },
        ),
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={
                "expectedRevision": 1,
                "expectedProjectRevision": 2,
                "milestoneId": foreign_milestone["id"],
            },
        ),
    ]
    for response in requests:
        assert_error(response, 404, "not_found")
    assert revision(client, path) == 2 and revision(client, foreign_path) == 3
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type.in_(("project", "task", "stage", "milestone")))
            )
            == audit_count
        )
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == outbox_count


def test_structure_openapi_success_errors_headers_and_patch_constraints(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    for resource, stem, response_name in (
        ("stages", "stage", "Stage"),
        ("milestones", "milestone", "Milestone"),
    ):
        for suffix, methods in (("", ("get", "post")), (f"/{{{stem}_id}}", ("patch",))):
            path = f"/api/v1/projects/{{project_id}}/{resource}{suffix}"
            for method in methods:
                operation = document["paths"][path][method]
                expected_status = "201" if method == "post" else "200"
                assert operation["responses"][expected_status]["content"]["application/json"][
                    "schema"
                ]["$ref"].endswith(f"/{response_name}{'Page' if method == 'get' else 'Response'}")
                for status in ("401", "404", "422", "500", "503"):
                    response = operation["responses"][status]
                    assert response["content"]["application/json"]["schema"]["$ref"].endswith(
                        "/ErrorBody"
                    )
                    assert set(response["headers"]) == {
                        "X-Request-ID",
                        "Cache-Control",
                        "X-Content-Type-Options",
                    }
                if method != "get":
                    assert "409" in operation["responses"] and "403" in operation["responses"]
                    csrf = next(
                        parameter
                        for parameter in operation["parameters"]
                        if parameter["name"] == "X-CSRF-Token"
                    )
                    assert csrf["required"] is True
        patch = document["components"]["schemas"][f"{response_name}UpdateRequest"]
        assert all(
            {"expectedRevision", "expectedProjectRevision"}.issubset(branch["required"])
            and len(branch["required"]) == 3
            for branch in patch["anyOf"]
        )


@pytest.mark.parametrize("resource", ["stages", "milestones"])
def test_structure_validation_scope_auth_csrf_protocol(
    client: TestClient, database: Database, resource: str
) -> None:
    project = _create_project(client, "Permissions")
    path = f"/api/v1/projects/{project['id']}/{resource}"
    valid = {
        "name": "X",
        "expectedProjectRevision": 1,
        **({"position": 0} if resource == "stages" else {}),
    }
    assert_error(client.post(path, json={"name": "Missing revision"}), 422, "validation_error")
    assert_error(client.get(f"{path}?limit=0"), 422, "validation_error")
    assert_error(client.get(f"{path}?cursor=bad"), 422, "invalid_cursor")
    assert_error(client.post(path, headers={"X-CSRF-Token": "bad"}, json=valid), 403, "csrf_failed")
    result = client.post(path, json=valid)
    assert result.status_code == 201
    object_path = f"{path}/{result.json()['id']}"
    assert_error(
        client.patch(object_path, json={"expectedRevision": 1, "expectedProjectRevision": 2}),
        422,
        "validation_error",
    )
    assert_error(
        client.patch(
            object_path,
            json={"expectedRevision": 2, "expectedProjectRevision": 2, "name": "Stale object"},
        ),
        409,
        "revision_conflict",
    )
    assert_error(
        client.patch(
            f"{path}/{uuid4()}",
            json={"expectedRevision": 1, "expectedProjectRevision": 2, "name": "Invisible"},
        ),
        404,
        "not_found",
    )
    identity = client.get("/api/v1/session").json()
    with database.session_factory.begin() as session:
        member = session.get(Membership, UUID(identity["membership"]["id"]))
        assert member is not None
        member.role = "viewer"
    assert client.get(path).status_code == 200
    valid["expectedProjectRevision"] = 2
    assert_error(client.post(path, json=valid), 404, "not_found")
    assert_error(
        client.patch(
            object_path,
            json={"expectedRevision": 1, "expectedProjectRevision": 2, "name": "Denied"},
        ),
        404,
        "not_found",
    )
    protocol = client.put(path, json=valid)
    assert protocol.status_code == 405 and set(protocol.headers["allow"].split(", ")) == {
        "GET",
        "POST",
    }
    assert protocol.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/v1/projects/{project['id']}").json()["revision"] == 2
    client.cookies.clear()
    assert_error(client.get(path), 401, "session_invalid")
    assert_error(client.post(path, json=valid), 401, "session_invalid")
    assert_error(
        client.patch(
            object_path,
            json={"name": "Denied", "expectedRevision": 1, "expectedProjectRevision": 2},
        ),
        401,
        "session_invalid",
    )


@pytest.mark.parametrize(
    "operation", ["stage_create", "stage_edit", "milestone_create", "milestone_edit"]
)
@pytest.mark.parametrize(
    "failure,status,code",
    [("database", 503, "database_unavailable"), ("unexpected", 500, "internal_error")],
)
def test_structure_rollback_after_audit_and_outbox(
    client: TestClient,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failure: str,
    status: int,
    code: str,
) -> None:
    from cairn_api.projects.service import ProjectService

    project = _create_project(client, "Atomic structure")
    path = f"/api/v1/projects/{project['id']}"
    resource = "stages" if operation.startswith("stage") else "milestones"
    body = {
        "name": "Original",
        "expectedProjectRevision": 1,
        **({"position": 0} if resource == "stages" else {}),
    }
    row = (
        client.post(f"{path}/{resource}", json=body).json() if operation.endswith("edit") else None
    )
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
    if row:
        response = client.patch(
            f"{path}/{resource}/{row['id']}",
            json={"name": "Lost", "expectedRevision": 1, "expectedProjectRevision": 2},
        )
    else:
        response = client.post(f"{path}/{resource}", json=body)
    assert_error(response, status, code)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
    assert revision(client, path) == (2 if row else 1)
    rows = client.get(f"{path}/{resource}").json()["items"]
    assert len(rows) == (1 if row else 0)
    if row:
        assert rows[0]["name"] == "Original" and rows[0]["revision"] == 1
    with database.session_factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.aggregate_id == UUID(str(project["id"])))
        ) == (2 if row else 1)
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action.in_(("stage.updated", "milestone.updated")))
            )
            == 0
        )


@pytest.mark.parametrize("operation", ["create", "details", "status", "add", "delete"])
@pytest.mark.parametrize(
    "failure,status,code",
    [("database", 503, "database_unavailable"), ("unexpected", 500, "internal_error")],
)
def test_legacy_mutation_failure_rolls_back_project_revision_and_all_business_rows(
    client: TestClient,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failure: str,
    status: int,
    code: str,
) -> None:
    from cairn_api.projects.service import ProjectService

    project = _create_project(client, "Atomic legacy")
    first = _create_task(client, str(project["id"]), "First")
    second = _create_task(client, str(project["id"]), "Second")
    task_path = f"/api/v1/tasks/{second['id']}"
    edge = None
    if operation == "delete":
        edge = client.post(
            f"{task_path}/dependencies", json={"predecessorTaskId": first["id"]}
        ).json()
    before_revision = revision(client, f"/api/v1/projects/{project['id']}")
    with database.session_factory() as session:
        task_before = [
            tuple(row)
            for row in session.execute(
                select(Task.id, Task.title, Task.status, Task.revision)
                .where(Task.project_id == UUID(str(project["id"])))
                .order_by(Task.id)
            )
        ]
        edge_count = session.scalar(select(func.count()).select_from(TaskDependency))
        audit_count = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.resource_type.in_(("project", "task", "task_dependency")))
        )
        outbox_count = session.scalar(select(func.count()).select_from(OutboxEvent))
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
    if operation == "create":
        response = client.post(
            f"/api/v1/projects/{project['id']}/tasks", json={"title": "Rollback"}
        )
    elif operation == "details":
        response = client.patch(task_path, json={"expectedRevision": 1, "title": "Rollback"})
    elif operation == "status":
        response = client.patch(f"{task_path}/status", json={"status": "todo"})
    elif operation == "add":
        response = client.post(f"{task_path}/dependencies", json={"predecessorTaskId": first["id"]})
    else:
        assert edge is not None
        response = client.delete(f"{task_path}/dependencies/{edge['id']}?expectedRevision=2")
    assert_error(response, status, code)
    with database.session_factory() as session:
        stored = session.get(Project, UUID(str(project["id"])))
        assert stored is not None and stored.revision == before_revision
        assert [
            tuple(row)
            for row in session.execute(
                select(Task.id, Task.title, Task.status, Task.revision)
                .where(Task.project_id == UUID(str(project["id"])))
                .order_by(Task.id)
            )
        ] == task_before
        assert session.scalar(select(func.count()).select_from(TaskDependency)) == edge_count
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type.in_(("project", "task", "task_dependency")))
            )
            == audit_count
        )
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == outbox_count
