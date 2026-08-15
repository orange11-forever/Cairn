from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from cairn_api.audit.repository import add_audit_log
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobAttemptStatus,
    IngestionJobStatus,
    JobAttemptTrigger,
    JobKind,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from cairn_worker.errors import WorkerFailure, retry_delay, safe_detail_for

LEASE_DURATION = timedelta(minutes=5)
HEARTBEAT_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True)
class ClaimedJob:
    job_id: UUID
    attempt_id: UUID
    org_id: UUID
    project_id: UUID
    job_kind: JobKind
    target_id: UUID
    lease_owner: str
    lease_expires_at: datetime


def _running_attempt(session: Session, job_id: UUID) -> IngestionJobAttempt | None:
    return session.scalar(
        select(IngestionJobAttempt)
        .where(
            IngestionJobAttempt.job_id == job_id,
            IngestionJobAttempt.status == IngestionJobAttemptStatus.RUNNING,
        )
        .order_by(IngestionJobAttempt.ordinal.desc())
        .limit(1)
        .with_for_update()
    )


def _next_attempt(session: Session, *, job: IngestionJob, now: datetime) -> IngestionJobAttempt:
    queued = session.scalar(
        select(IngestionJobAttempt)
        .where(
            IngestionJobAttempt.job_id == job.id,
            IngestionJobAttempt.status == IngestionJobAttemptStatus.QUEUED,
        )
        .order_by(IngestionJobAttempt.ordinal)
        .limit(1)
        .with_for_update()
    )
    if queued is None:
        last_ordinal = session.scalar(
            select(func.max(IngestionJobAttempt.ordinal)).where(
                IngestionJobAttempt.job_id == job.id
            )
        )
        queued = IngestionJobAttempt(
            org_id=job.org_id,
            project_id=job.project_id,
            job_id=job.id,
            ordinal=int(last_ordinal or 0) + 1,
            trigger=JobAttemptTrigger.AUTOMATIC,
            status=IngestionJobAttemptStatus.QUEUED,
            queued_at=now,
        )
        session.add(queued)
        session.flush()
    queued.status = IngestionJobAttemptStatus.RUNNING
    queued.started_at = now
    return queued


def _mark_index_target_processing(session: Session, *, job: IngestionJob, now: datetime) -> None:
    if JobKind(job.job_kind) != JobKind.INDEX_RESOURCE_VERSION:
        return
    version = session.scalar(
        select(KnowledgeResourceVersion)
        .where(
            KnowledgeResourceVersion.id == job.target_id,
            KnowledgeResourceVersion.org_id == job.org_id,
            KnowledgeResourceVersion.project_id == job.project_id,
        )
        .with_for_update()
    )
    if version is None or version.status == ResourceVersionStatus.READY:
        return
    version.status = ResourceVersionStatus.PROCESSING
    version.error_code = None
    version.ready_at = None
    if version.processing_started_at is None:
        version.processing_started_at = max(now, version.created_at)
    item = session.scalar(
        select(IngestionItem)
        .where(
            IngestionItem.org_id == job.org_id,
            IngestionItem.project_id == job.project_id,
            IngestionItem.resource_id == version.resource_id,
            IngestionItem.resource_version_id == version.id,
        )
        .with_for_update()
    )
    if item is None:
        return
    item.status = IngestionItemStatus.PROCESSING
    item.error_code = None
    item.error_detail = None
    item.completed_at = None
    repository.refresh_batch_summary(
        session,
        org_id=job.org_id,
        project_id=job.project_id,
        batch_id=item.batch_id,
        now=now,
    )


def claim_next_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime,
    job_kinds: Collection[JobKind] | None = None,
) -> ClaimedJob | None:
    if job_kinds is not None and not job_kinds:
        return None
    statement = (
        select(IngestionJob)
        .where(
            or_(
                (
                    (IngestionJob.status == IngestionJobStatus.QUEUED)
                    & (IngestionJob.next_attempt_at <= now)
                ),
                (
                    (IngestionJob.status == IngestionJobStatus.RUNNING)
                    & (IngestionJob.lease_expires_at <= now)
                ),
            )
        )
        .order_by(IngestionJob.next_attempt_at, IngestionJob.created_at, IngestionJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job_kinds is not None:
        statement = statement.where(IngestionJob.job_kind.in_(job_kinds))
    job = session.scalar(statement)
    if job is None:
        return None

    if job.status == IngestionJobStatus.RUNNING:
        abandoned = _running_attempt(session, job.id)
        if abandoned is None:
            raise RuntimeError("running ingestion job has no running attempt")
        expired_owner = job.lease_owner
        expired_at = job.lease_expires_at
        if expired_owner is None or expired_at is None:
            raise RuntimeError("running ingestion job has incomplete lease state")
        abandoned.status = IngestionJobAttemptStatus.FAILED
        abandoned.error_code = "lease_lost"
        abandoned.safe_detail = safe_detail_for("lease_lost")
        abandoned.completed_at = now
        if job.attempt >= job.max_attempts:
            job.status = IngestionJobStatus.FAILED
            job.last_error_code = "ingestion_retry_exhausted"
            job.completed_at = now
            _clear_lease(job)
            target_details = _terminalize_target(
                session,
                job=job,
                error_code="ingestion_retry_exhausted",
                safe_detail=safe_detail_for("ingestion_retry_exhausted"),
                now=now,
            )
            _emit_terminal_failure(
                session,
                job=job,
                claim=ClaimedJob(
                    job_id=job.id,
                    attempt_id=abandoned.id,
                    org_id=job.org_id,
                    project_id=job.project_id,
                    job_kind=JobKind(job.job_kind),
                    target_id=job.target_id,
                    lease_owner=expired_owner,
                    lease_expires_at=expired_at,
                ),
                error_code="ingestion_retry_exhausted",
                safe_detail=safe_detail_for("ingestion_retry_exhausted"),
                target_details=target_details,
            )
            session.flush()
            return None

    attempt = _next_attempt(session, job=job, now=now)
    job.attempt += 1
    job.status = IngestionJobStatus.RUNNING
    job.lease_owner = worker_id
    job.heartbeat_at = now
    lease_expires_at = now + LEASE_DURATION
    job.lease_expires_at = lease_expires_at
    job.completed_at = None
    _mark_index_target_processing(session, job=job, now=now)
    session.flush()
    return ClaimedJob(
        job_id=job.id,
        attempt_id=attempt.id,
        org_id=job.org_id,
        project_id=job.project_id,
        job_kind=JobKind(job.job_kind),
        target_id=job.target_id,
        lease_owner=worker_id,
        lease_expires_at=lease_expires_at,
    )


def renew_lease(
    session: Session,
    *,
    job_id: UUID,
    worker_id: str,
    now: datetime,
) -> bool:
    job = session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.id == job_id,
            IngestionJob.status == IngestionJobStatus.RUNNING,
            IngestionJob.lease_owner == worker_id,
            IngestionJob.lease_expires_at > now,
        )
        .with_for_update()
    )
    if job is None:
        return False
    job.heartbeat_at = now
    job.lease_expires_at = now + LEASE_DURATION
    session.flush()
    return True


def _claim_records(
    session: Session,
    claim: ClaimedJob,
) -> tuple[IngestionJob | None, IngestionJobAttempt | None]:
    job = session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.id == claim.job_id,
            IngestionJob.org_id == claim.org_id,
            IngestionJob.project_id == claim.project_id,
        )
        .with_for_update()
    )
    attempt = session.scalar(
        select(IngestionJobAttempt)
        .where(
            IngestionJobAttempt.id == claim.attempt_id,
            IngestionJobAttempt.job_id == claim.job_id,
            IngestionJobAttempt.org_id == claim.org_id,
            IngestionJobAttempt.project_id == claim.project_id,
        )
        .with_for_update()
    )
    return job, attempt


def _is_owned_running(
    job: IngestionJob | None,
    attempt: IngestionJobAttempt | None,
    claim: ClaimedJob,
    *,
    now: datetime,
) -> bool:
    return bool(
        job is not None
        and attempt is not None
        and job.status == IngestionJobStatus.RUNNING
        and job.lease_owner == claim.lease_owner
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
        and attempt.status == IngestionJobAttemptStatus.RUNNING
    )


def _raise_lease_lost() -> None:
    raise WorkerFailure("lease_lost", "", retryable=True)


def _clear_lease(job: IngestionJob) -> None:
    job.lease_owner = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _retry_at(now: datetime, delay: timedelta) -> datetime:
    try:
        return now + delay
    except OverflowError:
        return datetime.max.replace(tzinfo=now.tzinfo)


def finish_job(session: Session, *, claim: ClaimedJob, now: datetime) -> None:
    job, attempt = _claim_records(session, claim)
    if (
        job is not None
        and attempt is not None
        and job.status == IngestionJobStatus.COMPLETED
        and attempt.status == IngestionJobAttemptStatus.SUCCEEDED
    ):
        return
    if not _is_owned_running(job, attempt, claim, now=now):
        _raise_lease_lost()
    assert job is not None and attempt is not None
    attempt.status = IngestionJobAttemptStatus.SUCCEEDED
    attempt.completed_at = now
    job.status = IngestionJobStatus.COMPLETED
    job.last_error_code = None
    job.completed_at = now
    _clear_lease(job)
    session.flush()


def ensure_claim_finalized(session: Session, *, claim: ClaimedJob, now: datetime) -> None:
    session.flush()
    job, attempt = _claim_records(session, claim)
    if (
        job is not None
        and attempt is not None
        and job.status == IngestionJobStatus.COMPLETED
        and attempt.status == IngestionJobAttemptStatus.SUCCEEDED
    ):
        return
    if _is_owned_running(job, attempt, claim, now=now):
        raise WorkerFailure("parser_failed", "", retryable=True)
    _raise_lease_lost()


def _terminalize_target(
    session: Session,
    *,
    job: IngestionJob,
    error_code: str,
    safe_detail: str,
    now: datetime,
) -> dict[str, object]:
    if JobKind(job.job_kind) == JobKind.EXPAND_ARCHIVE:
        item = session.scalar(
            select(IngestionItem)
            .where(
                IngestionItem.id == job.target_id,
                IngestionItem.org_id == job.org_id,
                IngestionItem.project_id == job.project_id,
            )
            .with_for_update()
        )
        if item is None:
            raise LookupError("archive ingestion item is unavailable")
        item.status = IngestionItemStatus.FAILED
        item.error_code = error_code
        item.error_detail = safe_detail
        item.completed_at = now
        repository.refresh_batch_summary(
            session,
            org_id=job.org_id,
            project_id=job.project_id,
            batch_id=item.batch_id,
            now=now,
        )
        return {"batchId": str(item.batch_id), "itemId": str(item.id)}

    version = session.scalar(
        select(KnowledgeResourceVersion)
        .where(
            KnowledgeResourceVersion.id == job.target_id,
            KnowledgeResourceVersion.org_id == job.org_id,
            KnowledgeResourceVersion.project_id == job.project_id,
        )
        .with_for_update()
    )
    if version is None:
        raise LookupError("knowledge resource version is unavailable")
    version.status = ResourceVersionStatus.FAILED
    version.error_code = error_code
    version.ready_at = None
    target_details: dict[str, object] = {
        "resourceId": str(version.resource_id),
        "versionId": str(version.id),
    }
    item = session.scalar(
        select(IngestionItem)
        .where(
            IngestionItem.org_id == job.org_id,
            IngestionItem.project_id == job.project_id,
            IngestionItem.resource_id == version.resource_id,
            IngestionItem.resource_version_id == version.id,
        )
        .with_for_update()
    )
    if item is not None:
        item.status = IngestionItemStatus.FAILED
        item.error_code = error_code
        item.error_detail = safe_detail
        item.completed_at = now
        repository.refresh_batch_summary(
            session,
            org_id=job.org_id,
            project_id=job.project_id,
            batch_id=item.batch_id,
            now=now,
        )
        target_details.update({"batchId": str(item.batch_id), "itemId": str(item.id)})
    return target_details


def _emit_terminal_failure(
    session: Session,
    *,
    job: IngestionJob,
    claim: ClaimedJob,
    error_code: str,
    safe_detail: str,
    target_details: dict[str, object],
) -> None:
    details: dict[str, object] = {
        "projectId": str(job.project_id),
        "jobId": str(job.id),
        "jobKind": str(job.job_kind),
        "targetId": str(job.target_id),
        "errorCode": error_code,
        "safeDetail": safe_detail,
        **target_details,
    }
    add_audit_log(
        session,
        org_id=job.org_id,
        actor_type="system",
        actor_id=None,
        action="knowledge.ingestion_failed",
        resource_type="ingestion_job",
        resource_id=job.id,
        trace_id=f"worker:{claim.attempt_id}",
        ip=None,
        user_agent=None,
        details=details,
    )
    repository.add_project_outbox_event(
        session,
        org_id=job.org_id,
        project_id=job.project_id,
        event_type="knowledge.ingestion_failed",
        payload={**details, "status": IngestionJobStatus.FAILED.value},
    )


def fail_job(
    session: Session,
    *,
    claim: ClaimedJob,
    failure: WorkerFailure,
    now: datetime,
) -> None:
    job, attempt = _claim_records(session, claim)
    if (
        job is not None
        and attempt is not None
        and attempt.status == IngestionJobAttemptStatus.FAILED
        and job.status != IngestionJobStatus.RUNNING
    ):
        return
    if not _is_owned_running(job, attempt, claim, now=now):
        _raise_lease_lost()
    assert job is not None and attempt is not None

    terminal = not failure.retryable or job.attempt >= job.max_attempts
    effective_code = "ingestion_retry_exhausted" if terminal and failure.retryable else failure.code
    effective_detail = (
        safe_detail_for(effective_code) if terminal and failure.retryable else failure.safe_detail
    )
    attempt.status = IngestionJobAttemptStatus.FAILED
    attempt.error_code = effective_code
    attempt.safe_detail = effective_detail
    attempt.completed_at = now
    if not terminal:
        job.status = IngestionJobStatus.QUEUED
        job.next_attempt_at = _retry_at(now, retry_delay(job.attempt, failure))
        job.last_error_code = failure.code
        job.completed_at = None
        _clear_lease(job)
        session.flush()
        return

    job.status = IngestionJobStatus.FAILED
    job.last_error_code = effective_code
    job.completed_at = now
    _clear_lease(job)
    target_details = _terminalize_target(
        session,
        job=job,
        error_code=effective_code,
        safe_detail=effective_detail,
        now=now,
    )
    _emit_terminal_failure(
        session,
        job=job,
        claim=claim,
        error_code=effective_code,
        safe_detail=effective_detail,
        target_details=target_details,
    )
    session.flush()


__all__ = [
    "HEARTBEAT_INTERVAL",
    "LEASE_DURATION",
    "ClaimedJob",
    "claim_next_job",
    "ensure_claim_finalized",
    "fail_job",
    "finish_job",
    "renew_lease",
]
