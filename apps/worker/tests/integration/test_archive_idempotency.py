from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    IngestionBatch,
    IngestionBatchStatus,
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobStatus,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
    UploadSession,
)
from cairn_api.knowledge.object_store import ObjectNotFound, ObjectStat, ObjectStoreUnavailable
from cairn_api.organizations.models import Organization
from cairn_api.projects.models import OutboxEvent, Project
from cairn_worker.archive import WorkerContext, handle_expand_archive
from cairn_worker.errors import WorkerFailure
from cairn_worker.leases import claim_next_job, fail_job
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker


class _Heartbeat:
    def ensure_owned(self) -> None:
        return None


class _Store:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = {}
        self.puts: list[str] = []
        self.fail_after_successes: int | None = None
        self.delete_fails = False

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
            item.completed_at = now + timedelta(minutes=1)
            assert item.resource_version_id is not None
            version = session.get(KnowledgeResourceVersion, item.resource_version_id)
            assert version is not None
            version.status = ResourceVersionStatus.READY
            version.processing_started_at = now + timedelta(seconds=2)
            version.ready_at = now + timedelta(minutes=1)
        batch = repository.refresh_batch_summary(
            session,
            org_id=org_id,
            project_id=project_id,
            batch_id=batch_id,
            now=now + timedelta(minutes=1),
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
