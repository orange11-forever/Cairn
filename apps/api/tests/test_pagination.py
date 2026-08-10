import base64
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from cairn_api.errors import ApiProblem
from cairn_api.pagination import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    load_cursor_page,
)


def test_shared_cursor_round_trips_aware_timestamp_and_uuid() -> None:
    timestamp = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)
    item_id = UUID("00000000-0000-4000-8000-000000000123")

    cursor = encode_cursor(timestamp, item_id)

    padding = "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    assert payload == {
        "createdAt": "2026-08-10T09:30:00+00:00",
        "id": "00000000-0000-4000-8000-000000000123",
    }
    assert decode_cursor(cursor) == (timestamp, item_id)


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-valid-cursor",
        "W10",  # []
        "e30",  # {}
        "eyJjcmVhdGVkQXQiOjEsImlkIjoyfQ",  # numeric fields
        "eyJjcmVhdGVkQXQiOiIyMDI2LTA4LTEwVDA5OjMwOjAwIiwiaWQiOiIwMDAwMDAwMC0wMDAwLTQwMDAtODAwMC0wMDAwMDAwMDAxMjMifQ",
    ],
)
def test_shared_cursor_rejects_malformed_or_naive_values(cursor: str) -> None:
    # Break caught: malformed or timezone-less cursors silently alter page boundaries.
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)


def test_shared_cursor_rejects_naive_timestamps_at_encoding_boundary() -> None:
    # Break caught: the encoder emits an ambiguous local timestamp.
    with pytest.raises(ValueError, match="timezone"):
        encode_cursor(
            datetime(2026, 8, 10, 9, 30),  # noqa: DTZ001 - intentionally naive input
            UUID("00000000-0000-4000-8000-000000000123"),
        )


def test_load_cursor_page_translates_only_invalid_cursor_errors() -> None:
    # Break caught: an invalid repository cursor escapes as an unhandled exception.
    with pytest.raises(ApiProblem) as exc_info:
        load_cursor_page(lambda: decode_cursor("not-a-valid-cursor"))

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "invalid_cursor"
    assert exc_info.value.message == "分页游标无效"
