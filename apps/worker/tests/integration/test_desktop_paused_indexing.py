from datetime import UTC, datetime

import pytest
from cairn_api.knowledge.models import IngestionJob, IngestionJobAttempt, JobKind
from cairn_worker.leases import ClaimedJob, finish_job
from cairn_worker.runner import REQUIRED_JOB_KINDS, Heartbeat, run_once
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from .conftest import seed_job
from .test_leases import _NoopHeartbeat  # pyright: ignore[reportPrivateUsage]


@pytest.mark.integration
def test_paused_indexing_keeps_queued_job_untouched_and_processes_archive(
    migrated_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    index_id, _, _ = seed_job(migrated_engine, job_kind=JobKind.INDEX_RESOURCE_VERSION, now=now)
    archive_id, _, _ = seed_job(migrated_engine, job_kind=JobKind.EXPAND_ARCHIVE, now=now)
    processed: list[JobKind] = []

    def handler(session: Session, claim: ClaimedJob, _heartbeat: Heartbeat) -> None:
        processed.append(claim.job_kind)
        finish_job(session, claim=claim, now=now)

    def run() -> bool:
        return run_once(
            session_factory=sessionmaker(migrated_engine),
            worker_id="desktop:paused",
            handlers={kind: handler for kind in REQUIRED_JOB_KINDS},
            heartbeat_factory=_NoopHeartbeat,
            now=lambda: now,
            indexing_enabled=False,
        )

    assert run() is True
    assert run() is False
    assert processed == [JobKind.EXPAND_ARCHIVE]
    with Session(migrated_engine) as session:
        index = session.get(IngestionJob, index_id)
        archive = session.get(IngestionJob, archive_id)
        assert index is not None and index.status == "queued" and index.last_error_code is None
        assert archive is not None and archive.status == "completed"
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionJobAttempt)
                .where(IngestionJobAttempt.job_id == index_id)
            )
            == 0
        )
