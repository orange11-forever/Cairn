"""Real PostgreSQL scheduling and manual queue arbitration."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, current_thread
from typing import cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.audit.repository import add_audit_log
from cairn_api.knowledge.models import IngestionJob
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.knowledge.source_sync_queue import queue_locked_source_sync
from cairn_api.organizations.models import Organization
from cairn_api.projects.models import OutboxEvent, Project
from cairn_worker.feishu_schedule import schedule_due_sources
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import sessionmaker


def _due_source(engine: Engine, now: datetime, *, interval: int | None = 300, disabled: bool = False) -> tuple[UUID, UUID, UUID]:
    org_id, project_id, source_id = uuid4(), uuid4(), uuid4()
    with sessionmaker(engine).begin() as session:
        session.add(Organization(id=org_id, slug=f"org-{org_id.hex[:10]}", name="Schedule Org"))
        session.add(Project(id=project_id, org_id=org_id, name="Schedule Project"))
        session.flush()
        session.add(KnowledgeSource(
            id=source_id, org_id=org_id, project_id=project_id, name="Scheduled doc",
            external_id="DocSync1", credential_ref="team", access_policy="project_members",
            status="disabled" if disabled else "configured",
            disabled_at=now if disabled else None,
            sync_interval_seconds=interval,
            next_sync_at=now if interval is not None and not disabled else None,
        ))
    return org_id, project_id, source_id


@pytest.mark.integration
def test_due_scan_queues_once_advances_from_now_and_manual_coalesces(migrated_engine: Engine) -> None:
    now = datetime.now(UTC)
    org_id, project_id, source_id = _due_source(migrated_engine, now)
    factory = sessionmaker(migrated_engine, expire_on_commit=False)

    assert schedule_due_sources(factory, now) == 1
    assert schedule_due_sources(factory, now) == 0
    with factory.begin() as session:
        project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
        source = session.scalar(select(KnowledgeSource).where(KnowledgeSource.id == source_id).with_for_update())
        assert project is not None and source is not None
        sync, job = queue_locked_source_sync(session, source=source, trigger="manual", requested_by=None, trace_id="manual-race")
        assert source.next_sync_at == now + timedelta(seconds=300)
    with factory() as session:
        saved_sync = session.get(KnowledgeSourceSync, sync.id)
        assert saved_sync is not None and saved_sync.trigger == "scheduled"
        assert saved_sync.source_generation == 1 and saved_sync.requested_by is None
        assert session.scalar(select(func.count()).select_from(KnowledgeSourceSync)) == 1
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "knowledge.source_sync_queued"))
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "knowledge.source_sync_queued"))
        assert audit is not None and event is not None
        assert audit.actor_type == "system" and audit.actor_id is None
        assert audit.details == event.payload
        assert audit.details["trigger"] == "scheduled"
        assert job.target_id == sync.id and org_id == saved_sync.org_id


@pytest.mark.integration
def test_concurrent_due_scans_use_one_sync_and_do_not_deadlock(migrated_engine: Engine) -> None:
    now = datetime.now(UTC)
    _due_source(migrated_engine, now)
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    barrier = Barrier(2)

    def tick() -> int:
        barrier.wait(timeout=10)
        return schedule_due_sources(factory, now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(tick)
        second = executor.submit(tick)
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert sorted(results) == [0, 1]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeSourceSync)) == 1
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1


@pytest.mark.integration
def test_other_worker_skips_locked_reservation_and_schedules_independent_source(
    migrated_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    source_ids = {_due_source(migrated_engine, now)[2] for _ in range(2)}
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    holder_locked, release_holder = Event(), Event()

    def hold_reservation(_connection: object, _cursor: object, statement: str, _parameters: object,
                         _context: object, _executemany: bool) -> None:
        if "SKIP LOCKED" not in statement or not current_thread().name.startswith("holder"):
            return
        holder_locked.set()
        assert release_holder.wait(10)

    event.listen(migrated_engine, "after_cursor_execute", hold_reservation)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="holder") as first, ThreadPoolExecutor(max_workers=1, thread_name_prefix="other") as second:
            held = first.submit(schedule_due_sources, factory, now, 1)
            assert holder_locked.wait(10)
            other = second.submit(schedule_due_sources, factory, now, 1)
            assert other.result(timeout=10) == 1  # Completes while first worker still holds its source lock.
            assert not held.done()
            release_holder.set()
            assert held.result(timeout=10) == 1
    finally:
        release_holder.set()
        event.remove(migrated_engine, "after_cursor_execute", hold_reservation)
    with factory() as session:
        assert {sync.source_id for sync in session.scalars(select(KnowledgeSourceSync))} == source_ids
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 2


@pytest.mark.integration
def test_due_scan_skips_paused_and_disabled_sources(migrated_engine: Engine) -> None:
    now = datetime.now(UTC)
    _due_source(migrated_engine, now, interval=None)
    _due_source(migrated_engine, now, disabled=True)
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    assert schedule_due_sources(factory, now) == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeSourceSync)) == 0


@pytest.mark.integration
def test_failed_queue_audit_rolls_back_due_advance_and_job(migrated_engine: Engine) -> None:
    now = datetime.now(UTC)
    _, _, source_id = _due_source(migrated_engine, now)
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    with factory() as session:
        initial = session.get(KnowledgeSource, source_id)
        assert initial is not None
        initial_updated_at = initial.updated_at
    with patch("cairn_api.knowledge.source_sync_queue.add_audit_log", side_effect=RuntimeError("private")) as audit, patch("cairn_worker.feishu_schedule.logger.warning") as warning:
        assert schedule_due_sources(factory, now) == 0
    with factory() as session:
        source = session.get(KnowledgeSource, source_id)
        assert source is not None and source.next_sync_at == now
        assert source.last_schedule_attempt_at is not None
        assert source.updated_at == initial_updated_at
        assert session.scalar(select(func.count()).select_from(KnowledgeSourceSync)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    audit.assert_called_once()
    warning.assert_called_once_with("Feishu schedule transaction failed for source_id=%s", source_id)


@pytest.mark.integration
def test_persisted_attempt_order_reaches_healthy_source_after_twenty_rollback_failures(
    migrated_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    ids = [_due_source(migrated_engine, now)[2] for _ in range(21)]
    healthy_id = max(ids)
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    attempts: list[list[str]] = []
    current: list[str] = []

    def selective_audit(*args: object, **kwargs: object) -> None:
        details = kwargs["details"]
        assert isinstance(details, dict)
        source_id = cast(dict[str, object], details)["sourceId"]
        assert isinstance(source_id, str)
        current.append(source_id)
        if source_id != str(healthy_id):
            raise RuntimeError("private-failing-source")
        add_audit_log(*args, **kwargs)  # type: ignore[arg-type]

    with patch("cairn_api.knowledge.source_sync_queue.add_audit_log", side_effect=selective_audit):
        assert schedule_due_sources(factory, now) == 0
        attempts.append(current[:])
        current.clear()
        assert schedule_due_sources(sessionmaker(migrated_engine, expire_on_commit=False), now) == 1
        attempts.append(current[:])
    assert len(attempts[0]) == 20 and str(healthy_id) not in attempts[0]
    assert len(attempts[1]) <= 20 and str(healthy_id) in attempts[1]
    with factory() as session:
        source = session.get(KnowledgeSource, healthy_id)
        syncs = list(session.scalars(select(KnowledgeSourceSync)))
        assert source is not None and source.next_sync_at == now + timedelta(seconds=300)
        assert len(syncs) == 1 and syncs[0].source_id == healthy_id
        for failed_id in ids:
            if failed_id == healthy_id:
                continue
            failed = session.get(KnowledgeSource, failed_id)
            assert failed is not None and failed.next_sync_at == now
            assert failed.last_schedule_attempt_at is not None
