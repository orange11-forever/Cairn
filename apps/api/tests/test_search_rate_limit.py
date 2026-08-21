from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.search_rate_limit import SearchRateLimiter, minute_window
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


def test_minute_window_uses_utc_wall_clock_boundary() -> None:
    """Break caught: rolling or local-time windows make Retry-After nondeterministic."""
    now = datetime(2026, 8, 21, 7, 12, 34, 123456, tzinfo=UTC)
    assert minute_window(now) == (
        datetime(2026, 8, 21, 7, 12, tzinfo=UTC),
        datetime(2026, 8, 21, 7, 13, tzinfo=UTC),
    )


def test_org_rejection_raises_stable_429_with_retry_after() -> None:
    """Break caught: organization exhaustion is ignored or omits the protocol retry deadline."""
    session = MagicMock(spec=Session)
    limiter = SearchRateLimiter(session, user_limit=2, org_limit=3)
    limiter._reserve_bucket = MagicMock(side_effect=[True, False])  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ApiProblem) as raised:
        limiter.reserve(
            org_id=uuid4(),
            user_id=uuid4(),
            now=datetime(2026, 8, 21, 7, 12, 59, 100000, tzinfo=UTC),
        )

    assert raised.value.status_code == 429
    assert raised.value.code == "search_rate_limited"
    assert raised.value.headers == {"Retry-After": "1"}


def test_rate_limiter_rejects_disabled_or_nonpositive_buckets() -> None:
    """Break caught: deployment configuration silently disables a required search bucket."""
    session = MagicMock(spec=Session)
    with pytest.raises(ValueError):
        SearchRateLimiter(session, user_limit=0, org_limit=1)
    with pytest.raises(ValueError):
        SearchRateLimiter(session, user_limit=1, org_limit=0)


def test_bucket_reservation_is_a_conditional_atomic_postgresql_upsert() -> None:
    """Break caught: read-then-write reservations lose increments under two-session contention."""
    session = MagicMock(spec=Session)
    session.scalar.return_value = 1
    limiter = SearchRateLimiter(session, user_limit=30, org_limit=300)
    start = datetime(2026, 8, 21, 7, 12, tzinfo=UTC)

    assert limiter._reserve_bucket(  # pyright: ignore[reportPrivateUsage]
        org_id=uuid4(),
        subject_type="user",
        subject_id=uuid4(),
        limit=30,
        window_started_at=start,
        window_expires_at=start.replace(minute=13),
    )

    statement = session.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "insert into search_rate_limit_buckets" in sql
    assert "on conflict on constraint uq_search_rate_limit_buckets_window do update" in sql
    assert "request_count +" in sql
    assert "where search_rate_limit_buckets.request_count <" in sql
    assert "returning search_rate_limit_buckets.request_count" in sql
