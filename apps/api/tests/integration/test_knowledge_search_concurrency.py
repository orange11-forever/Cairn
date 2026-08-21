from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.models import SearchRateLimitBucket
from cairn_api.knowledge.search_rate_limit import SearchRateLimiter
from sqlalchemy import func, select

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_search import SearchEmbedding


@pytest.mark.integration
def test_configured_user_limit_returns_429_and_retry_after_on_next_reservation(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    with knowledge_client(
        knowledge_settings(
            test_database_url,
            search_user_limit_per_minute=2,
            search_org_limit_per_minute=10,
        ),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        responses = [
            client.post(
                f"/api/v1/projects/{project_id}/knowledge/search",
                json={"query": "rate limit query"},
            )
            for _ in range(3)
        ]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[-1].json()["code"] == "search_rate_limited"
    assert int(responses[-1].headers["retry-after"]) >= 1


@pytest.mark.integration
def test_org_rejection_rolls_back_the_user_bucket_increment(
    database: Database,
    test_database_url: str,
) -> None:
    first = seed_actor(database, MembershipRole.MEMBER)
    second = seed_actor(database, MembershipRole.MEMBER, org_id=first.organization_id)
    project_id = seed_project(database, first, permission="read")
    with database.session_factory.begin() as session:
        session.add(
            ResourceAclEntry(
                org_id=first.organization_id,
                resource_type="project",
                resource_id=project_id,
                principal_type="user",
                principal_id=str(second.user_id),
                permission="read",
                granted_by_type="system",
            )
        )
    settings = knowledge_settings(
        test_database_url,
        search_user_limit_per_minute=5,
        search_org_limit_per_minute=1,
    )
    with knowledge_client(
        settings, database, first, MemoryObjectStore(), SearchEmbedding()
    ) as client:
        accepted = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "organization quota"},
        )
    with knowledge_client(
        settings, database, second, MemoryObjectStore(), SearchEmbedding()
    ) as client:
        rejected = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "organization quota"},
        )

    assert accepted.status_code == 200
    assert rejected.status_code == 429
    with database.session_factory() as session:
        second_user_count = session.scalar(
            select(func.count())
            .select_from(SearchRateLimitBucket)
            .where(
                SearchRateLimitBucket.subject_type == "user",
                SearchRateLimitBucket.subject_id == second.user_id,
            )
        )
        assert second_user_count == 0


@pytest.mark.integration
def test_two_session_contention_has_no_lost_rate_limit_increments(database: Database) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    now = datetime(2026, 8, 21, 8, 12, 20, tzinfo=UTC)
    barrier = Barrier(2)

    def reserve() -> None:
        with database.session_factory.begin() as session:
            barrier.wait()
            SearchRateLimiter(session, user_limit=30, org_limit=300).reserve(
                org_id=actor.organization_id,
                user_id=actor.user_id,
                now=now,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    with database.session_factory() as session:
        rows = session.execute(
            select(
                SearchRateLimitBucket.subject_type,
                SearchRateLimitBucket.request_count,
            ).where(SearchRateLimitBucket.org_id == actor.organization_id)
        ).all()
        counts = {subject_type: request_count for subject_type, request_count in rows}
    assert counts == {"user": 2, "organization": 2}


@pytest.mark.integration
def test_rate_limit_minute_rollover_creates_a_fresh_window(database: Database) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    times = [
        datetime(2026, 8, 21, 8, 12, 59, tzinfo=UTC),
        datetime(2026, 8, 21, 8, 13, 0, tzinfo=UTC),
    ]
    for now in times:
        with database.session_factory.begin() as session:
            SearchRateLimiter(session, user_limit=1, org_limit=1).reserve(
                org_id=actor.organization_id,
                user_id=actor.user_id,
                now=now,
            )
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SearchRateLimitBucket)
                .where(SearchRateLimitBucket.org_id == actor.organization_id)
            )
            == 4
        )


@pytest.mark.integration
def test_default_user_and_organization_threshold_boundaries(database: Database) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    now = datetime(2026, 8, 21, 8, 14, tzinfo=UTC)
    limiter: SearchRateLimiter
    with database.session_factory.begin() as session:
        limiter = SearchRateLimiter(session, user_limit=30, org_limit=300)
        for _ in range(30):
            limiter.reserve(org_id=actor.organization_id, user_id=actor.user_id, now=now)
    with pytest.raises(ApiProblem) as user_rejected, database.session_factory.begin() as session:
        SearchRateLimiter(session, user_limit=30, org_limit=300).reserve(
            org_id=actor.organization_id,
            user_id=actor.user_id,
            now=now,
        )
    assert user_rejected.value.code == "search_rate_limited"

    with database.session_factory.begin() as session:
        limiter = SearchRateLimiter(session, user_limit=30, org_limit=300)
        for _ in range(270):
            limiter.reserve(org_id=actor.organization_id, user_id=uuid4(), now=now)
    with pytest.raises(ApiProblem) as org_rejected, database.session_factory.begin() as session:
        SearchRateLimiter(session, user_limit=30, org_limit=300).reserve(
            org_id=actor.organization_id,
            user_id=uuid4(),
            now=now,
        )
    assert org_rejected.value.code == "search_rate_limited"
