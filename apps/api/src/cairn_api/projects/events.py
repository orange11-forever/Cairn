import base64
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select, tuple_
from sqlalchemy.orm import Session

from cairn_api.db.errors import DATABASE_UNAVAILABLE_ERRORS
from cairn_api.errors import ApiProblem
from cairn_api.projects.models import OutboxEvent

MAX_PROJECT_EVENT_BATCH = 100
PROJECT_EVENT_TYPE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
class InvalidProjectEventCursor(ValueError):
    pass


@dataclass(frozen=True)
class ProjectEventCursor:
    occurred_at: datetime
    id: UUID

    def encode(self) -> str:
        if self.occurred_at.tzinfo is None:
            raise ValueError("project event cursor timestamp must be timezone-aware")
        timestamp = self.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        payload = json.dumps(
            {"occurredAt": timestamp, "id": str(self.id)},
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "ProjectEventCursor":
        try:
            padding = "=" * (-len(value) % 4)
            decoded = base64.b64decode(
                value + padding,
                altchars=b"-_",
                validate=True,
            )
            decoded_payload = cast(object, json.loads(decoded))
            if not isinstance(decoded_payload, dict):
                raise TypeError("unexpected cursor shape")
            payload = cast(dict[object, object], decoded_payload)
            if len(payload) != 2:
                raise ValueError("unexpected cursor shape")
            occurred_at_value = payload.get("occurredAt")
            event_id_value = payload.get("id")
            if not isinstance(occurred_at_value, str) or not isinstance(event_id_value, str):
                raise TypeError("unexpected cursor values")
            occurred_at = datetime.fromisoformat(occurred_at_value)
            event_id = UUID(event_id_value)
            if occurred_at.tzinfo is None:
                raise ValueError("cursor timestamp must be timezone-aware")
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidProjectEventCursor("invalid project event cursor") from exc
        return cls(occurred_at=occurred_at, id=event_id)


def _project_event_statement(
    *,
    org_id: UUID,
    project_id: UUID,
    after: ProjectEventCursor | None,
) -> Select[tuple[OutboxEvent]]:
    statement = select(OutboxEvent).where(
        OutboxEvent.org_id == org_id,
        OutboxEvent.aggregate_type == "project",
        OutboxEvent.aggregate_id == project_id,
    )
    if after is not None:
        statement = statement.where(
            tuple_(OutboxEvent.occurred_at, OutboxEvent.id)
            > (after.occurred_at, after.id)
        )
    return statement.order_by(
        OutboxEvent.occurred_at.asc(),
        OutboxEvent.id.asc(),
    ).limit(MAX_PROJECT_EVENT_BATCH)


def load_project_events(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    after: ProjectEventCursor | None,
) -> list[OutboxEvent]:
    statement = _project_event_statement(
        org_id=org_id,
        project_id=project_id,
        after=after,
    )
    return list(session.scalars(statement).all())


def serialize_project_event(event: OutboxEvent) -> str:
    if PROJECT_EVENT_TYPE_PATTERN.fullmatch(event.event_type) is None:
        raise ValueError("invalid outbox event type")
    event_id = ProjectEventCursor(event.occurred_at, event.id).encode()
    data = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event.event_type}\ndata: {data}\n\n"


def materialize_project_event_frames(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    after: str | None,
) -> tuple[str, ...]:
    try:
        cursor = ProjectEventCursor.decode(after) if after is not None else None
    except InvalidProjectEventCursor as exc:
        raise ApiProblem(
            status_code=422,
            code="invalid_cursor",
            message="事件游标无效",
        ) from exc

    try:
        events = load_project_events(
            session,
            org_id=org_id,
            project_id=project_id,
            after=cursor,
        )
    except DATABASE_UNAVAILABLE_ERRORS as exc:
        raise ApiProblem(
            status_code=503,
            code="database_unavailable",
            message="数据库暂时不可用",
        ) from exc
    return tuple(serialize_project_event(event) for event in events)


__all__ = [
    "MAX_PROJECT_EVENT_BATCH",
    "InvalidProjectEventCursor",
    "ProjectEventCursor",
    "load_project_events",
    "materialize_project_event_frames",
    "serialize_project_event",
]
