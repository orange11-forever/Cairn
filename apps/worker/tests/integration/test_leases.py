import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Self
from uuid import uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.knowledge.models import (
    IngestionBatch,
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobAttemptStatus,
    IngestionJobStatus,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceSourceType,
    ResourceVersionStatus,
)
from cairn_api.projects.models import OutboxEvent
from cairn_worker.errors import WorkerFailure
from cairn_worker.leases import ClaimedJob, claim_next_job, fail_job, finish_job, renew_lease
from cairn_worker.runner import REQUIRED_JOB_KINDS, Heartbeat, run_once
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from .conftest import seed_job


class _NoopHeartbeat:
    def __init__(self, *_: object) -> None:
        return None

    def __enter__(self) -> Self:
        return self

    def ensure_owned(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback


@pytest.mark.integration
def test_claim_heartbeat_finish_and_duplicate_finish_are_owner_safe(migrated_engine: Engine) -> None:
    """Break caught: only the live owner may renew/finish, and finish must be idempotent."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, _org_id, _project_id = seed_job(migrated_engine, now=now)
    with Session(migrated_engine) as session, session.begin():
        claim = claim_next_job(session, worker_id="worker-a:1", now=now)
    assert claim is not None

    with Session(migrated_engine) as session, session.begin():
        assert renew_lease(session, job_id=job_id, worker_id="worker-b:1", now=now) is False
        wrong_claim = replace(claim, lease_owner="worker-b:1")
        with pytest.raises(WorkerFailure) as raised:
            finish_job(session, claim=wrong_claim, now=now + timedelta(seconds=1))
        assert raised.value.code == "lease_lost"

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        assert job is not None and job.status == IngestionJobStatus.RUNNING

    with Session(migrated_engine) as session, session.begin():
        assert renew_lease(
            session,
            job_id=job_id,
            worker_id="worker-a:1",
            now=now + timedelta(minutes=1),
        )
        finish_job(session, claim=claim, now=now + timedelta(minutes=1, seconds=1))
        finish_job(session, claim=claim, now=now + timedelta(minutes=1, seconds=2))

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        attempts = list(session.scalars(select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job_id)))
        assert job is not None and job.status == IngestionJobStatus.COMPLETED
        assert len(attempts) == 1
        assert attempts[0].status == IngestionJobAttemptStatus.SUCCEEDED
        assert session.scalar(select(func.count(OutboxEvent.id))) == 0


@pytest.mark.integration
def test_live_lease_cannot_be_stolen_but_expired_lease_is_reclaimed(migrated_engine: Engine) -> None:
    """Break caught: recovery must wait for expiry and preserve each durable attempt fact."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, _org_id, _project_id = seed_job(migrated_engine, now=now)
    with Session(migrated_engine) as session, session.begin():
        first = claim_next_job(session, worker_id="worker-a:1", now=now)
    assert first is not None
    with Session(migrated_engine) as session, session.begin():
        assert claim_next_job(session, worker_id="worker-b:1", now=now + timedelta(minutes=4)) is None
    with Session(migrated_engine) as session, session.begin():
        second = claim_next_job(session, worker_id="worker-b:1", now=now + timedelta(minutes=5))
    assert second is not None and second.job_id == job_id and second.attempt_id != first.attempt_id

    with Session(migrated_engine) as session:
        attempts = list(
            session.scalars(
                select(IngestionJobAttempt)
                .where(IngestionJobAttempt.job_id == job_id)
                .order_by(IngestionJobAttempt.ordinal)
            )
        )
        assert [(attempt.status, attempt.error_code) for attempt in attempts] == [
            (IngestionJobAttemptStatus.FAILED, "lease_lost"),
            (IngestionJobAttemptStatus.RUNNING, None),
        ]


@pytest.mark.integration
def test_expired_owner_cannot_renew_finish_or_fail(migrated_engine: Engine) -> None:
    """Break caught: expiry itself must revoke every lease mutation from the old owner."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, _org_id, _project_id = seed_job(migrated_engine, now=now)
    with Session(migrated_engine) as session, session.begin():
        claim = claim_next_job(session, worker_id="worker-a:1", now=now)
    assert claim is not None

    expired_at = now + timedelta(minutes=5)
    with Session(migrated_engine) as session, session.begin():
        assert renew_lease(
            session,
            job_id=job_id,
            worker_id=claim.lease_owner,
            now=expired_at,
        ) is False
        with pytest.raises(WorkerFailure) as finish_error:
            finish_job(session, claim=claim, now=expired_at)
        assert finish_error.value.code == "lease_lost"

    with Session(migrated_engine) as session, session.begin():
        with pytest.raises(WorkerFailure) as fail_error:
            fail_job(
                session,
                claim=claim,
                failure=WorkerFailure("object_store_unavailable", "temporary", retryable=True),
                now=expired_at,
            )
        assert fail_error.value.code == "lease_lost"

    with Session(migrated_engine) as session, session.begin():
        replacement = claim_next_job(session, worker_id="worker-b:1", now=expired_at)
    assert replacement is not None and replacement.job_id == job_id


@pytest.mark.integration
def test_wrong_owner_cannot_fail_a_live_claim(migrated_engine: Engine) -> None:
    """Break caught: a different worker must not reschedule another owner's live work."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, _org_id, _project_id = seed_job(migrated_engine, now=now)
    with Session(migrated_engine) as session, session.begin():
        claim = claim_next_job(session, worker_id="worker-a:1", now=now)
    assert claim is not None

    with Session(migrated_engine) as session, session.begin():
        with pytest.raises(WorkerFailure) as raised:
            fail_job(
                session,
                claim=replace(claim, lease_owner="worker-b:1"),
                failure=WorkerFailure("object_store_unavailable", "temporary", retryable=True),
                now=now + timedelta(seconds=1),
            )
        assert raised.value.code == "lease_lost"

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        assert job is not None and job.status == IngestionJobStatus.RUNNING


@pytest.mark.integration
def test_stale_finish_rolls_back_publication_after_reclaim(migrated_engine: Engine) -> None:
    """Break caught: stale publication facts must not commit after another worker reclaims."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, org_id, project_id = seed_job(migrated_engine, now=now)
    with Session(migrated_engine) as session, session.begin():
        old_claim = claim_next_job(session, worker_id="worker-a:1", now=now)
    assert old_claim is not None

    with Session(migrated_engine) as old_session:
        with pytest.raises(WorkerFailure) as raised, old_session.begin():
            old_session.add(
                AuditLog(
                    org_id=org_id,
                    actor_type="system",
                    actor_id=None,
                    action="knowledge.publication",
                    resource_type="ingestion_job",
                    resource_id=job_id,
                    trace_id="stale-publication",
                    ip=None,
                    user_agent=None,
                    details={"published": True},
                )
            )
            old_session.add(
                OutboxEvent(
                    org_id=org_id,
                    event_type="knowledge.published",
                    aggregate_type="project",
                    aggregate_id=project_id,
                    payload={"published": True},
                )
            )
            old_session.flush()
            with Session(migrated_engine) as reclaim_session, reclaim_session.begin():
                replacement = claim_next_job(
                    reclaim_session,
                    worker_id="worker-b:1",
                    now=now + timedelta(minutes=5),
                )
            assert replacement is not None
            finish_job(
                old_session,
                claim=old_claim,
                now=now + timedelta(minutes=5, seconds=1),
            )
        assert raised.value.code == "lease_lost"

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        assert job is not None and job.lease_owner == "worker-b:1"
        assert session.scalar(select(func.count(AuditLog.id))) == 0
        assert session.scalar(select(func.count(OutboxEvent.id))) == 0


@pytest.mark.integration
def test_run_once_commits_only_a_handler_that_finishes_the_exact_claim(
    migrated_engine: Engine,
) -> None:
    """Break caught: a successful handler must durably finalize its own claim."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, _org_id, _project_id = seed_job(migrated_engine, now=now)
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def handler(session: Session, claim: ClaimedJob, heartbeat: Heartbeat) -> None:
        heartbeat.ensure_owned()
        finish_job(session, claim=claim, now=now + timedelta(seconds=1))

    assert run_once(
        session_factory=factory,
        worker_id="worker-a:1",
        handlers={kind: handler for kind in REQUIRED_JOB_KINDS},
        now=lambda: now,
        heartbeat_factory=_NoopHeartbeat,
    )

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        attempt = session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job_id)
        )
        assert job is not None and job.status == IngestionJobStatus.COMPLETED
        assert attempt is not None and attempt.status == IngestionJobAttemptStatus.SUCCEEDED


@pytest.mark.integration
def test_run_once_rolls_back_publication_and_fails_a_nonfinalizing_handler(
    migrated_engine: Engine,
) -> None:
    """Break caught: returning with a running attempt cannot commit handler publication."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    job_id, org_id, project_id = seed_job(migrated_engine, now=now)
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def handler(session: Session, claim: ClaimedJob, _heartbeat: Heartbeat) -> None:
        session.add(
            AuditLog(
                org_id=org_id,
                actor_type="system",
                actor_id=None,
                action="knowledge.premature_publication",
                resource_type="ingestion_job",
                resource_id=claim.job_id,
                trace_id="nonfinalizing-handler",
                ip=None,
                user_agent=None,
                details={"published": True},
            )
        )
        session.add(
            OutboxEvent(
                org_id=org_id,
                event_type="knowledge.premature_publication",
                aggregate_type="project",
                aggregate_id=project_id,
                payload={"published": True},
            )
        )

    assert run_once(
        session_factory=factory,
        worker_id="worker-a:1",
        handlers={kind: handler for kind in REQUIRED_JOB_KINDS},
        now=lambda: now,
        heartbeat_factory=_NoopHeartbeat,
    )

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        attempt = session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job_id)
        )
        assert job is not None and job.status == IngestionJobStatus.QUEUED
        assert job.last_error_code == "parser_failed"
        assert attempt is not None and attempt.status == IngestionJobAttemptStatus.FAILED
        assert attempt.error_code == "parser_failed"
        assert session.scalar(select(func.count(AuditLog.id))) == 0
        assert session.scalar(select(func.count(OutboxEvent.id))) == 0


@pytest.mark.integration
def test_expired_final_attempt_terminalizes_instead_of_exceeding_max_attempts(
    migrated_engine: Engine,
) -> None:
    """Break caught: final-attempt expiry must fail the target without creating attempt N+1."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    batch_id, item_id = uuid4(), uuid4()
    job_id, org_id, project_id = seed_job(
        migrated_engine,
        job_kind=JobKind.EXPAND_ARCHIVE,
        target_id=item_id,
        now=now,
    )
    with Session(migrated_engine) as session, session.begin():
        job = session.get(IngestionJob, job_id)
        assert job is not None
        job.max_attempts = 1
        session.add(IngestionBatch(id=batch_id, org_id=org_id, project_id=project_id, item_count=1))
        session.add(
            IngestionItem(
                id=item_id,
                org_id=org_id,
                project_id=project_id,
                batch_id=batch_id,
                normalized_path="final.zip",
                media_type="application/zip",
                size_bytes=10,
                sha256="d" * 64,
                status=IngestionItemStatus.PROCESSING,
            )
        )

    with Session(migrated_engine) as session, session.begin():
        assert claim_next_job(session, worker_id="worker-a:1", now=now) is not None
    with Session(migrated_engine) as session, session.begin():
        assert (
            claim_next_job(session, worker_id="worker-b:1", now=now + timedelta(minutes=5))
            is None
        )

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        item = session.get(IngestionItem, item_id)
        assert job is not None and job.status == IngestionJobStatus.FAILED
        assert job.attempt == 1 and job.last_error_code == "ingestion_retry_exhausted"
        assert item is not None and item.status == IngestionItemStatus.FAILED
        assert item.error_code == "ingestion_retry_exhausted"
        assert item.error_detail == "automatic ingestion retries are exhausted"
        attempt = session.scalar(select(IngestionJobAttempt))
        assert attempt is not None
        assert attempt.safe_detail == "worker no longer owns the job lease"
        assert session.scalar(select(func.count(IngestionJobAttempt.id))) == 1
        assert session.scalar(select(func.count(AuditLog.id))) == 1
        assert session.scalar(select(func.count(OutboxEvent.id))) == 1


@pytest.mark.integration
def test_retry_then_fifth_failure_marks_archive_item_and_emits_once(migrated_engine: Engine) -> None:
    """Break caught: retry exhaustion must atomically terminalize target, batch, audit, and event once."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    batch_id, item_id = uuid4(), uuid4()
    job_id, org_id, project_id = seed_job(
        migrated_engine, job_kind=JobKind.EXPAND_ARCHIVE, target_id=item_id, now=now
    )
    with Session(migrated_engine) as session, session.begin():
        session.add(IngestionBatch(id=batch_id, org_id=org_id, project_id=project_id, item_count=1))
        session.add(
            IngestionItem(
                id=item_id,
                org_id=org_id,
                project_id=project_id,
                batch_id=batch_id,
                normalized_path="archive.zip",
                media_type="application/zip",
                size_bytes=10,
                sha256="a" * 64,
                status=IngestionItemStatus.PROCESSING,
            )
        )

    transient = WorkerFailure("object_store_unavailable", "temporary", retryable=True)
    for ordinal in range(1, 6):
        claim_at = now if ordinal == 1 else now + timedelta(hours=ordinal)
        with Session(migrated_engine) as session, session.begin():
            claim = claim_next_job(session, worker_id="worker-a:1", now=claim_at)
        assert claim is not None
        with Session(migrated_engine) as session, session.begin():
            fail_job(session, claim=claim, failure=transient, now=claim_at)
            fail_job(session, claim=claim, failure=transient, now=claim_at)

        with Session(migrated_engine) as session:
            job = session.get(IngestionJob, job_id)
            assert job is not None
            if ordinal < 5:
                assert job.status == IngestionJobStatus.QUEUED
                assert job.next_attempt_at == claim_at + (
                    timedelta(seconds=5),
                    timedelta(seconds=30),
                    timedelta(minutes=2),
                    timedelta(minutes=10),
                )[ordinal - 1]

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        item = session.get(IngestionItem, item_id)
        batch = session.get(IngestionBatch, batch_id)
        attempts = list(
            session.scalars(
                select(IngestionJobAttempt)
                .where(IngestionJobAttempt.job_id == job_id)
                .order_by(IngestionJobAttempt.ordinal)
            )
        )
        audit = session.scalar(select(AuditLog))
        outbox = session.scalar(select(OutboxEvent))
        assert job is not None and job.status == IngestionJobStatus.FAILED
        assert job.last_error_code == "ingestion_retry_exhausted"
        assert item is not None and item.status == IngestionItemStatus.FAILED
        assert item.error_code == "ingestion_retry_exhausted"
        assert item.error_detail == "automatic ingestion retries are exhausted"
        assert batch is not None and batch.failed_count == 1
        assert len(attempts) == 5
        assert attempts[-1].error_code == "ingestion_retry_exhausted"
        assert attempts[-1].safe_detail == "automatic ingestion retries are exhausted"
        assert audit is not None
        assert audit.details["errorCode"] == "ingestion_retry_exhausted"
        assert audit.details["safeDetail"] == "automatic ingestion retries are exhausted"
        assert outbox is not None
        assert outbox.payload["errorCode"] == "ingestion_retry_exhausted"
        assert outbox.payload["safeDetail"] == "automatic ingestion retries are exhausted"


@pytest.mark.integration
def test_fifth_failure_uses_exhaustion_facts_for_resource_version(
    migrated_engine: Engine,
) -> None:
    """Break caught: resource-version exhaustion facts must share one effective code/template."""
    now = datetime.now(UTC) + timedelta(minutes=1)
    resource_id, version_id = uuid4(), uuid4()
    job_id, org_id, project_id = seed_job(
        migrated_engine,
        job_kind=JobKind.INDEX_RESOURCE_VERSION,
        target_id=version_id,
        now=now,
    )
    with Session(migrated_engine) as session, session.begin():
        session.add(
            KnowledgeResource(
                id=resource_id,
                org_id=org_id,
                project_id=project_id,
                title="exhausted.pdf",
                source_type=ResourceSourceType.UPLOAD,
                source_id="upload-exhausted",
                external_id="exhausted.pdf",
            )
        )
        session.flush()
        session.add(
            KnowledgeResourceVersion(
                id=version_id,
                org_id=org_id,
                project_id=project_id,
                resource_id=resource_id,
                source_type=ResourceSourceType.UPLOAD,
                source_id="upload-exhausted",
                external_id="exhausted.pdf",
                source_version="v1",
                object_key=f"orgs/{org_id}/exhausted.pdf",
                media_type="application/pdf",
                size_bytes=10,
                sha256="f" * 64,
                parser_profile="default-v1",
                chunking_profile="default-v1",
                status=ResourceVersionStatus.PROCESSING,
                processing_started_at=now,
            )
        )

    transient = WorkerFailure("embedding_unavailable", "private provider body", retryable=True)
    for ordinal in range(1, 6):
        claim_at = now + timedelta(hours=ordinal)
        with Session(migrated_engine) as session, session.begin():
            claim = claim_next_job(session, worker_id="worker-a:1", now=claim_at)
        assert claim is not None
        with Session(migrated_engine) as session, session.begin():
            fail_job(session, claim=claim, failure=transient, now=claim_at)

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        version = session.get(KnowledgeResourceVersion, version_id)
        attempts = list(
            session.scalars(
                select(IngestionJobAttempt)
                .where(IngestionJobAttempt.job_id == job_id)
                .order_by(IngestionJobAttempt.ordinal)
            )
        )
        audit = session.scalar(select(AuditLog))
        outbox = session.scalar(select(OutboxEvent))
        assert job is not None and job.last_error_code == "ingestion_retry_exhausted"
        assert version is not None and version.status == ResourceVersionStatus.FAILED
        assert version.error_code == "ingestion_retry_exhausted"
        assert len(attempts) == 5
        assert attempts[-1].error_code == "ingestion_retry_exhausted"
        assert attempts[-1].safe_detail == "automatic ingestion retries are exhausted"
        assert audit is not None
        assert audit.details["errorCode"] == "ingestion_retry_exhausted"
        assert audit.details["safeDetail"] == "automatic ingestion retries are exhausted"
        assert outbox is not None
        assert outbox.payload["errorCode"] == "ingestion_retry_exhausted"
        assert outbox.payload["safeDetail"] == "automatic ingestion retries are exhausted"


@pytest.mark.integration
def test_permanent_failure_terminalizes_on_first_attempt(migrated_engine: Engine) -> None:
    """Break caught: permanent content failures must not enqueue an automatic retry."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    batch_id, item_id = uuid4(), uuid4()
    job_id, org_id, project_id = seed_job(
        migrated_engine, job_kind=JobKind.EXPAND_ARCHIVE, target_id=item_id, now=now
    )
    with Session(migrated_engine) as session, session.begin():
        session.add(IngestionBatch(id=batch_id, org_id=org_id, project_id=project_id, item_count=1))
        session.add(
            IngestionItem(
                id=item_id,
                org_id=org_id,
                project_id=project_id,
                batch_id=batch_id,
                normalized_path="unsafe.zip",
                media_type="application/zip",
                size_bytes=10,
                sha256="b" * 64,
                status=IngestionItemStatus.PROCESSING,
            )
        )
    with Session(migrated_engine) as session, session.begin():
        claim = claim_next_job(session, worker_id="worker-a:1", now=now)
    assert claim is not None
    with Session(migrated_engine) as session, session.begin():
        secret = 'Bearer sk-live-secret {"body":"private document text"}'
        fail_job(
            session,
            claim=claim,
            failure=WorkerFailure.for_code("archive_path_unsafe", secret),
            now=now,
        )
    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        item = session.get(IngestionItem, item_id)
        attempt = session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job_id)
        )
        audit = session.scalar(select(AuditLog))
        outbox = session.scalar(select(OutboxEvent))
        assert job is not None and job.status == IngestionJobStatus.FAILED
        assert job.last_error_code == "archive_path_unsafe"
        assert item is not None and item.error_detail == "archive entry path is unsafe"
        assert attempt is not None and attempt.safe_detail == "archive entry path is unsafe"
        emitted = json.dumps(
            {"audit": audit.details if audit else {}, "outbox": outbox.payload if outbox else {}}
        )
        assert "sk-live-secret" not in emitted
        assert "private document text" not in emitted
        assert session.scalar(select(func.count(IngestionJobAttempt.id))) == 1


@pytest.mark.integration
def test_permanent_failure_terminalizes_resource_version_and_emits_once(
    migrated_engine: Engine,
) -> None:
    """Break caught: index failures must terminalize the version and emit facts idempotently."""
    now = datetime.now(UTC) + timedelta(minutes=1)
    resource_id, version_id = uuid4(), uuid4()
    job_id, org_id, project_id = seed_job(
        migrated_engine,
        job_kind=JobKind.INDEX_RESOURCE_VERSION,
        target_id=version_id,
        now=now,
    )
    with Session(migrated_engine) as session, session.begin():
        session.add(
            KnowledgeResource(
                id=resource_id,
                org_id=org_id,
                project_id=project_id,
                title="failed.pdf",
                source_type=ResourceSourceType.UPLOAD,
                source_id="upload-1",
                external_id="failed.pdf",
            )
        )
        session.flush()
        session.add(
            KnowledgeResourceVersion(
                id=version_id,
                org_id=org_id,
                project_id=project_id,
                resource_id=resource_id,
                source_type=ResourceSourceType.UPLOAD,
                source_id="upload-1",
                external_id="failed.pdf",
                source_version="v1",
                object_key=f"orgs/{org_id}/failed.pdf",
                media_type="application/pdf",
                size_bytes=10,
                sha256="c" * 64,
                parser_profile="default-v1",
                chunking_profile="default-v1",
                status=ResourceVersionStatus.PROCESSING,
                processing_started_at=now,
            )
        )

    with Session(migrated_engine) as session, session.begin():
        claim = claim_next_job(session, worker_id="worker-a:1", now=now)
    assert claim is not None
    with Session(migrated_engine) as session, session.begin():
        failure = WorkerFailure.for_code("no_extractable_text", "no supported text")
        fail_job(session, claim=claim, failure=failure, now=now)
        fail_job(session, claim=claim, failure=failure, now=now)

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        version = session.get(KnowledgeResourceVersion, version_id)
        assert job is not None and job.status == IngestionJobStatus.FAILED
        assert job.last_error_code == "no_extractable_text"
        assert version is not None and version.status == ResourceVersionStatus.FAILED
        assert version.error_code == "no_extractable_text"
        assert session.scalar(select(func.count(IngestionJobAttempt.id))) == 1
        assert session.scalar(select(func.count(AuditLog.id))) == 1
        assert session.scalar(select(func.count(OutboxEvent.id))) == 1


@pytest.mark.integration
@pytest.mark.parametrize("failure_point", ["audit", "outbox"])
def test_terminal_failure_rolls_back_if_fact_insert_fails(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """Break caught: target, attempt, job, audit, and outbox are one atomic transition."""
    now = datetime(2026, 8, 13, 8, tzinfo=UTC)
    batch_id, item_id = uuid4(), uuid4()
    job_id, org_id, project_id = seed_job(
        migrated_engine,
        job_kind=JobKind.EXPAND_ARCHIVE,
        target_id=item_id,
        now=now,
    )
    with Session(migrated_engine) as session, session.begin():
        session.add(IngestionBatch(id=batch_id, org_id=org_id, project_id=project_id, item_count=1))
        session.add(
            IngestionItem(
                id=item_id,
                org_id=org_id,
                project_id=project_id,
                batch_id=batch_id,
                normalized_path="atomic.zip",
                media_type="application/zip",
                size_bytes=10,
                sha256="e" * 64,
                status=IngestionItemStatus.PROCESSING,
            )
        )
    with Session(migrated_engine) as session, session.begin():
        claim = claim_next_job(session, worker_id="worker-a:1", now=now)
    assert claim is not None

    def unavailable(*_: object, **__: object) -> None:
        raise RuntimeError(f"{failure_point} unavailable")

    if failure_point == "audit":
        monkeypatch.setattr("cairn_worker.leases.add_audit_log", unavailable)
    else:
        monkeypatch.setattr("cairn_worker.leases.repository.add_project_outbox_event", unavailable)
    with (
        pytest.raises(RuntimeError, match=f"{failure_point} unavailable"),
        Session(migrated_engine) as session,
        session.begin(),
    ):
        fail_job(
            session,
            claim=claim,
            failure=WorkerFailure.for_code("archive_path_unsafe", "untrusted detail"),
            now=now + timedelta(seconds=1),
        )

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        item = session.get(IngestionItem, item_id)
        attempt = session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job_id)
        )
        assert job is not None and job.status == IngestionJobStatus.RUNNING
        assert job.lease_owner == claim.lease_owner
        assert item is not None and item.status == IngestionItemStatus.PROCESSING
        assert attempt is not None and attempt.status == IngestionJobAttemptStatus.RUNNING
        assert session.scalar(select(func.count(AuditLog.id))) == 0
        assert session.scalar(select(func.count(OutboxEvent.id))) == 0
