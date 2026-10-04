"""Project SSE resume must follow commit visibility across transactions."""

import json
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from uuid import UUID

import pytest
from cairn_api.app import create_app
from cairn_api.db.session import Database
from cairn_api.organizations.models import Organization
from cairn_api.projects.models import OutboxEvent, Project
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

APP_ORIGIN = "http://localhost:5500"


@pytest.fixture()
def client(
    database: Database,
    migrated_engine: Engine,
    test_database_url: str,
) -> Generator[TestClient, None, None]:
    del migrated_engine
    settings = Settings(
        environment="test",
        database_url=test_database_url,
        app_url=APP_ORIGIN,
        cors_origins=[APP_ORIGIN],
        csrf_secret="test-only-csrf-secret-with-at-least-32-bytes",
        auth_rate_limit_secret="test-only-auth-rate-limit-secret-with-at-least-32-bytes",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    seed_demo_identity(settings, database)
    with TestClient(create_app(settings, database)) as test_client:
        login = test_client.post(
            "/api/v1/login",
            headers={"Origin": APP_ORIGIN},
            json={"email": "demo@cairn.dev", "password": "cairn-demo-2026"},
        )
        assert login.status_code == 200
        test_client.headers.update(
            {"Origin": APP_ORIGIN, "X-CSRF-Token": login.json()["csrfToken"]}
        )
        yield test_client


def _project(client: TestClient, database: Database) -> tuple[UUID, UUID]:
    created = client.post("/api/v1/projects", json={"name": "Commit ordered SSE"})
    assert created.status_code == 201
    with database.session_factory() as session:
        org_id = session.scalar(select(Organization.id).where(Organization.slug == "cairn-demo"))
    assert org_id is not None
    return org_id, UUID(created.json()["id"])


def _event(session: Session, org_id: UUID, project_id: UUID, marker: str) -> OutboxEvent:
    event = OutboxEvent(
        org_id=org_id,
        aggregate_type="project",
        aggregate_id=project_id,
        event_type="test.commit_order",
        payload={"marker": marker},
    )
    session.add(event)
    session.flush()
    return event


def _frames(client: TestClient, project_id: UUID, after: str | None = None) -> list[dict[str, object]]:
    response = client.get(
        f"/api/v1/projects/{project_id}/events",
        params={"after": after} if after is not None else None,
        headers={"Origin": APP_ORIGIN, "X-Request-ID": "req-project-event-ordering"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-request-id"] == "req-project-event-ordering"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["access-control-allow-origin"] == APP_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert {
        value.strip().lower()
        for value in response.headers["access-control-expose-headers"].split(",")
    } == {"x-request-id", "retry-after"}
    assert "Origin" in response.headers["vary"]
    for header in ("set-cookie", "allow", "retry-after"):
        assert header not in response.headers
    return [
        {
            key: json.loads(value) if key == "data" else value
            for key, value in (line.split(": ", 1) for line in raw.splitlines())
        }
        for raw in response.text.split("\n\n")
        if raw
    ]


@pytest.mark.integration
@pytest.mark.parametrize("slow_insert_before_fast_commit", [True, False])
def test_late_commit_event_remains_reachable_after_faster_event_cursor(
    client: TestClient,
    database: Database,
    slow_insert_before_fast_commit: bool,
) -> None:
    org_id, project_id = _project(client, database)
    with database.session_factory() as slow, slow.begin():
        slow.execute(text("SET LOCAL lock_timeout = '3s'"))
        slow.execute(text("SET LOCAL statement_timeout = '5s'"))
        slow.execute(text("SELECT 1"))
        if slow_insert_before_fast_commit:
            _event(slow, org_id, project_id, "slow")

        with database.session_factory.begin() as fast:
            fast.execute(text("SET LOCAL lock_timeout = '3s'"))
            fast.execute(text("SET LOCAL statement_timeout = '5s'"))
            _event(fast, org_id, project_id, "fast")

        fast_frames = _frames(client, project_id)
        fast_frame = next(frame for frame in fast_frames if frame["data"] == {"marker": "fast"})
        assert all(frame["data"] != {"marker": "slow"} for frame in fast_frames)
        if not slow_insert_before_fast_commit:
            _event(slow, org_id, project_id, "slow")

    resumed = _frames(client, project_id, str(fast_frame["id"]))
    assert [frame["data"] for frame in resumed] == [{"marker": "slow"}]


@pytest.mark.integration
def test_event_time_is_finalized_at_commit_and_rollback_stays_invisible(
    client: TestClient, database: Database
) -> None:
    org_id, project_id = _project(client, database)
    with database.session_factory() as session:
        with session.begin():
            pending = _event(session, org_id, project_id, "rollback")
            assert pending.occurred_at is not None
            assert all(frame["data"] != {"marker": "rollback"} for frame in _frames(client, project_id))
            session.rollback()
        with session.begin():
            committed = _event(session, org_id, project_id, "commit")
            inserted_at = committed.occurred_at

    with database.session_factory() as session:
        persisted = session.get(OutboxEvent, committed.id)
    assert persisted is not None
    assert inserted_at is not None and persisted.occurred_at > inserted_at
    assert [frame["data"] for frame in _frames(client, project_id) if frame["event"] == "test.commit_order"] == [
        {"marker": "commit"}
    ]


@pytest.mark.integration
def test_multiple_events_in_one_transaction_get_strictly_increasing_times(
    client: TestClient, database: Database
) -> None:
    org_id, project_id = _project(client, database)
    with database.session_factory.begin() as session:
        events = [_event(session, org_id, project_id, marker) for marker in ("one", "two", "three")]

    with database.session_factory() as session:
        persisted = [session.get(OutboxEvent, event.id) for event in events]
    assert all(event is not None for event in persisted)
    times = [event.occurred_at for event in persisted if event is not None]
    assert times == sorted(set(times))
    assert [frame["data"] for frame in _frames(client, project_id) if frame["event"] == "test.commit_order"] == [
        {"marker": "one"},
        {"marker": "two"},
        {"marker": "three"},
    ]


@pytest.mark.integration
def test_non_project_event_keeps_explicit_time_and_payload_after_commit(
    client: TestClient, database: Database
) -> None:
    org_id, _project_id = _project(client, database)
    explicit_time = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    payload = {"marker": "unmodified", "number": 3}
    with database.session_factory.begin() as session:
        event = OutboxEvent(
            org_id=org_id,
            aggregate_type="organization",
            aggregate_id=org_id,
            event_type="organization.test",
            payload=payload,
            occurred_at=explicit_time,
        )
        session.add(event)
        session.flush()

    with database.session_factory() as session:
        persisted = session.get(OutboxEvent, event.id)
    assert persisted is not None
    assert persisted.occurred_at == explicit_time
    assert persisted.payload == payload
    assert persisted.event_type == "organization.test"
    assert persisted.published_at is None


@pytest.mark.integration
def test_opposite_project_insert_order_commits_without_stream_lock_cycle(
    client: TestClient, database: Database
) -> None:
    org_id, first_project = _project(client, database)
    second_project = UUID(client.post("/api/v1/projects", json={"name": "Other stream"}).json()["id"])
    ready = Barrier(2)

    def write_two(projects: tuple[UUID, UUID], marker: str) -> None:
        with database.session_factory.begin() as session:
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            session.execute(text("SET LOCAL statement_timeout = '5s'"))
            for project_id in projects:
                _event(session, org_id, project_id, marker)
            ready.wait(timeout=10)

    with ThreadPoolExecutor(max_workers=2) as executor:
        forward = executor.submit(write_two, (first_project, second_project), "forward")
        reverse = executor.submit(write_two, (second_project, first_project), "reverse")
        forward.result(timeout=15)
        reverse.result(timeout=15)

    for project_id in (first_project, second_project):
        markers = [
            frame["data"]
            for frame in _frames(client, project_id)
            if frame["event"] == "test.commit_order"
        ]
        assert markers in ([{"marker": "forward"}, {"marker": "reverse"}], [{"marker": "reverse"}, {"marker": "forward"}])


@pytest.mark.integration
def test_event_flush_then_domain_lock_does_not_invert_stream_lock(
    client: TestClient, database: Database
) -> None:
    org_id, project_id = _project(client, database)
    a_inserted = Event()
    b_locked = Event()

    def event_then_project_lock() -> None:
        with database.session_factory.begin() as session:
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            session.execute(text("SET LOCAL statement_timeout = '5s'"))
            _event(session, org_id, project_id, "event-first")
            a_inserted.set()
            assert b_locked.wait(timeout=10)
            assert session.scalar(
                select(Project.id).where(Project.id == project_id).with_for_update()
            ) == project_id

    def project_lock_then_event() -> None:
        assert a_inserted.wait(timeout=10)
        with database.session_factory.begin() as session:
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            session.execute(text("SET LOCAL statement_timeout = '5s'"))
            assert session.scalar(
                select(Project.id).where(Project.id == project_id).with_for_update()
            ) == project_id
            b_locked.set()
            _event(session, org_id, project_id, "project-first")

    with ThreadPoolExecutor(max_workers=2) as executor:
        event_first = executor.submit(event_then_project_lock)
        project_first = executor.submit(project_lock_then_event)
        event_first.result(timeout=15)
        project_first.result(timeout=15)

    markers = [frame["data"] for frame in _frames(client, project_id) if frame["event"] == "test.commit_order"]
    assert markers == [{"marker": "project-first"}, {"marker": "event-first"}]
