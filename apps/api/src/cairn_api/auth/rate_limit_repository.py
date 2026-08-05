"""PostgreSQL persistence for login failure buckets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import and_, case, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from cairn_api.auth.models import AuthRateLimit
from cairn_api.auth.rate_limit import BucketType, RateLimitPolicy


@dataclass(frozen=True)
class BucketKey:
    bucket_type: BucketType
    key_digest: bytes


@dataclass(frozen=True)
class BucketState:
    bucket_type: BucketType
    key_digest: bytes
    failure_count: int
    window_started_at: datetime
    blocked_until: datetime | None


def _policy(bucket_type: BucketType) -> RateLimitPolicy:
    return RateLimitPolicy(bucket_type)


def _state(row: AuthRateLimit) -> BucketState:
    return BucketState(
        bucket_type=cast(BucketType, row.bucket_type),
        key_digest=row.key_digest,
        failure_count=row.failure_count,
        window_started_at=row.window_started_at,
        blocked_until=row.blocked_until,
    )


class RateLimitRepository:
    @staticmethod
    def lock_buckets(
        session: Session,
        keys: list[BucketKey] | tuple[BucketKey, ...],
        *,
        now: datetime,
    ) -> dict[BucketKey, BucketState]:
        unique_keys = sorted(
            set(keys),
            key=lambda key: (0 if key.bucket_type == "email" else 1, key.key_digest),
        )
        if not unique_keys:
            return {}
        values = [(key.bucket_type, key.key_digest) for key in unique_keys]
        statement = (
            select(AuthRateLimit)
            .where(tuple_(AuthRateLimit.bucket_type, AuthRateLimit.key_digest).in_(values))
            .order_by(
                case((AuthRateLimit.bucket_type == "email", 0), else_=1),
                AuthRateLimit.key_digest,
            )
            .with_for_update()
        )
        rows = session.scalars(statement).all()
        return {BucketKey(cast(BucketType, row.bucket_type), row.key_digest): _state(row) for row in rows}

    @staticmethod
    def record_failure(session: Session, key: BucketKey, *, now: datetime) -> BucketState:
        policy = _policy(key.bucket_type)
        table = AuthRateLimit.__table__
        statement = insert(AuthRateLimit).values(
            bucket_type=key.bucket_type,
            key_digest=key.key_digest,
            failure_count=1,
            window_started_at=now,
            blocked_until=None,
        )
        existing_window = table.c.window_started_at > now - policy.window
        active_block = table.c.blocked_until > now
        accepts_failure = or_(table.c.blocked_until.is_(None), table.c.blocked_until <= now)
        next_count = case(
            (active_block, table.c.failure_count),
            (and_(existing_window, accepts_failure), table.c.failure_count + 1),
            else_=1,
        )
        next_window = case(
            (active_block, table.c.window_started_at),
            (and_(existing_window, accepts_failure), table.c.window_started_at),
            else_=now,
        )
        next_block = case(
            (active_block, table.c.blocked_until),
            (
                and_(
                    existing_window,
                    accepts_failure,
                    table.c.failure_count + 1 >= policy.threshold,
                ),
                now + policy.block,
            ),
            else_=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.bucket_type, table.c.key_digest],
            set_={
                "failure_count": next_count,
                "window_started_at": next_window,
                "blocked_until": next_block,
            },
        )
        session.execute(statement)
        row = session.scalar(
            select(AuthRateLimit).where(
                AuthRateLimit.bucket_type == key.bucket_type,
                AuthRateLimit.key_digest == key.key_digest,
            )
        )
        if row is None:
            raise SQLAlchemyError("rate-limit bucket upsert returned no row")
        return _state(row)

    @staticmethod
    def clear_email_bucket(session: Session, key_digest: bytes) -> None:
        from sqlalchemy import delete

        session.execute(
            delete(AuthRateLimit).where(
                AuthRateLimit.bucket_type == "email",
                AuthRateLimit.key_digest == key_digest,
            )
        )

    @staticmethod
    def active_block_deadlines(
        buckets: dict[BucketKey, BucketState], *, now: datetime
    ) -> list[datetime]:
        return [
            state.blocked_until
            for state in buckets.values()
            if state.blocked_until is not None and state.blocked_until > now
        ]

    @staticmethod
    def rate_limit_is_active(state: BucketState | None, *, now: datetime) -> bool:
        return state is not None and state.blocked_until is not None and state.blocked_until > now


def utcnow() -> datetime:
    return datetime.now(UTC)
