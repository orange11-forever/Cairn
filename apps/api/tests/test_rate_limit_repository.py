from datetime import UTC, datetime
from unittest.mock import MagicMock

from cairn_api.auth.models import AuthRateLimit
from cairn_api.auth.rate_limit_repository import BucketKey, RateLimitRepository
from sqlalchemy.dialects import postgresql


def test_lock_buckets_orders_email_before_ip_and_locks_rows() -> None:
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    now = datetime(2026, 8, 5, tzinfo=UTC)

    RateLimitRepository.lock_buckets(
        session,
        [BucketKey("ip", b"i" * 32), BucketKey("email", b"e" * 32)],
        now=now,
    )

    statement = session.scalars.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert "CASE" in sql
    assert statement._order_by_clauses


def test_rate_limit_model_uses_failure_count_contract_name() -> None:
    assert "failure_count" in AuthRateLimit.__table__.c
    assert "count" not in AuthRateLimit.__table__.c


def test_record_failure_uses_postgresql_upsert() -> None:
    session = MagicMock()
    session.execute.return_value.one.return_value = (
        "email",
        b"e" * 32,
        1,
        datetime(2026, 8, 5, tzinfo=UTC),
        None,
    )
    key = BucketKey("email", b"e" * 32)

    RateLimitRepository.record_failure(session, key, now=datetime(2026, 8, 5, tzinfo=UTC))

    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in sql
    assert "RETURNING" in sql
    assert "failure_count" in sql
    assert "auth_rate_limits" in sql
