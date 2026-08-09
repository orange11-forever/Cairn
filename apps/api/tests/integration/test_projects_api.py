from collections.abc import Generator
from uuid import uuid4

import pytest
from cairn_api.app import create_app
from cairn_api.db.session import Database
from cairn_api.organizations.models import Organization
from cairn_api.projects import repository
from cairn_api.projects.models import Project, Task
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

APP_ORIGIN = "http://localhost:5500"
DEMO_EMAIL = "demo@cairn.dev"
DEMO_PASSWORD = "cairn-demo-2026"


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


@pytest.fixture()
def client(
    database: Database,
    migrated_engine: object,
    api_settings: Settings,
) -> Generator[TestClient, None, None]:
    del migrated_engine
    seed_demo_identity(api_settings, database)
    with TestClient(
        create_app(api_settings, database),
        raise_server_exceptions=False,
    ) as test_client:
        response = test_client.post(
            "/api/v1/login",
            headers={"Origin": APP_ORIGIN, "X-Request-ID": "req-project-login"},
            json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        )
        assert response.status_code == 200
        test_client.headers.update(
            {
                "Origin": APP_ORIGIN,
                "X-CSRF-Token": response.json()["csrfToken"],
            }
        )
        yield test_client


def _create_project(client: TestClient, name: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        headers={"X-Request-ID": f"req-create-{name.lower().replace(' ', '-')}"},
        json={"name": name, "description": f"Description for {name}"},
    )
    assert response.status_code == 201
    return response.json()


def _create_task(
    client: TestClient,
    project_id: str,
    title: str,
    *,
    priority: str = "medium",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={
            "title": title,
            "priority": priority,
            "dueAt": "2026-08-20T09:30:00+08:00",
            "acceptanceCriteria": f"{title} is observable",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("repository_operation", "method", "path", "payload"),
    [
        ("list_projects", "GET", "/api/v1/projects", None),
        (
            "get_task",
            "PATCH",
            "/api/v1/tasks/00000000-0000-4000-8000-000000000901/status",
            {"status": "todo"},
        ),
    ],
)
def test_project_and_task_routes_return_traced_database_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    repository_operation: str,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    """Break caught: a post-identity domain database outage becomes an internal error."""

    def fail_database_operation(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("SELECT domain data", {}, Exception("database offline"))

    monkeypatch.setattr(repository, repository_operation, fail_database_operation)
    response = client.request(
        method,
        path,
        headers={"X-Request-ID": f"req-{repository_operation}-database-down"},
        json=payload,
    )

    assert response.status_code == 503
    assert response.json() == {
        "message": "数据库暂时不可用",
        "code": "database_unavailable",
        "traceId": f"req-{repository_operation}-database-down",
    }


@pytest.mark.integration
def test_project_routes_do_not_classify_programming_errors_as_database_outages(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: broad outage handling hides a programming defect behind a retryable 503."""

    def fail_programming_operation(*_args: object, **_kwargs: object) -> None:
        raise TypeError("project repository bug")

    monkeypatch.setattr(repository, "list_projects", fail_programming_operation)
    response = client.get(
        "/api/v1/projects",
        headers={"X-Request-ID": "req-project-programming-error"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器内部错误",
        "code": "internal_error",
        "traceId": "req-project-programming-error",
    }


@pytest.mark.integration
def test_project_mutations_require_origin_and_session_bound_csrf(
    client: TestClient,
) -> None:
    csrf_token = client.headers["X-CSRF-Token"]
    del client.headers["Origin"]
    del client.headers["X-CSRF-Token"]

    # Break caught: a cookie-authenticated write succeeds without CSRF proof.
    missing = client.post(
        "/api/v1/projects",
        headers={"X-Request-ID": "req-missing-project-csrf"},
        json={"name": "Missing CSRF"},
    )
    assert missing.status_code == 403
    assert missing.json() == {
        "message": "请求来源或 CSRF 令牌无效",
        "code": "csrf_failed",
        "traceId": "req-missing-project-csrf",
    }

    client.headers.update({"Origin": APP_ORIGIN, "X-CSRF-Token": "wrong-token"})
    wrong = client.post(
        "/api/v1/projects",
        headers={"X-Request-ID": "req-wrong-project-csrf"},
        json={"name": "Wrong CSRF"},
    )
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "csrf_failed"
    assert wrong.json()["traceId"] == "req-wrong-project-csrf"

    client.headers["X-CSRF-Token"] = csrf_token
    accepted = client.post("/api/v1/projects", json={"name": "Valid CSRF"})
    assert accepted.status_code == 201


@pytest.mark.integration
def test_project_mutations_reject_non_ascii_csrf_with_traced_forbidden_error(
    client: TestClient,
) -> None:
    # Break caught: untrusted non-ASCII header bytes crash string compare_digest as a 500.
    response = client.post(
        "/api/v1/projects",
        headers=[
            (b"x-request-id", b"req-non-ascii-project-csrf"),
            (b"x-csrf-token", b"\xff"),
        ],
        json={"name": "Malformed CSRF"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "message": "请求来源或 CSRF 令牌无效",
        "code": "csrf_failed",
        "traceId": "req-non-ascii-project-csrf",
    }


@pytest.mark.integration
def test_project_crud_is_authenticated_tenant_scoped_and_cursor_paginated(
    client: TestClient,
    database: Database,
) -> None:
    # Break caught: a caller-supplied tenant or audit field is accepted by project creation.
    rejected = client.post(
        "/api/v1/projects",
        headers={"X-Request-ID": "req-reject-identity"},
        json={
            "name": "Injected tenant",
            "org_id": str(uuid4()),
            "created_by": str(uuid4()),
            "actorId": str(uuid4()),
        },
    )
    assert rejected.status_code == 422
    assert rejected.json() == {
        "message": "请求参数无效",
        "code": "validation_error",
        "traceId": "req-reject-identity",
    }

    first = _create_project(client, "Project One")
    second = _create_project(client, "Project Two")
    third = _create_project(client, "Project Three")

    first_page = client.get("/api/v1/projects", params={"limit": 2})
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert [item["id"] for item in first_body["items"]] == [first["id"], second["id"]]
    assert isinstance(first_body["nextCursor"], str)

    second_page = client.get(
        "/api/v1/projects",
        params={"limit": 2, "cursor": first_body["nextCursor"]},
    )
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == [third["id"]]
    assert second_page.json()["nextCursor"] is None

    detail = client.get(f"/api/v1/projects/{first['id']}")
    assert detail.status_code == 200
    assert detail.json() == first

    other_org_id = uuid4()
    other_project_id = uuid4()
    other_task_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(Organization(id=other_org_id, slug="other-project-org", name="Other Org"))
        session.add(
            Project(
                id=other_project_id,
                org_id=other_org_id,
                name="Other Project",
                description=None,
            )
        )
        session.add(
            Task(
                id=other_task_id,
                org_id=other_org_id,
                project_id=other_project_id,
                title="Other task",
            )
        )

    hidden = client.get(
        f"/api/v1/projects/{other_project_id}",
        headers={"X-Request-ID": "req-cross-org-project"},
    )
    assert hidden.status_code == 404
    assert hidden.json() == {
        "message": "资源不存在",
        "code": "not_found",
        "traceId": "req-cross-org-project",
    }
    hidden_task = client.patch(
        f"/api/v1/tasks/{other_task_id}/status",
        headers={"X-Request-ID": "req-cross-org-task"},
        json={"status": "todo"},
    )
    assert hidden_task.status_code == 404
    assert hidden_task.json() == {
        "message": "资源不存在",
        "code": "not_found",
        "traceId": "req-cross-org-task",
    }


@pytest.mark.integration
def test_task_creation_and_listing_enforce_contract_and_cursor_pagination(
    client: TestClient,
) -> None:
    project = _create_project(client, "Task Project")
    project_id = str(project["id"])

    # Break caught: naive due dates or priority values outside the approved enum reach storage.
    naive_date = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"title": "Naive date", "dueAt": "2026-08-20T09:30:00"},
    )
    invalid_priority = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"title": "Invalid priority", "priority": "urgent"},
    )
    assert naive_date.status_code == 422
    assert naive_date.json()["code"] == "validation_error"
    assert invalid_priority.status_code == 422
    assert invalid_priority.json()["code"] == "validation_error"

    first = _create_task(client, project_id, "Task One", priority="high")
    second = _create_task(client, project_id, "Task Two")
    third = _create_task(client, project_id, "Task Three", priority="low")
    assert first["status"] == "backlog"
    assert first["priority"] == "high"
    assert isinstance(first["dueAt"], str)
    assert first["dueAt"].endswith("+08:00")

    first_page = client.get(
        f"/api/v1/projects/{project_id}/tasks",
        params={"limit": 2},
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert [item["id"] for item in first_body["items"]] == [first["id"], second["id"]]
    assert isinstance(first_body["nextCursor"], str)

    second_page = client.get(
        f"/api/v1/projects/{project_id}/tasks",
        params={"limit": 2, "cursor": first_body["nextCursor"]},
    )
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == [third["id"]]
    assert second_page.json()["nextCursor"] is None


@pytest.mark.integration
def test_project_and_task_lists_reject_malformed_cursors_with_traced_client_errors(
    client: TestClient,
) -> None:
    project = _create_project(client, "Cursor Project")
    _create_task(client, str(project["id"]), "Cursor Task")

    # Break caught: malformed client cursors escape as generic internal errors.
    project_page = client.get(
        "/api/v1/projects",
        headers={"X-Request-ID": "req-invalid-project-cursor"},
        params={"cursor": "not-a-cursor"},
    )
    task_page = client.get(
        f"/api/v1/projects/{project['id']}/tasks",
        headers={"X-Request-ID": "req-invalid-task-cursor"},
        params={"cursor": "not-a-cursor"},
    )

    assert project_page.status_code == 422
    assert project_page.json() == {
        "message": "分页游标无效",
        "code": "invalid_cursor",
        "traceId": "req-invalid-project-cursor",
    }
    assert task_page.status_code == 422
    assert task_page.json() == {
        "message": "分页游标无效",
        "code": "invalid_cursor",
        "traceId": "req-invalid-task-cursor",
    }


@pytest.mark.integration
def test_status_transitions_return_exact_traced_error_envelope(client: TestClient) -> None:
    project = _create_project(client, "Transition Project")
    task = _create_task(client, str(project["id"]), "Transition Task")

    moved = client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        json={"status": "todo"},
    )
    assert moved.status_code == 200
    assert moved.json()["status"] == "todo"

    # Break caught: the API bypasses the server state machine or loses trace correlation.
    rejected = client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers={"X-Request-ID": "req-invalid-transition"},
        json={"status": "done"},
    )
    assert rejected.status_code == 409
    assert rejected.json() == {
        "message": "不允许该任务状态转换",
        "code": "invalid_state_transition",
        "traceId": "req-invalid-transition",
    }
    assert rejected.headers["x-request-id"] == "req-invalid-transition"


@pytest.mark.integration
def test_dependency_creation_rejects_cycles_with_exact_traced_error_envelope(
    client: TestClient,
) -> None:
    project = _create_project(client, "Dependency Project")
    project_id = str(project["id"])
    first = _create_task(client, project_id, "Dependency One")
    second = _create_task(client, project_id, "Dependency Two")
    third = _create_task(client, project_id, "Dependency Three")

    first_edge = client.post(
        f"/api/v1/tasks/{second['id']}/dependencies",
        json={"predecessorTaskId": first["id"]},
    )
    second_edge = client.post(
        f"/api/v1/tasks/{third['id']}/dependencies",
        json={"predecessorTaskId": second["id"]},
    )
    assert first_edge.status_code == 201
    assert first_edge.json()["predecessorTaskId"] == first["id"]
    assert first_edge.json()["successorTaskId"] == second["id"]
    assert second_edge.status_code == 201

    # Break caught: a reverse path can be inserted, turning the task graph cyclic.
    cycle = client.post(
        f"/api/v1/tasks/{first['id']}/dependencies",
        headers={"X-Request-ID": "req-dependency-cycle"},
        json={"predecessorTaskId": third["id"]},
    )
    assert cycle.status_code == 409
    assert cycle.json() == {
        "message": "任务依赖不能形成环",
        "code": "dependency_cycle",
        "traceId": "req-dependency-cycle",
    }
    assert cycle.headers["x-request-id"] == "req-dependency-cycle"
