from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from cairn_api.knowledge.models import JobKind
from cairn_worker.archive import WorkerContext, build_archive_handler
from cairn_worker.leases import ClaimedJob


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
