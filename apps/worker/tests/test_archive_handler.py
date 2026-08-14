from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, Self
from uuid import uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.knowledge.models import (
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobAttemptStatus,
    IngestionJobStatus,
    JobAttemptTrigger,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
)
from cairn_api.projects.models import OutboxEvent
from cairn_worker.archive import WorkerContext, build_archive_handler, inspect_archive
from cairn_worker.leases import ClaimedJob
from cairn_worker.runner import REQUIRED_JOB_KINDS, run_once


def test_runner_adapter_binds_the_existing_transaction_heartbeat_clock_and_object_store(
    monkeypatch: Any,
) -> None:
    """Break caught: archive work must use the runner-owned lease and dependencies."""
    now = datetime(2026, 8, 14, 8, tzinfo=UTC)
    claim = ClaimedJob(
        job_id=uuid4(),
        attempt_id=uuid4(),
        org_id=uuid4(),
        project_id=uuid4(),
        job_kind=JobKind.EXPAND_ARCHIVE,
        target_id=uuid4(),
        lease_owner="archive-a:1",
        lease_expires_at=now + timedelta(minutes=5),
    )
    session = object()
    heartbeat = object()
    object_store = object()
    session_factory = object()
    observed: list[tuple[ClaimedJob, WorkerContext]] = []

    def handle(actual_claim: ClaimedJob, context: WorkerContext) -> None:
        observed.append((actual_claim, context))

    monkeypatch.setattr("cairn_worker.archive.handle_expand_archive", handle)
    adapter = build_archive_handler(
        object_store=object_store,
        session_factory=session_factory,
        now=lambda: now,
    )

    adapter(session, claim, heartbeat)

    assert len(observed) == 1
    actual_claim, context = observed[0]
    assert actual_claim is claim
    assert context.session is session
    assert context.session_factory is session_factory
    assert context.heartbeat is heartbeat
    assert context.object_store is object_store
    assert context.now() == now


class _Transaction:
    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback


class _LeaseSession:
    def __init__(self, records: list[object] | None = None) -> None:
        self.info: dict[str, object] = {}
        self.records = list(records or [])
        self.added: list[object] = []

    def begin(self) -> _Transaction:
        return _Transaction()

    def scalar(self, _statement: object) -> object | None:
        return self.records.pop(0) if self.records else None

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class _NoopHeartbeat:
    def __init__(self, *_args: object) -> None:
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


def test_malformed_archive_is_terminal_through_runner_lease_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: corrupt ZIP bytes must fail once without child publication or retry."""
    now = datetime(2026, 8, 14, 8, tzinfo=UTC)
    claim = ClaimedJob(
        job_id=uuid4(),
        attempt_id=uuid4(),
        org_id=uuid4(),
        project_id=uuid4(),
        job_kind=JobKind.EXPAND_ARCHIVE,
        target_id=uuid4(),
        lease_owner="archive-a:1",
        lease_expires_at=now + timedelta(minutes=5),
    )
    job = IngestionJob(
        id=claim.job_id,
        org_id=claim.org_id,
        project_id=claim.project_id,
        job_kind=claim.job_kind,
        target_id=claim.target_id,
        status=IngestionJobStatus.RUNNING,
        attempt=1,
        max_attempts=5,
        next_attempt_at=now,
        lease_owner=claim.lease_owner,
        lease_expires_at=claim.lease_expires_at,
        heartbeat_at=now,
    )
    attempt = IngestionJobAttempt(
        id=claim.attempt_id,
        org_id=claim.org_id,
        project_id=claim.project_id,
        job_id=claim.job_id,
        ordinal=1,
        trigger=JobAttemptTrigger.AUTOMATIC,
        status=IngestionJobAttemptStatus.RUNNING,
        queued_at=now,
        started_at=now,
    )
    item = IngestionItem(
        id=claim.target_id,
        org_id=claim.org_id,
        project_id=claim.project_id,
        batch_id=uuid4(),
        normalized_path="corrupt.zip",
        media_type="application/zip",
        size_bytes=9,
        sha256="a" * 64,
        status=IngestionItemStatus.PROCESSING,
    )
    claim_session = _LeaseSession()
    handler_session = _LeaseSession()
    failure_session = _LeaseSession([job, attempt, item])
    sessions = iter([claim_session, handler_session, failure_session])

    def claimed(*_args: object, **_kwargs: object) -> ClaimedJob:
        return claim

    def refresh_batch(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("cairn_worker.runner.claim_next_job", claimed)
    monkeypatch.setattr(
        "cairn_worker.leases.repository.refresh_batch_summary",
        refresh_batch,
    )

    def malformed_handler(*_args: object) -> None:
        inspect_archive(BytesIO(b"not a zip"))

    def pending_index_handler(*_args: object) -> None:
        raise AssertionError("wrong handler")

    assert run_once(
        session_factory=lambda: next(sessions),
        worker_id=claim.lease_owner,
        handlers={
            JobKind.EXPAND_ARCHIVE: malformed_handler,
            JobKind.INDEX_RESOURCE_VERSION: pending_index_handler,
        },
        now=lambda: now,
        heartbeat_factory=_NoopHeartbeat,
    )

    assert job.status == IngestionJobStatus.FAILED
    assert job.last_error_code == "parser_failed"
    assert attempt.status == IngestionJobAttemptStatus.FAILED
    assert attempt.error_code == "parser_failed"
    assert item.status == IngestionItemStatus.FAILED
    assert item.error_code == "parser_failed"
    assert not any(isinstance(fact, IngestionJobAttempt) for fact in failure_session.added)
    assert not any(
        isinstance(fact, (KnowledgeResource, KnowledgeResourceVersion))
        for fact in claim_session.added + handler_session.added + failure_session.added
    )
    assert sum(isinstance(fact, AuditLog) for fact in failure_session.added) == 1
    assert sum(isinstance(fact, OutboxEvent) for fact in failure_session.added) == 1
    assert set(REQUIRED_JOB_KINDS) == {
        JobKind.EXPAND_ARCHIVE,
        JobKind.INDEX_RESOURCE_VERSION,
    }
