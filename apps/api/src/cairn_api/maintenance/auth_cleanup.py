"""Bounded deletion of obsolete authentication state."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, delete, or_, select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cairn_api.auth.models import AuthRateLimit, AuthSession
from cairn_api.auth.rate_limit import RateLimitPolicy
from cairn_api.auth.rate_limit_repository import utcnow
from cairn_api.db.session import Database
from cairn_api.settings import Settings


@dataclass(frozen=True)
class CleanupCounts:
    sessions_deleted: int = 0
    rate_limits_deleted: int = 0


def _delete_expired_session_batch(
    session_factory: sessionmaker[Session],
    *,
    now: datetime,
    batch_size: int,
) -> int:
    with session_factory() as session, session.begin():
        stale_sessions = (
            select(AuthSession.id)
            .where(
                or_(
                    AuthSession.expires_at <= now,
                    AuthSession.revoked_at.is_not(None),
                )
            )
            .order_by(AuthSession.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
            .cte("stale_auth_sessions")
        )
        deleted_rows = session.execute(
            delete(AuthSession)
            .where(AuthSession.id.in_(select(stale_sessions.c.id)))
            .returning(AuthSession.id)
        ).all()
        return len(deleted_rows)


def _delete_stale_rate_limit_batch(
    session_factory: sessionmaker[Session],
    *,
    now: datetime,
    batch_size: int,
) -> int:
    window_cutoff = now - RateLimitPolicy("email").window
    with session_factory() as session, session.begin():
        stale_keys = (
            select(AuthRateLimit.bucket_type, AuthRateLimit.key_digest)
            .where(
                or_(
                    and_(
                        AuthRateLimit.blocked_until.is_(None),
                        AuthRateLimit.window_started_at <= window_cutoff,
                    ),
                    and_(
                        AuthRateLimit.blocked_until.is_not(None),
                        AuthRateLimit.blocked_until <= now,
                    ),
                )
            )
            .order_by(AuthRateLimit.bucket_type, AuthRateLimit.key_digest)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
            .cte("stale_auth_rate_limits")
        )
        deleted_rows = session.execute(
            delete(AuthRateLimit).where(
                tuple_(AuthRateLimit.bucket_type, AuthRateLimit.key_digest).in_(
                    select(stale_keys.c.bucket_type, stale_keys.c.key_digest)
                )
            )
            .returning(AuthRateLimit.bucket_type, AuthRateLimit.key_digest)
        ).all()
        return len(deleted_rows)


def _delete_in_batches(
    delete_batch: Callable[[], int],
    *,
    batch_size: int,
) -> int:
    total = 0
    while True:
        deleted = delete_batch()
        total += deleted
        if deleted < batch_size:
            return total


def cleanup_auth_state(
    session_factory: sessionmaker[Session],
    *,
    now: Callable[[], datetime],
    batch_size: int = 1000,
) -> CleanupCounts:
    """Delete obsolete sessions and limiter buckets in independently committed batches."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    current_time = now()
    sessions_deleted = _delete_in_batches(
        lambda: _delete_expired_session_batch(
            session_factory,
            now=current_time,
            batch_size=batch_size,
        ),
        batch_size=batch_size,
    )
    rate_limits_deleted = _delete_in_batches(
        lambda: _delete_stale_rate_limit_batch(
            session_factory,
            now=current_time,
            batch_size=batch_size,
        ),
        batch_size=batch_size,
    )
    return CleanupCounts(
        sessions_deleted=sessions_deleted,
        rate_limits_deleted=rate_limits_deleted,
    )


def run_auth_cleanup() -> int:
    """Run the cleanup command and return a shell exit code."""
    settings = Settings()
    database = Database(settings.database_url)
    try:
        counts = cleanup_auth_state(database.session_factory, now=utcnow)
    except SQLAlchemyError as exc:
        print(f"auth-cleanup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        database.dispose()

    print(
        "auth-cleanup complete: "
        f"sessions_deleted={counts.sessions_deleted} "
        f"rate_limits_deleted={counts.rate_limits_deleted}"
    )
    return 0
