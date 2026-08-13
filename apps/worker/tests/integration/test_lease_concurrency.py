from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event

import pytest
from cairn_api.knowledge.models import IngestionJob, IngestionJobStatus
from cairn_worker.leases import ClaimedJob, claim_next_job
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from .conftest import seed_job


@pytest.mark.integration
def test_two_postgresql_sessions_skip_locked_and_only_one_claims_job(
    migrated_engine: Engine,
) -> None:
    """Break caught: competing workers must never receive the same durable job."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, _org_id, _project_id = seed_job(migrated_engine, now=now)
    start = Barrier(2)
    winner_claimed = Event()
    release_winner = Event()

    def compete(worker_id: str) -> ClaimedJob | None:
        with Session(migrated_engine) as session, session.begin():
            start.wait(timeout=5)
            claim = claim_next_job(session, worker_id=worker_id, now=now)
            if claim is not None:
                winner_claimed.set()
                assert release_winner.wait(timeout=5)
            return claim

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(compete, worker_id) for worker_id in ("worker-a:1", "worker-b:1")]
        assert winner_claimed.wait(timeout=5)
        release_winner.set()
        claims = [future.result(timeout=5) for future in futures]

    claimed = [claim for claim in claims if claim is not None]
    assert len(claimed) == 1 and claimed[0].job_id == job_id


@pytest.mark.integration
def test_claim_is_invisible_until_commit_then_blocks_stealing(migrated_engine: Engine) -> None:
    """Break caught: work must begin only after the lease transaction is durably committed."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, _org_id, _project_id = seed_job(migrated_engine, now=now)
    claimed = Event()
    allow_commit = Event()

    def claim_without_commit() -> ClaimedJob | None:
        with Session(migrated_engine) as session, session.begin():
            claim = claim_next_job(session, worker_id="worker-a:1", now=now)
            claimed.set()
            assert allow_commit.wait(timeout=5)
            return claim

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(claim_without_commit)
        assert claimed.wait(timeout=5)
        with Session(migrated_engine) as observer:
            job = observer.get(IngestionJob, job_id)
            assert job is not None and job.status == IngestionJobStatus.QUEUED
        allow_commit.set()
        assert future.result(timeout=5) is not None

    with Session(migrated_engine) as observer, observer.begin():
        job = observer.get(IngestionJob, job_id)
        assert job is not None and job.status == IngestionJobStatus.RUNNING
        assert claim_next_job(observer, worker_id="worker-b:1", now=now) is None
