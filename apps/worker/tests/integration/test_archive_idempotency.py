from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from threading import Event, Thread
from typing import Any, BinaryIO, Self, cast
from uuid import UUID, uuid4
from zipfile import ZipFile

import cairn_worker.archive as archive_module
import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    IngestionBatch,
    IngestionBatchStatus,
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
    UploadSession,
)
from cairn_api.knowledge.object_store import (
    ObjectNotFound,
    ObjectStat,
    ObjectStore,
    ObjectStoreUnavailable,
)
from cairn_api.organizations.models import Organization
from cairn_api.projects.models import OutboxEvent, Project
from cairn_worker.archive import WorkerContext, build_archive_handler, handle_expand_archive
from cairn_worker.errors import WorkerFailure
from cairn_worker.leases import ClaimedJob, claim_next_job, fail_job
from cairn_worker.runner import build_runtime_handlers, run_once
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker


class _Heartbeat:
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


class _Store:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = {}
        self.puts: list[str] = []
        self.fail_after_successes: int | None = None
        self.delete_fails = False
        self.deletes: list[str] = []

    @contextmanager
    def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:
        try:
            payload = self.objects[object_key][0]
        except KeyError:
            raise ObjectNotFound() from None
        yield BytesIO(payload)

    def stat(self, *, object_key: str) -> ObjectStat:
        try:
            payload, content_type, checksum = self.objects[object_key]
        except KeyError:
            raise ObjectNotFound() from None
        return ObjectStat(
            size_bytes=len(payload), content_type=content_type, checksum_sha256=checksum
        )

    def put_object(
        self,
        *,
        object_key: str,
        source: BinaryIO,
        size_bytes: int,
        content_type: str,
        checksum_sha256: str,
    ) -> None:
        self.puts.append(object_key)
        successes = sum(1 for key in self.puts[:-1] if key in self.objects)
        if self.fail_after_successes is not None and successes >= self.fail_after_successes:
            self.fail_after_successes = None
            raise ObjectStoreUnavailable()
        if object_key in self.objects:
            raise ObjectStoreUnavailable()
        payload = source.read()
        assert len(payload) == size_bytes
        self.objects[object_key] = (payload, content_type, checksum_sha256)

    def delete_object(self, *, object_key: str) -> None:
        self.deletes.append(object_key)
        if self.delete_fails:
            raise ObjectStoreUnavailable()
        self.objects.pop(object_key, None)


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    target = BytesIO()
    with ZipFile(target, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return target.getvalue()


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _seed_archive(
    engine: Engine, store: _Store, payload: bytes, *, now: datetime
) -> tuple[UUID, UUID, UUID, UUID, str]:
    org_id, project_id, batch_id, item_id, upload_id, job_id = (uuid4() for _ in range(6))
    object_key = f"orgs/{org_id}/projects/{project_id}/uploads/{upload_id}/source"
    checksum = _sha256(payload)
    store.objects[object_key] = (payload, "application/zip", checksum)
    with Session(engine) as session, session.begin():
        session.add(Organization(id=org_id, slug=f"org-{org_id.hex[:10]}", name="Archive Org"))
        session.add(Project(id=project_id, org_id=org_id, name="Archive Project"))
        session.flush()
        session.add(
            IngestionBatch(
                id=batch_id,
                org_id=org_id,
                project_id=project_id,
                status=IngestionBatchStatus.PROCESSING,
                item_count=1,
            )
        )
        session.add(
            IngestionItem(
                id=item_id,
                org_id=org_id,
                project_id=project_id,
                batch_id=batch_id,
                normalized_path="bundle.zip",
                media_type="application/zip",
                size_bytes=len(payload),
                sha256=checksum,
                status=IngestionItemStatus.PROCESSING,
            )
        )
        session.flush()
        session.add(
            UploadSession(
                id=upload_id,
                org_id=org_id,
                project_id=project_id,
                batch_id=batch_id,
                item_id=item_id,
                original_file_name="bundle.zip",
                declared_media_type="application/zip",
                size_bytes=len(payload),
                sha256=checksum,
                object_key=object_key,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                completed_at=now,
            )
        )
        session.add(
            IngestionJob(
                id=job_id,
                org_id=org_id,
                project_id=project_id,
                job_kind=JobKind.EXPAND_ARCHIVE,
                target_id=item_id,
                next_attempt_at=now,
            )
        )
    return job_id, org_id, project_id, batch_id, object_key


def _context(
    session: Session,
    factory: sessionmaker[Session],
    store: _Store,
    now: datetime,
) -> WorkerContext:
    return WorkerContext(
        session=session,
        session_factory=factory,
        heartbeat=_Heartbeat(),
        object_store=store,
        now=lambda: now + timedelta(seconds=1),
    )


@pytest.mark.integration
def test_partial_success_creates_supported_children_and_keeps_unsupported_entry_explicit(
    migrated_engine: Engine,
) -> None:
    """Break caught: a safe unsupported sibling must be visible without blocking valid children."""
    now = datetime(2026, 8, 14, 8, tzinfo=UTC)
    payload = _zip(
        [
            ("docs/report.pdf", b"%PDF-1.7\nbody"),
            ("docs/notes.txt", b"plain text"),
            ("tools/run.exe", b"MZ binary"),
        ]
    )
    store = _Store()
    _job_id, org_id, project_id, batch_id, source_key = _seed_archive(
        migrated_engine, store, payload, now=now
    )
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as claim_session, claim_session.begin():
        claim = claim_next_job(claim_session, worker_id="archive-a:1", now=now)
    assert claim is not None

    with factory() as session, session.begin():
        handle_expand_archive(claim, _context(session, factory, store, now))

    with Session(migrated_engine) as session:
        children = list(
            session.scalars(
                select(IngestionItem)
                .where(IngestionItem.parent_item_id == claim.target_id)
                .order_by(IngestionItem.normalized_path)
            )
        )
        assert [(item.normalized_path, item.status, item.error_code) for item in children] == [
            ("docs/notes.txt", IngestionItemStatus.QUEUED, None),
            ("docs/report.pdf", IngestionItemStatus.QUEUED, None),
            ("tools/run.exe", IngestionItemStatus.FAILED, "unsupported_media_type"),
        ]
        parent = session.get(IngestionItem, claim.target_id)
        assert parent is not None and parent.status == IngestionItemStatus.READY
        resources = list(session.scalars(select(KnowledgeResource)))
        versions = list(session.scalars(select(KnowledgeResourceVersion)))
        jobs = list(session.scalars(select(IngestionJob)))
        assert len(resources) == len(versions) == 2
        assert len(jobs) == 3
        assert all(resource.source_type == "zip_entry" for resource in resources)
        assert all(resource.source_id != source_key for resource in resources)
        assert session.scalar(select(func.count(AuditLog.id))) == 1
        assert session.scalar(select(func.count(OutboxEvent.id))) == 1

    with Session(migrated_engine) as session, session.begin():
        finished_at = datetime.now(UTC) + timedelta(minutes=1)
        supported = list(
            session.scalars(
                select(IngestionItem).where(
                    IngestionItem.parent_item_id == claim.target_id,
                    IngestionItem.status == IngestionItemStatus.QUEUED,
                )
            )
        )
        for item in supported:
            item.status = IngestionItemStatus.READY
            item.completed_at = finished_at
            assert item.resource_version_id is not None
            version = session.get(KnowledgeResourceVersion, item.resource_version_id)
            assert version is not None
            version.status = ResourceVersionStatus.READY
            version.processing_started_at = version.created_at + timedelta(seconds=1)
            version.ready_at = finished_at
        batch = repository.refresh_batch_summary(
            session,
            org_id=org_id,
            project_id=project_id,
            batch_id=batch_id,
            now=finished_at,
        )
        assert batch.status == IngestionBatchStatus.COMPLETED_WITH_ERRORS


@pytest.mark.integration
def test_retry_after_partial_object_writes_is_idempotent_even_when_cleanup_fails(
    migrated_engine: Engine,
) -> None:
    """Break caught: reclaim after object writes must reuse deterministic facts and objects."""
    now = datetime(2026, 8, 14, 9, tzinfo=UTC)
    payload = _zip([("a.txt", b"alpha"), ("b.txt", b"beta")])
    store = _Store()
    job_id, _org_id, _project_id, _batch_id, _source_key = _seed_archive(
        migrated_engine, store, payload, now=now
    )
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as claim_session, claim_session.begin():
        first = claim_next_job(claim_session, worker_id="archive-a:1", now=now)
    assert first is not None
    store.fail_after_successes = 1
    store.delete_fails = True

    with pytest.raises(WorkerFailure) as raised, factory() as session, session.begin():
        handle_expand_archive(first, _context(session, factory, store, now))
    assert raised.value.code == "object_store_unavailable"
    with factory() as session, session.begin():
        fail_job(session, claim=first, failure=raised.value, now=now + timedelta(seconds=1))
    with factory() as claim_session, claim_session.begin():
        second = claim_next_job(
            claim_session, worker_id="archive-b:1", now=now + timedelta(seconds=6)
        )
    assert second is not None and second.job_id == job_id and second.attempt_id != first.attempt_id

    with factory() as session, session.begin():
        handle_expand_archive(second, _context(session, factory, store, now + timedelta(seconds=6)))
    before_repeat = (len(store.objects), len(store.puts))
    with factory() as session, session.begin():
        handle_expand_archive(second, _context(session, factory, store, now + timedelta(seconds=7)))
    assert (len(store.objects), len(store.puts)) == before_repeat

    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count(KnowledgeResource.id))) == 2
        assert session.scalar(select(func.count(KnowledgeResourceVersion.id))) == 2
        assert (
            session.scalar(
                select(func.count(IngestionItem.id)).where(
                    IngestionItem.parent_item_id == second.target_id
                )
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count(IngestionJob.id)).where(
                    IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION
                )
            )
            == 2
        )
        assert session.scalar(select(func.count(AuditLog.id))) == 1
        assert session.scalar(select(func.count(OutboxEvent.id))) == 1
        job = session.get(IngestionJob, job_id)
        assert job is not None and job.status == IngestionJobStatus.COMPLETED


@pytest.mark.integration
def test_malformed_archive_is_terminal_without_child_publication(
    migrated_engine: Engine,
) -> None:
    """Break caught: PostgreSQL publication must reject corrupt ZIP bytes on attempt one."""
    now = datetime(2026, 8, 14, 10, tzinfo=UTC)
    payload = b"not a zip"
    store = _Store()
    job_id, _org_id, _project_id, _batch_id, _source_key = _seed_archive(
        migrated_engine, store, payload, now=now
    )
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def wrong_handler(*_args: object) -> None:
        raise AssertionError("index handler must not run")

    assert run_once(
        session_factory=factory,
        worker_id="archive-a:1",
        handlers={
            JobKind.EXPAND_ARCHIVE: build_archive_handler(
                object_store=store,
                session_factory=factory,
                now=lambda: now,
            ),
            JobKind.INDEX_RESOURCE_VERSION: wrong_handler,
        },
        now=lambda: now,
        heartbeat_factory=_Heartbeat,
    )

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        attempt = session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job_id)
        )
        assert job is not None and job.status == IngestionJobStatus.FAILED
        assert job.attempt == 1 and job.last_error_code == "parser_failed"
        assert attempt is not None and attempt.status == IngestionJobAttemptStatus.FAILED
        assert attempt.error_code == "parser_failed"
        assert session.scalar(select(func.count(KnowledgeResource.id))) == 0
        assert session.scalar(select(func.count(KnowledgeResourceVersion.id))) == 0
        assert (
            session.scalar(
                select(func.count(IngestionItem.id)).where(IngestionItem.parent_item_id.is_not(None))
            )
            == 0
        )
        assert session.scalar(select(func.count(AuditLog.id))) == 1
        assert session.scalar(select(func.count(OutboxEvent.id))) == 1


@pytest.mark.integration
def test_stale_cleanup_waits_for_reclaim_and_cannot_delete_uncommitted_adoption(
    migrated_engine: Engine,
) -> None:
    """Break caught: rollback cleanup must serialize with a replacement attempt's adoption."""
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    store = _Store()
    job_id, org_id, project_id, _batch_id, _source_key = _seed_archive(
        migrated_engine, store, _zip([("entry.txt", b"entry")]), now=now
    )
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        old_claim = claim_next_job(session, worker_id="archive-a:1", now=now)
    assert old_claim is not None
    object_key = f"orgs/{org_id}/projects/{project_id}/replacement-object"
    store.objects[object_key] = (b"entry", "text/plain", _sha256(b"entry"))
    cleanup_done = Event()
    cleanup_errors: list[BaseException] = []

    def stale_cleanup() -> None:
        try:
            archive_module._cleanup_object(  # pyright: ignore[reportPrivateUsage]
                factory,
                cast(ObjectStore, store),
                object_key,
                old_claim,
                now + timedelta(minutes=5),
            )
        except Exception as error:  # noqa: BLE001  # pragma: no cover
            cleanup_errors.append(error)
        finally:
            cleanup_done.set()

    cleanup_thread = Thread(target=stale_cleanup, daemon=True)
    with factory() as replacement_session, replacement_session.begin():
        replacement = claim_next_job(
            replacement_session,
            worker_id="archive-b:1",
            now=now + timedelta(minutes=5),
        )
        assert replacement is not None and replacement.job_id == job_id
        resource = KnowledgeResource(
            org_id=org_id,
            project_id=project_id,
            title="entry.txt",
            source_type=ResourceSourceType.ZIP_ENTRY,
            source_id="replacement",
            external_id="entry.txt",
            created_by=None,
        )
        replacement_session.add(resource)
        replacement_session.flush()
        replacement_session.add(
            KnowledgeResourceVersion(
                org_id=org_id,
                project_id=project_id,
                resource_id=resource.id,
                source_type=ResourceSourceType.ZIP_ENTRY,
                source_id="replacement",
                external_id="entry.txt",
                source_version=_sha256(b"entry"),
                object_key=object_key,
                media_type="text/plain",
                size_bytes=5,
                sha256=_sha256(b"entry"),
                parser_profile=repository.PARSER_PROFILE,
                chunking_profile=repository.CHUNKING_PROFILE,
                status=ResourceVersionStatus.QUEUED,
            )
        )
        replacement_session.flush()
        cleanup_thread.start()
        assert not cleanup_done.wait(0.25)

    cleanup_thread.join(timeout=5)
    assert cleanup_done.is_set() and cleanup_errors == []
    assert object_key in store.objects
    assert store.deletes == []


@pytest.mark.integration
def test_runtime_parks_index_jobs_without_mutating_publication_facts(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: Task 9 workers must leave Task 11 jobs queued and fact-neutral."""
    now = datetime(2026, 8, 14, 13, tzinfo=UTC)
    store = _Store()
    _job_id, _org_id, _project_id, _batch_id, _source_key = _seed_archive(
        migrated_engine, store, _zip([("entry.txt", b"entry")]), now=now
    )
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    archive_handler = archive_module.build_archive_handler(
        object_store=store, session_factory=factory, now=lambda: now
    )

    def pending_index_handler(_session: Any, _claim: ClaimedJob, _heartbeat: Any) -> None:
        pass

    assert run_once(
        session_factory=factory,
        worker_id="archive-a:1",
        handlers={
            JobKind.EXPAND_ARCHIVE: archive_handler,
            JobKind.INDEX_RESOURCE_VERSION: pending_index_handler,
        },
        now=lambda: now,
        heartbeat_factory=_Heartbeat,
    )
    monkeypatch.setattr("cairn_worker.runner.HANDLERS", {})
    runtime_handlers = build_runtime_handlers(
        object_store=cast(ObjectStore, store), session_factory=factory
    )
    with Session(migrated_engine) as session:
        parked = session.scalar(
            select(IngestionJob).where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
        )
        version = session.scalar(select(KnowledgeResourceVersion))
        child = session.scalar(
            select(IngestionItem).where(IngestionItem.parent_item_id.is_not(None))
        )
        batch = session.scalar(select(IngestionBatch))
        assert (
            parked is not None and version is not None and child is not None and batch is not None
        )
        before = (
            parked.status,
            parked.attempt,
            parked.last_error_code,
            version.status,
            child.status,
            batch.status,
            session.scalar(select(func.count(IngestionJobAttempt.id))),
            session.scalar(select(func.count(AuditLog.id))),
            session.scalar(select(func.count(OutboxEvent.id))),
        )

    assert not run_once(
        session_factory=factory,
        worker_id="archive-a:1",
        handlers=runtime_handlers,
        now=lambda: now + timedelta(seconds=1),
        heartbeat_factory=_Heartbeat,
    )
    assert not run_once(
        session_factory=factory,
        worker_id="archive-a:1",
        handlers=runtime_handlers,
        now=lambda: now + timedelta(seconds=2),
        heartbeat_factory=_Heartbeat,
    )

    with Session(migrated_engine) as session:
        parked = session.scalar(
            select(IngestionJob).where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
        )
        version = session.scalar(select(KnowledgeResourceVersion))
        child = session.scalar(
            select(IngestionItem).where(IngestionItem.parent_item_id.is_not(None))
        )
        batch = session.scalar(select(IngestionBatch))
        assert (
            parked is not None and version is not None and child is not None and batch is not None
        )
        after = (
            parked.status,
            parked.attempt,
            parked.last_error_code,
            version.status,
            child.status,
            batch.status,
            session.scalar(select(func.count(IngestionJobAttempt.id))),
            session.scalar(select(func.count(AuditLog.id))),
            session.scalar(select(func.count(OutboxEvent.id))),
        )
    assert after == before
    assert parked.status == IngestionJobStatus.QUEUED and parked.attempt == 0


@pytest.mark.integration
def test_oversized_archive_path_is_terminal_before_publication_or_object_write(
    migrated_engine: Engine,
) -> None:
    """Break caught: persistence-overflow names fail permanently before side effects."""
    now = datetime(2026, 8, 14, 14, tzinfo=UTC)
    payload = _zip([(f"{'a' * 509}.txt", b"entry")])
    store = _Store()
    job_id, _org_id, _project_id, _batch_id, _source_key = _seed_archive(
        migrated_engine, store, payload, now=now
    )
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def pending_index_handler(_session: Any, _claim: ClaimedJob, _heartbeat: Any) -> None:
        pass

    assert run_once(
        session_factory=factory,
        worker_id="archive-a:1",
        handlers={
            JobKind.EXPAND_ARCHIVE: build_archive_handler(
                object_store=store, session_factory=factory, now=lambda: now
            ),
            JobKind.INDEX_RESOURCE_VERSION: pending_index_handler,
        },
        now=lambda: now,
        heartbeat_factory=_Heartbeat,
    )

    with Session(migrated_engine) as session:
        job = session.get(IngestionJob, job_id)
        attempt = session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job_id)
        )
        assert job is not None and job.status == IngestionJobStatus.FAILED
        assert job.attempt == 1 and job.last_error_code == "archive_path_unsafe"
        assert attempt is not None and attempt.error_code == "archive_path_unsafe"
        assert session.scalar(select(func.count(KnowledgeResource.id))) == 0
        assert session.scalar(select(func.count(KnowledgeResourceVersion.id))) == 0
        assert (
            session.scalar(
                select(func.count(IngestionItem.id)).where(
                    IngestionItem.parent_item_id.is_not(None)
                )
            )
            == 0
        )
        assert session.scalar(select(func.count(AuditLog.id))) == 1
        assert session.scalar(select(func.count(OutboxEvent.id))) == 1
    assert store.puts == []
