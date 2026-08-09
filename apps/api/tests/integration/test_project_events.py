import json
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from cairn_api.app import create_app
from cairn_api.auth.dependencies import get_current_identity
from cairn_api.db.session import Database, get_db
from cairn_api.organizations.models import Organization
from cairn_api.projects.models import OutboxEvent
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

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
            headers={"Origin": APP_ORIGIN},
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
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _parse_sse(body: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for raw_frame in body.split("\n\n"):
        if not raw_frame:
            continue
        fields = dict(line.split(": ", 1) for line in raw_frame.splitlines())
        frames.append(
            {
                "id": fields["id"],
                "event": fields["event"],
                "data": json.loads(fields["data"]),
            }
        )
    return frames


def _failing_session() -> Iterator[Session]:
    session = MagicMock(spec=Session)
    session.scalars.side_effect = OperationalError("SELECT secret", {}, Exception("down"))
    yield session


@pytest.mark.integration
def test_project_event_stream_reads_transactional_outbox_with_strict_bounded_resume(
    client: TestClient,
    database: Database,
) -> None:
    first_project = _create_project(client, "Event Project")
    second_project = _create_project(client, "Aggregate Decoy")
    task_response = client.post(
        f"/api/v1/projects/{first_project['id']}/tasks",
        json={"title": "Observable event task"},
    )
    assert task_response.status_code == 201
    task = task_response.json()
    transition = client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        json={"status": "todo"},
    )
    assert transition.status_code == 200

    fixed_time = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    other_org_id = uuid4()
    with database.session_factory.begin() as session:
        demo_org = session.scalar(select(Organization).where(Organization.slug == "cairn-demo"))
        assert demo_org is not None
        status_event = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.org_id == demo_org.id,
                OutboxEvent.aggregate_id == UUID(str(first_project["id"])),
                OutboxEvent.event_type == "task.status_changed",
            )
        ).one()
        assert status_event.payload == {
            "projectId": first_project["id"],
            "taskId": task["id"],
            "status": "todo",
        }
        assert status_event.published_at is None
        status_event.occurred_at = fixed_time
        successor_id = UUID(int=status_event.id.int + 1)
        session.add(
            OutboxEvent(
                id=successor_id,
                org_id=demo_org.id,
                event_type="project.same_timestamp_successor",
                aggregate_type="project",
                aggregate_id=UUID(str(first_project["id"])),
                payload={"marker": "same-timestamp-successor"},
                occurred_at=fixed_time,
            )
        )
        session.add_all(
            [
                OutboxEvent(
                    id=UUID(int=10_000 + index),
                    org_id=demo_org.id,
                    event_type="project.bulk",
                    aggregate_type="project",
                    aggregate_id=UUID(str(first_project["id"])),
                    payload={"sequence": index},
                    occurred_at=fixed_time + timedelta(seconds=index + 1),
                )
                for index in range(105)
            ]
        )
        session.add(
            OutboxEvent(
                org_id=demo_org.id,
                event_type="project.aggregate_decoy",
                aggregate_type="project",
                aggregate_id=UUID(str(second_project["id"])),
                payload={
                    "projectId": first_project["id"],
                    "marker": "hidden-other-project-aggregate",
                },
                occurred_at=fixed_time,
            )
        )
        session.add(
            OutboxEvent(
                org_id=demo_org.id,
                event_type="task.wrong_aggregate_type",
                aggregate_type="task",
                aggregate_id=UUID(str(first_project["id"])),
                payload={"marker": "hidden-wrong-aggregate-type"},
                occurred_at=fixed_time,
            )
        )
        session.add(Organization(id=other_org_id, slug="other-event-org", name="Other Org"))
        session.add(
            OutboxEvent(
                org_id=other_org_id,
                event_type="project.other_tenant",
                aggregate_type="project",
                aggregate_id=UUID(str(first_project["id"])),
                payload={"marker": "hidden-other-tenant"},
                occurred_at=fixed_time,
            )
        )
        status_event_id = status_event.id

    # Cookie-authenticated event reads are safe GETs and do not require mutation CSRF.
    del client.headers["Origin"]
    del client.headers["X-CSRF-Token"]
    with client.stream("GET", f"/api/v1/projects/{first_project['id']}/events") as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _parse_sse(body)
    assert len(frames) == 100
    status_frame = next(
        frame
        for frame in frames
        if frame["event"] == "task.status_changed"
        and frame["data"] == {
            "projectId": first_project["id"],
            "taskId": task["id"],
            "status": "todo",
        }
    )
    assert all(set(frame) == {"id", "event", "data"} for frame in frames)
    assert "hidden-other-project-aggregate" not in body
    assert "hidden-wrong-aggregate-type" not in body
    assert "hidden-other-tenant" not in body
    status_cursor = status_frame["id"]
    assert isinstance(status_cursor, str)

    with client.stream(
        "GET",
        f"/api/v1/projects/{first_project['id']}/events",
        params={"after": status_cursor},
    ) as resumed_response:
        resumed_body = "".join(resumed_response.iter_text())
    resumed_frames = _parse_sse(resumed_body)
    assert resumed_response.status_code == 200
    assert len(resumed_frames) == 100
    assert resumed_frames[0]["data"] == {"marker": "same-timestamp-successor"}
    assert status_cursor not in {frame["id"] for frame in resumed_frames}

    with database.session_factory() as session:
        persisted = session.get(OutboxEvent, status_event_id)
        assert persisted is not None
        assert persisted.published_at is None


@pytest.mark.integration
def test_project_event_database_failure_is_traced_before_streaming_starts(
    client: TestClient,
) -> None:
    identity_response = client.get("/api/v1/session")
    assert identity_response.status_code == 200
    identity = SimpleNamespace(
        organization=SimpleNamespace(
            id=UUID(identity_response.json()["organization"]["id"]),
        )
    )
    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_current_identity] = lambda: identity
    app.dependency_overrides[get_db] = _failing_session

    try:
        response = client.get(
            f"/api/v1/projects/{uuid4()}/events",
            headers={"X-Request-ID": "req-project-events-down"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.headers["x-request-id"] == "req-project-events-down"
    assert response.json() == {
        "message": "数据库暂时不可用",
        "code": "database_unavailable",
        "traceId": "req-project-events-down",
    }
    assert "SELECT secret" not in response.text
