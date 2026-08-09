import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import pytest
from cairn_api.app import create_app
from cairn_api.auth.dependencies import get_current_identity
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.db.session import Database, get_db
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects.events import (
    MAX_PROJECT_EVENT_BATCH,
    InvalidProjectEventCursor,
    ProjectEventCursor,
    load_project_events,
    serialize_project_event,
)
from cairn_api.projects.models import OutboxEvent
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)


def _identity(org_id: UUID) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(id=uuid4(), email="member@example.com", display_name="Member"),
        organization=OrganizationResponse(id=org_id, slug="event-org", name="Event Org"),
        membership=MembershipResponse(id=uuid4(), role="owner"),
        csrf_token="csrf-token",
    )


def _event(
    *,
    org_id: UUID,
    project_id: UUID,
    occurred_at: datetime,
    event_id: UUID | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        id=event_id or uuid4(),
        org_id=org_id,
        event_type="task.status_changed",
        aggregate_type="project",
        aggregate_id=project_id,
        payload={"taskId": str(uuid4()), "status": "todo"},
        occurred_at=occurred_at,
        published_at=None,
    )


def _test_client(
    *,
    identity: IdentityContextResponse,
    session: Session,
) -> TestClient:
    database = Mock(spec=Database)
    app = create_app(
        Settings(
            environment="test",
            database_url="postgresql+psycopg://unused/unused",
            csrf_secret="test-only-csrf-secret-with-at-least-32-bytes",
            auth_rate_limit_secret="test-only-auth-rate-secret-with-at-least-32-bytes",
            _env_file=None,  # pyright: ignore[reportCallIssue]
        ),
        database,
    )

    def override_db() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_identity] = lambda: identity
    return TestClient(app, raise_server_exceptions=False)


def test_project_event_cursor_round_trips_as_url_safe_opaque_value() -> None:
    # Break caught: resume IDs lose either half of the deterministic ordering tuple.
    cursor = ProjectEventCursor(occurred_at=NOW, id=uuid4())

    encoded = cursor.encode()

    assert ProjectEventCursor.decode(encoded) == cursor
    assert "=" not in encoded
    assert set(encoded) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )


@pytest.mark.parametrize(
    "value",
    [
        "not-base64!",
        base64.urlsafe_b64encode(b"not-json").decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps([NOW.isoformat(), "not-a-uuid"]).encode())
        .decode()
        .rstrip("="),
    ],
)
def test_project_event_cursor_rejects_malformed_values(value: str) -> None:
    # Break caught: untrusted cursor input reaches SQL or escapes as a server error.
    with pytest.raises(InvalidProjectEventCursor):
        ProjectEventCursor.decode(value)


def test_project_event_query_is_tenant_project_scoped_strictly_ordered_and_capped() -> None:
    # Break caught: the query omits a tenant/aggregate predicate, resumes inclusively,
    # orders by timestamp alone, or permits an unbounded initial response.
    session = MagicMock(spec=Session)
    session.scalars.return_value.all.return_value = []
    org_id = uuid4()
    project_id = uuid4()
    after = ProjectEventCursor(occurred_at=NOW, id=uuid4())

    assert load_project_events(
        session,
        org_id=org_id,
        project_id=project_id,
        after=after,
    ) == []

    statement = session.scalars.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    assert "outbox_events.org_id = %(org_id_1)s::UUID" in sql
    assert "outbox_events.aggregate_type = %(aggregate_type_1)s" in sql
    assert "outbox_events.aggregate_id = %(aggregate_id_1)s::UUID" in sql
    assert (
        "(outbox_events.occurred_at, outbox_events.id) > "
        "(%(param_1)s, %(param_2)s::UUID)" in sql
    )
    assert "ORDER BY outbox_events.occurred_at ASC, outbox_events.id ASC" in sql
    assert "LIMIT %(param_3)s" in sql
    assert compiled.params == {
        "org_id_1": org_id,
        "aggregate_type_1": "project",
        "aggregate_id_1": project_id,
        "param_1": NOW,
        "param_2": after.id,
        "param_3": MAX_PROJECT_EVENT_BATCH,
    }
    assert MAX_PROJECT_EVENT_BATCH == 100


def test_project_events_endpoint_serializes_a_bounded_batch_then_closes() -> None:
    # Break caught: SSE omits resume/event metadata, emits invalid JSON, or keeps the
    # first-slice connection open after the materialized rows are exhausted.
    session = MagicMock(spec=Session)
    org_id = uuid4()
    project_id = uuid4()
    first = _event(org_id=org_id, project_id=project_id, occurred_at=NOW)
    second = _event(
        org_id=org_id,
        project_id=project_id,
        occurred_at=NOW + timedelta(microseconds=1),
    )
    session.scalars.return_value.all.return_value = [first, second]

    with _test_client(identity=_identity(org_id), session=session) as client:
        response = client.get(f"/api/v1/projects/{project_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == (
        f"id: {ProjectEventCursor(first.occurred_at, first.id).encode()}\n"
        "event: task.status_changed\n"
        f"data: {json.dumps(first.payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"id: {ProjectEventCursor(second.occurred_at, second.id).encode()}\n"
        "event: task.status_changed\n"
        f"data: {json.dumps(second.payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def test_project_events_rejects_control_line_injection_before_streaming() -> None:
    # Break caught: an untrusted Outbox event type injects forged SSE id/event control
    # lines, including after an already serialized safe row.
    session = MagicMock(spec=Session)
    org_id = uuid4()
    project_id = uuid4()
    safe = _event(org_id=org_id, project_id=project_id, occurred_at=NOW)
    malicious = _event(
        org_id=org_id,
        project_id=project_id,
        occurred_at=NOW + timedelta(microseconds=1),
    )
    malicious.event_type = "safe\nid: forged\nevent: attacker"
    session.scalars.return_value.all.return_value = [safe, malicious]

    with _test_client(identity=_identity(org_id), session=session) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/events",
            headers={"X-Request-ID": "req-malicious-event-type"},
        )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "message": "服务器内部错误",
        "code": "internal_error",
        "traceId": "req-malicious-event-type",
    }
    assert "task.status_changed" not in response.text
    assert "forged" not in response.text
    assert "attacker" not in response.text


def test_project_event_payload_control_characters_remain_in_one_json_data_line() -> None:
    # Break caught: payload CR/LF bytes escape JSON encoding and become SSE control lines.
    event = _event(org_id=uuid4(), project_id=uuid4(), occurred_at=NOW)
    event.payload = {"note": "first\r\nid: forged\nevent: attacker"}

    frame = serialize_project_event(event)

    lines = frame.splitlines()
    assert len(lines) == 4
    assert lines[1] == "event: task.status_changed"
    assert lines[2] == r'data: {"note":"first\r\nid: forged\nevent: attacker"}'
    assert lines[3] == ""


def test_project_events_materializes_database_failure_before_stream_headers() -> None:
    # Break caught: a lazy streaming query fails after a successful status and loses
    # the request-correlated database error envelope.
    session = MagicMock(spec=Session)
    session.scalars.side_effect = OperationalError("SELECT secret", {}, Exception("down"))
    org_id = uuid4()
    project_id = uuid4()

    with _test_client(identity=_identity(org_id), session=session) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/events",
            headers={"X-Request-ID": "req-event-database-down"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "message": "数据库暂时不可用",
        "code": "database_unavailable",
        "traceId": "req-event-database-down",
    }
    assert response.headers["x-request-id"] == "req-event-database-down"
    assert "SELECT secret" not in response.text
