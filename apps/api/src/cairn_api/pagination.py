import base64
import json
from collections.abc import Callable
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import InstrumentedAttribute, Session

from cairn_api.errors import ApiProblem


class InvalidCursorError(ValueError):
    """Raised when an opaque pagination cursor cannot be decoded."""


def encode_cursor(timestamp: datetime, item_id: UUID) -> str:
    if timestamp.tzinfo is None:
        raise ValueError("cursor timestamp must include a timezone")
    raw = json.dumps(
        {"createdAt": timestamp.isoformat(), "id": str(item_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload: object = json.loads(decoded)
        if not isinstance(payload, dict):
            raise TypeError("cursor payload must be an object")
        typed_payload = cast(dict[str, object], payload)
        timestamp_value = typed_payload.get("createdAt")
        item_id_value = typed_payload.get("id")
        if not isinstance(timestamp_value, str) or not isinstance(item_id_value, str):
            raise TypeError("cursor fields must be strings")
        timestamp = datetime.fromisoformat(timestamp_value)
        item_id = UUID(item_id_value)
        if timestamp.tzinfo is None:
            raise ValueError("cursor timestamp must include a timezone")
        return timestamp, item_id
    except (TypeError, ValueError) as exc:
        raise InvalidCursorError("pagination cursor is invalid") from exc


def page_by_timestamp[Item](
    session: Session,
    statement: Select[tuple[Item]],
    *,
    timestamp_column: InstrumentedAttribute[datetime],
    id_column: InstrumentedAttribute[UUID],
    cursor: str | None,
    limit: int,
) -> tuple[list[Item], str | None]:
    if cursor is not None:
        cursor_timestamp, cursor_id = decode_cursor(cursor)
        statement = statement.where(
            or_(
                timestamp_column > cursor_timestamp,
                and_(timestamp_column == cursor_timestamp, id_column > cursor_id),
            )
        )
    bounded = statement.order_by(timestamp_column, id_column).limit(limit + 1)
    rows = list(session.scalars(bounded).all())
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit and items:
        last = items[-1]
        next_cursor = encode_cursor(
            cast(datetime, getattr(last, timestamp_column.key)),
            cast(UUID, getattr(last, id_column.key)),
        )
    return items, next_cursor


def load_cursor_page[Page](load: Callable[[], Page]) -> Page:
    try:
        return load()
    except InvalidCursorError as exc:
        raise ApiProblem(
            status_code=422,
            code="invalid_cursor",
            message="分页游标无效",
        ) from exc


__all__ = [
    "InvalidCursorError",
    "decode_cursor",
    "encode_cursor",
    "load_cursor_page",
    "page_by_timestamp",
]
