import math
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from cairn_api.errors import ApiProblem
from cairn_api.knowledge.models import SearchRateLimitBucket

SearchRateLimitSubject = Literal["user", "organization"]


def minute_window(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError("search rate-limit timestamps must be timezone-aware")
    started_at = now.astimezone(UTC).replace(second=0, microsecond=0)
    return started_at, started_at + timedelta(minutes=1)


def _rate_limited(window_expires_at: datetime, now: datetime) -> ApiProblem:
    retry_after = max(1, math.ceil((window_expires_at - now).total_seconds()))
    return ApiProblem(
        status_code=429,
        code="search_rate_limited",
        message="搜索请求过于频繁",
        headers={"Retry-After": str(retry_after)},
    )


class SearchRateLimiter:
    def __init__(self, session: Session, *, user_limit: int, org_limit: int) -> None:
        if user_limit < 1 or org_limit < 1:
            raise ValueError("search rate limits must be positive")
        self._session = session
        self._user_limit = user_limit
        self._org_limit = org_limit

    def _reserve_bucket(
        self,
        *,
        org_id: UUID,
        subject_type: SearchRateLimitSubject,
        subject_id: UUID,
        limit: int,
        window_started_at: datetime,
        window_expires_at: datetime,
    ) -> bool:
        table = SearchRateLimitBucket.__table__
        statement = (
            insert(SearchRateLimitBucket)
            .values(
                org_id=org_id,
                subject_type=subject_type,
                subject_id=subject_id,
                window_started_at=window_started_at,
                window_expires_at=window_expires_at,
                request_count=1,
            )
            .on_conflict_do_update(
                constraint="uq_search_rate_limit_buckets_window",
                set_={"request_count": table.c.request_count + 1},
                where=table.c.request_count < limit,
            )
            .returning(table.c.request_count)
        )
        return self._session.scalar(statement) is not None

    def reserve(self, *, org_id: UUID, user_id: UUID, now: datetime) -> None:
        window_started_at, window_expires_at = minute_window(now)
        if not self._reserve_bucket(
            org_id=org_id,
            subject_type="user",
            subject_id=user_id,
            limit=self._user_limit,
            window_started_at=window_started_at,
            window_expires_at=window_expires_at,
        ):
            raise _rate_limited(window_expires_at, now)
        if not self._reserve_bucket(
            org_id=org_id,
            subject_type="organization",
            subject_id=org_id,
            limit=self._org_limit,
            window_started_at=window_started_at,
            window_expires_at=window_expires_at,
        ):
            raise _rate_limited(window_expires_at, now)


__all__ = ["SearchRateLimiter", "minute_window"]
