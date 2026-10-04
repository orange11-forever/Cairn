"""Durable sync acceptance at the runner/transaction boundary, with fake vendor I/O."""

import hashlib
import json
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, BinaryIO
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import User
from cairn_api.knowledge.models import (
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IngestionBatch,
    IngestionItem,
    IngestionJob,
    IngestionJobAttempt,
    JobKind,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
)
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.projects.models import OutboxEvent
from cairn_worker.errors import WorkerFailure, safe_detail_for
from cairn_worker.feishu import FeishuDocumentClient, FeishuDocumentSnapshot, FeishuFailure
from cairn_worker.feishu_sync import build_feishu_sync_handler
from cairn_worker.indexing import build_index_handler
from cairn_worker.leases import ClaimedJob, claim_next_job
from cairn_worker.runner import run_once
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import sessionmaker

from .conftest import seed_job
from .test_feishu_sync import _Heartbeat, _Store  # pyright: ignore[reportPrivateUsage]

CONTENT = "Durable Feishu snapshot"
PRIVATE = "private-upstream-secret"


def snapshot(**overrides: Any) -> FeishuDocumentSnapshot:
    content = overrides.pop("content", CONTENT)
    return (
        FeishuDocumentSnapshot(
            document_id="DocSync1",
            revision_id=12,
            title="Synced handbook",
            content=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        )
        if not overrides
        else replace(snapshot(content=content), **overrides)
    )


class SnapshotReader:
    def __init__(self) -> None:
        self.value: FeishuDocumentSnapshot | Exception = snapshot()
        self.after_read: Callable[[], None] | None = None
        self.bindings: list[tuple[UUID, str]] = []
        self.document_ids: list[str] = []

    def create_client(self, *, org_id: UUID, credential_ref: str) -> "SnapshotReader":
        self.bindings.append((org_id, credential_ref))
        return self

    def read_document(self, document_id: str) -> FeishuDocumentSnapshot:
        self.document_ids.append(document_id)
        if self.after_read is not None:
            self.after_read()
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class SnapshotStore(_Store):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[str] = []

    def put_object(self, *, object_key: str, source: Any, **kwargs: Any) -> None:
        self.writes.append(object_key)
        super().put_object(object_key=object_key, source=source, **kwargs)

    @contextmanager
    def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:
        yield BytesIO(self.objects[object_key])


class SyncCase:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.now = datetime.now(UTC)
        self.sync_id, self.source_id, self.user_id = uuid4(), uuid4(), uuid4()
        self.job_id, self.org_id, self.project_id = seed_job(
            engine, job_kind=JobKind.SYNC_FEISHU_SOURCE, target_id=self.sync_id, now=self.now
        )
        self.factory = sessionmaker(engine, expire_on_commit=False)
        self.reader = SnapshotReader()
        self.store = SnapshotStore()
        with self.factory.begin() as session:
            job = session.get(IngestionJob, self.job_id)
            assert job is not None
            job.profile_version = "feishu-sync-v1"
            session.add(
                User(
                    id=self.user_id,
                    email=f"{self.user_id}@example.com",
                    normalized_email=f"{self.user_id}@example.com",
                    password_hash="test",
                )
            )
            session.add(
                KnowledgeSource(
                    id=self.source_id,
                    org_id=self.org_id,
                    project_id=self.project_id,
                    name="Fallback handbook",
                    external_id="DocSync1",
                    credential_ref="sync_credential",
                    access_policy="project_members",
                )
            )
            session.flush()
            session.add(
                KnowledgeSourceSync(
                    id=self.sync_id,
                    org_id=self.org_id,
                    project_id=self.project_id,
                    source_id=self.source_id,
                    requested_by=self.user_id,
                )
            )
            profile = session.scalar(
                select(EmbeddingProfile).where(
                    EmbeddingProfile.org_id.is_(None), EmbeddingProfile.status == "active"
                )
            )
            if profile is None:
                session.add(
                    EmbeddingProfile(
                        org_id=None,
                        provider_key="default",
                        model="text-embedding-v4",
                        dimensions=1024,
                        distance_metric="cosine",
                        chunking_config={"maxCodepoints": 1800, "overlapCodepoints": 180},
                        index_config={"strategy": "exact", "candidateLimit": 50},
                        version="default-v1",
                        status=EmbeddingProfileStatus.ACTIVE,
                    )
                )

    def run(self, *, resolver: Any = ..., heartbeat_factory: Any = _Heartbeat) -> bool:
        def noop(_session: Any, _claim: ClaimedJob, _heartbeat: Any) -> None:
            raise AssertionError("test unexpectedly claimed a non-sync job")

        return run_once(
            session_factory=self.factory,
            worker_id="sync-acceptance:1",
            now=lambda: self.now,
            heartbeat_factory=heartbeat_factory,
            handlers={
                JobKind.SYNC_FEISHU_SOURCE: build_feishu_sync_handler(
                    object_store=self.store,
                    resolver=self.reader if resolver is ... else resolver,  # type: ignore[arg-type]
                    now=lambda: self.now,
                ),
                JobKind.EXPAND_ARCHIVE: noop,
                JobKind.INDEX_RESOURCE_VERSION: noop,
            },
        )

    def next_sync(self) -> None:
        self.now += timedelta(seconds=1)
        self.sync_id, self.job_id = uuid4(), uuid4()
        with self.factory.begin() as session:
            # Isolate sync scheduling while leaving the index lifecycle untouched.
            for job in session.scalars(
                select(IngestionJob).where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
            ):
                job.next_attempt_at = self.now + timedelta(days=365)
            session.add(
                KnowledgeSourceSync(
                    id=self.sync_id,
                    org_id=self.org_id,
                    project_id=self.project_id,
                    source_id=self.source_id,
                    requested_by=self.user_id,
                )
            )
            session.add(
                IngestionJob(
                    id=self.job_id,
                    org_id=self.org_id,
                    project_id=self.project_id,
                    job_kind=JobKind.SYNC_FEISHU_SOURCE,
                    target_id=self.sync_id,
                    profile_version="feishu-sync-v1",
                    next_attempt_at=self.now,
                )
            )

    def job(self) -> IngestionJob:
        with self.factory() as session:
            job = session.get(IngestionJob, self.job_id)
            assert job is not None
            return job

    def assert_no_result(self) -> None:
        with self.factory() as session:
            sync = session.get(KnowledgeSourceSync, self.sync_id)
            assert sync is not None
            assert (sync.resource_id, sync.resource_version_id) == (None, None)
            assert session.scalar(select(func.count()).select_from(KnowledgeResource)) == 0
            assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 0
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IngestionJob)
                    .where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.event_type == "knowledge.source_synced")
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action == "knowledge.source_synced")
                )
                == 0
            )
        assert self.store.objects == {}

    def assert_terminal(self, code: str) -> None:
        job = self.job()
        assert job.status == "failed" and job.last_error_code == code
        assert job.completed_at == self.now
        assert job.lease_owner is None and job.lease_expires_at is None
        with self.factory() as session:
            sync = session.get(KnowledgeSourceSync, self.sync_id)
            assert (
                sync is not None and sync.resource_id is None and sync.resource_version_id is None
            )
            attempts = list(
                session.scalars(
                    select(IngestionJobAttempt)
                    .where(IngestionJobAttempt.job_id == job.id)
                    .order_by(IngestionJobAttempt.ordinal)
                )
            )
            assert len(attempts) == job.attempt
            assert all(attempt.status == "failed" for attempt in attempts)
            audits = list(
                session.scalars(
                    select(AuditLog).where(
                        AuditLog.resource_id == job.id,
                        AuditLog.action == "knowledge.ingestion_failed",
                    )
                )
            )
            events = list(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == "knowledge.ingestion_failed"
                    )
                )
            )
            assert len(audits) == len(events) == 1
            expected = {
                "projectId": str(self.project_id),
                "jobId": str(job.id),
                "jobKind": "sync_feishu_source",
                "targetId": str(self.sync_id),
                "sourceSyncId": str(self.sync_id),
                "errorCode": code,
                "safeDetail": safe_detail_for(code),
            }
            assert audits[0].details == expected
            assert audits[0].trace_id == f"worker:{attempts[-1].id}"
            assert events[0].payload == {**expected, "status": "failed"}
            assert PRIVATE not in json.dumps([expected, [a.safe_detail for a in attempts]])


@pytest.fixture
def sync_case(migrated_engine: Engine) -> SyncCase:
    return SyncCase(migrated_engine)


@pytest.mark.integration
def test_sync_of_soft_deleted_resource_reports_safe_actionable_code_without_revival(
    sync_case: SyncCase,
) -> None:
    case = sync_case
    assert case.run()
    with case.factory.begin() as session:
        resource = session.scalar(select(KnowledgeResource))
        assert resource is not None
        resource.deleted_at = case.now
        resource.deleted_by = case.user_id
        old_version = resource.current_version_id
    case.next_sync()

    assert case.run()

    with case.factory() as session:
        resource = session.scalar(select(KnowledgeResource))
        source = session.get(KnowledgeSource, case.source_id)
        sync = session.get(KnowledgeSourceSync, case.sync_id)
        assert resource is not None and resource.deleted_at is not None
        assert resource.current_version_id == old_version
        assert source is not None and source.access_state == "available"
        assert sync is not None and sync.failure_code == "feishu_resource_deleted"
        assert session.scalar(select(func.count()).select_from(KnowledgeResource)) == 1
        assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 1
    assert case.job().status == "failed"


@pytest.mark.integration
@pytest.mark.parametrize("index_status", ["queued", "running", "failed", "completed"])
def test_duplicate_revision_reuses_version_and_preserves_index_lifecycle(
    sync_case: SyncCase,
    index_status: str,
) -> None:
    case = sync_case
    assert case.run()
    first_sync_id = case.sync_id
    case.next_sync()
    with case.factory.begin() as session:
        index = session.scalar(
            select(IngestionJob).where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
        )
        version = session.scalar(select(KnowledgeResourceVersion))
        resource = session.scalar(select(KnowledgeResource))
        assert index is not None and version is not None and resource is not None
        index.status = index_status
        index.attempt = 1 if index_status != "queued" else 0
        index.completed_at = case.now if index_status in {"completed", "failed"} else None
        index.last_error_code = "parser_failed" if index_status == "failed" else None
        if index_status == "running":
            index.lease_owner = "index-worker:1"
            index.lease_expires_at = case.now + timedelta(minutes=5)
            index.heartbeat_at = case.now
        version.status = {
            "queued": "queued",
            "running": "processing",
            "failed": "failed",
            "completed": "ready",
        }[index_status]
        version.error_code = "parser_failed" if index_status == "failed" else None
        version.processing_started_at = case.now if index_status != "queued" else None
        version.ready_at = case.now if index_status == "completed" else None
        if index_status == "completed":
            resource.current_version_id = version.id
        saved = (
            index.id,
            index.attempt,
            index.next_attempt_at,
            index.last_error_code,
            index.lease_owner,
            version.id,
            version.status,
            resource.current_version_id,
        )
    assert case.run()
    assert len(case.store.writes) == 1
    with case.factory() as session:
        syncs = [session.get(KnowledgeSourceSync, value) for value in (first_sync_id, case.sync_id)]
        assert all(sync is not None for sync in syncs)
        assert {(sync.resource_id, sync.resource_version_id) for sync in syncs if sync} == {
            (resource.id, version.id)
        }
        assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
            )
            == 1
        )
        index = session.get(IngestionJob, saved[0])
        version = session.get(KnowledgeResourceVersion, saved[5])
        resource = session.scalar(select(KnowledgeResource))
        assert index is not None and version is not None and resource is not None
        assert index.status == index_status
        assert (
            index.id,
            index.attempt,
            index.next_attempt_at,
            index.last_error_code,
            index.lease_owner,
            version.id,
            version.status,
            resource.current_version_id,
        ) == saved
    assert case.job().status == "completed"


@pytest.mark.integration
def test_hash_conflict_retries_then_reuses_original_without_new_objects(
    sync_case: SyncCase,
) -> None:
    case = sync_case
    assert case.run()
    case.next_sync()
    case.reader.value = snapshot(content="conflicting body")
    assert case.run()
    job = case.job()
    assert job.status == "queued" and job.last_error_code == "parser_failed" and job.attempt == 1
    assert job.next_attempt_at == case.now + timedelta(seconds=5)
    assert len(case.store.writes) == 1
    assert not case.run()  # Backoff is enforced by the real claim query.
    case.now = job.next_attempt_at
    case.reader.value = snapshot()
    assert case.run()
    assert case.job().status == "completed" and case.job().attempt == 2
    assert len(case.store.writes) == 1
    with case.factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
            )
            == 1
        )


@pytest.mark.integration
def test_new_revision_then_stale_read_preserves_all_stored_facts_before_object_write(
    sync_case: SyncCase,
) -> None:
    case = sync_case
    assert case.run()
    with case.factory.begin() as session:
        resource = session.scalar(select(KnowledgeResource))
        version = session.scalar(select(KnowledgeResourceVersion))
        assert resource is not None and version is not None
        old_id = version.id
        resource.current_version_id = old_id
    case.next_sync()
    case.reader.value = snapshot(revision_id=13, content="newer body", title="New title")
    assert case.run()
    with case.factory() as session:
        resource = session.scalar(select(KnowledgeResource))
        assert resource is not None and resource.current_version_id == old_id
        stored = [
            (v.id, v.sha256, v.source_version)
            for v in session.scalars(
                select(KnowledgeResourceVersion).order_by(KnowledgeResourceVersion.source_version)
            )
        ]
        assert [v[2] for v in stored] == ["12", "13"]
    case.next_sync()
    case.reader.value = snapshot(revision_id=11, title="Stale title")
    assert case.run()
    case.assert_terminal("parser_failed")
    assert len(case.store.writes) == len(case.store.objects) == 2
    with case.factory() as session:
        resource = session.scalar(select(KnowledgeResource))
        assert resource is not None and resource.title == "New title"
        assert resource.current_version_id == old_id
        assert [
            (v.id, v.sha256, v.source_version)
            for v in session.scalars(
                select(KnowledgeResourceVersion).order_by(KnowledgeResourceVersion.source_version)
            )
        ] == stored


@pytest.mark.integration
@pytest.mark.parametrize("configuration", [None, "{}", "invalid-private-upstream-secret"])
def test_missing_or_invalid_credentials_fail_before_client_construction(
    sync_case: SyncCase,
    monkeypatch: pytest.MonkeyPatch,
    configuration: str | None,
) -> None:
    if configuration is None:
        monkeypatch.delenv("CAIRN_FEISHU_CREDENTIALS_JSON", raising=False)
    else:
        monkeypatch.setenv("CAIRN_FEISHU_CREDENTIALS_JSON", configuration)
    with patch("cairn_worker.feishu_credentials.FeishuDocumentClient") as constructor:
        assert sync_case.run(resolver=None)
        constructor.assert_not_called()
    sync_case.assert_terminal("parser_failed")
    sync_case.assert_no_result()


class StatusOpener:
    def __init__(self, status: int) -> None:
        self.status = status

    def open(self, *_args: Any, **_kwargs: Any) -> Any:
        from http.client import HTTPMessage
        from urllib.error import HTTPError

        headers = HTTPMessage()
        headers["Retry-After"] = "999999999999"
        raise HTTPError(
            "https://open.feishu.cn/private",
            self.status,
            PRIVATE,
            headers,
            BytesIO(PRIVATE.encode()),
        )


@pytest.mark.integration
@pytest.mark.parametrize("failure", [401, 403, 404, 429, 503, "document_changed", "transport"])
def test_upstream_failures_are_classified_redacted_and_bounded(
    sync_case: SyncCase, failure: Any
) -> None:
    case = sync_case
    if isinstance(failure, int):
        client = FeishuDocumentClient(
            app_id="test", app_secret="test", opener_factory=lambda *_args: StatusOpener(failure)
        )
        with patch.object(case.reader, "create_client", return_value=client):
            assert case.run()
    else:
        case.reader.value = FeishuFailure(
            "feishu_document_changed" if failure == "document_changed" else "feishu_unavailable",
            PRIVATE,
            retryable=True,
            retry_after_seconds=999999,
        )
        assert case.run()
    if failure in {401, 403, 404}:
        case.assert_terminal("parser_failed")
    else:
        job = case.job()
        assert job.status == "queued" and job.last_error_code == "parser_failed"
        assert job.next_attempt_at == case.now + timedelta(seconds=3600)
        assert job.completed_at is None
        with case.factory() as session:
            attempt = session.scalar(select(IngestionJobAttempt))
            assert attempt is not None and attempt.safe_detail == safe_detail_for("parser_failed")
            assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
    case.assert_no_result()
    assert case.store.writes == []


@pytest.mark.integration
@pytest.mark.parametrize(
    "malformation",
    [
        "identity",
        "negative_revision",
        "boolean_revision",
        "oversized_revision",
        "enormous_revision",
        "title_utf8",
        "utf8",
        "hash",
        "empty",
        "whitespace",
        "content_type",
        "title_type",
    ],
)
def test_malformed_snapshots_are_terminal_without_writes(
    sync_case: SyncCase, malformation: str
) -> None:
    values: dict[str, dict[str, Any]] = {
        "identity": {"document_id": "WrongDocument"},
        "negative_revision": {"revision_id": -1},
        "boolean_revision": {"revision_id": True},
        "oversized_revision": {"revision_id": 10**255},
        "enormous_revision": {"revision_id": 10**5000},
        "title_utf8": {"title": "\ud800"},
        "utf8": {"content": "\ud800"},
        "hash": {"content_sha256": "0" * 64},
        "empty": {"content": ""},
        "whitespace": {"content": " \n "},
        "content_type": {"content": None},
        "title_type": {"title": None},
    }
    sync_case.reader.value = replace(snapshot(), **values[malformation])
    assert sync_case.run()
    sync_case.assert_terminal(
        "no_extractable_text" if malformation in {"empty", "whitespace"} else "parser_failed"
    )
    sync_case.assert_no_result()
    assert sync_case.store.writes == []


@pytest.mark.integration
@pytest.mark.parametrize(
    ("title", "expected"), [(" \n ", "Fallback handbook"), ("  " + "界" * 600 + "  ", "界" * 512)]
)
def test_title_fallback_and_bound_use_trusted_source(
    sync_case: SyncCase, title: str, expected: str
) -> None:
    case = sync_case
    case.reader.value = snapshot(title=title)
    assert case.run()
    with case.factory() as session:
        resource = session.scalar(select(KnowledgeResource))
        assert resource is not None and resource.title == expected
    assert case.reader.bindings == [(case.org_id, "sync_credential")]
    assert case.reader.document_ids == ["DocSync1"]


@pytest.mark.integration
@pytest.mark.parametrize("dependency", ["add_audit_log", "repository.add_project_outbox_event"])
def test_completion_event_failure_rolls_back_snapshot_object_and_result(
    sync_case: SyncCase,
    dependency: str,
) -> None:
    case = sync_case
    with patch(f"cairn_worker.feishu_sync.{dependency}", side_effect=RuntimeError(PRIVATE)):
        assert case.run()
    assert case.job().status == "queued" and case.job().last_error_code == "parser_failed"
    assert len(case.store.writes) == 1
    case.assert_no_result()
    case.now = case.job().next_attempt_at
    assert case.run()
    assert case.job().status == "completed"
    assert len(case.store.objects) == 1 and len(set(case.store.writes)) == 2
    with case.factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "knowledge.source_synced")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "knowledge.source_synced")
            )
            == 1
        )


@pytest.mark.integration
def test_lease_reclaimed_during_read_fences_old_worker_then_new_owner_completes(
    sync_case: SyncCase,
) -> None:
    case = sync_case
    reclaimed: list[ClaimedJob] = []

    def reclaim() -> None:
        case.now += timedelta(minutes=6)
        with case.factory.begin() as session:
            claim = claim_next_job(
                session,
                worker_id="replacement:1",
                now=case.now,
                job_kinds={JobKind.SYNC_FEISHU_SOURCE},
            )
            assert claim is not None
            reclaimed.append(claim)

    case.reader.after_read = reclaim
    with pytest.raises(WorkerFailure, match="lease_lost"):
        case.run()
    case.assert_no_result()
    assert case.store.writes == []
    job = case.job()
    assert job.status == "running" and job.lease_owner == "replacement:1" and job.attempt == 2
    case.reader.after_read = None
    with case.factory.begin() as session:
        build_feishu_sync_handler(
            object_store=case.store,
            resolver=case.reader,  # type: ignore[arg-type]
            now=lambda: case.now,
        )(session, reclaimed[0], _Heartbeat())
    assert case.job().status == "completed"
    with case.factory() as session:
        attempts = list(
            session.scalars(select(IngestionJobAttempt).order_by(IngestionJobAttempt.ordinal))
        )
        assert [(a.status, a.error_code) for a in attempts] == [
            ("failed", "lease_lost"),
            ("succeeded", None),
        ]


@pytest.mark.integration
@pytest.mark.parametrize("exhaustion", ["failure", "expired_lease"])
def test_retry_budget_terminalizes_sync_once_without_result(
    sync_case: SyncCase, exhaustion: str
) -> None:
    case = sync_case
    with case.factory.begin() as session:
        job = session.get(IngestionJob, case.job_id)
        assert job is not None
        job.max_attempts = 2
    if exhaustion == "failure":
        case.reader.value = FeishuFailure("feishu_unavailable", PRIVATE, retryable=True)
        assert case.run()
        case.now = case.job().next_attempt_at
        assert case.run()
    else:
        for _ in range(2):
            with case.factory.begin() as session:
                claim = claim_next_job(
                    session,
                    worker_id="abandoned:1",
                    now=case.now,
                    job_kinds={JobKind.SYNC_FEISHU_SOURCE},
                )
                assert claim is not None
            case.now += timedelta(minutes=6)
        with case.factory.begin() as session:
            assert (
                claim_next_job(
                    session,
                    worker_id="replacement:1",
                    now=case.now,
                    job_kinds={JobKind.SYNC_FEISHU_SOURCE},
                )
                is None
            )
    case.assert_terminal("ingestion_retry_exhausted")
    case.assert_no_result()
    assert not case.run()
    case.assert_terminal("ingestion_retry_exhausted")


class Embeddings:
    provider_key = "default"
    model = "text-embedding-v4"
    dimensions = 1024
    maximum_batch_size = 10

    def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 1023 for _ in inputs]


@pytest.mark.integration
def test_sync_then_real_index_publishes_searchable_snapshot(sync_case: SyncCase) -> None:
    from cairn_api.auth.schemas import IdentityContextResponse
    from cairn_api.auth.service import RequestAuditContext
    from cairn_api.knowledge.search_service import KnowledgeSearchService
    from cairn_api.organizations.models import Membership

    case = sync_case
    assert case.run()
    with case.factory() as session:
        resource = session.scalar(select(KnowledgeResource))
        assert resource is not None and resource.current_version_id is None
        assert session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 0
    case.now += timedelta(seconds=1)
    index_handler = build_index_handler(case.store, Embeddings(), now=lambda: case.now)
    assert run_once(
        session_factory=case.factory,
        worker_id="index-acceptance:1",
        now=lambda: case.now,
        heartbeat_factory=_Heartbeat,
        handlers={
            JobKind.EXPAND_ARCHIVE: index_handler,
            JobKind.INDEX_RESOURCE_VERSION: index_handler,
        },
    )
    with case.factory() as session:
        resource = session.scalar(select(KnowledgeResource))
        version = session.scalar(select(KnowledgeResourceVersion))
        assert resource is not None and version is not None
        assert version.status == "ready" and resource.current_version_id == version.id
        assert session.scalar(select(func.count()).select_from(IngestionBatch)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionItem)) == 0
        chunks = list(session.scalars(select(KnowledgeChunk)))
        assert len(chunks) == 1 and chunks[0].text == CONTENT
    membership_id = uuid4()
    with case.factory.begin() as session:
        session.add(
            Membership(id=membership_id, org_id=case.org_id, user_id=case.user_id, role="owner")
        )
    identity = IdentityContextResponse.model_validate(
        {
            "user": {
                "id": case.user_id,
                "email": f"{case.user_id}@example.com",
                "display_name": None,
            },
            "organization": {"id": case.org_id, "slug": "sync-test", "name": "Sync test"},
            "membership": {"id": membership_id, "role": "owner"},
            "csrf_token": "unused",
        }
    )
    with case.factory() as session:
        result = KnowledgeSearchService(
            session, Embeddings(), audit_secret="test-search-secret"
        ).search(
            identity=identity,
            project_id=case.project_id,
            query="Durable",
            limit=10,
            audit=RequestAuditContext(trace_id="sync-search", ip=None, user_agent=None),
        )
    assert result.retrieval_mode == "hybrid"
    assert len(result.results) == 1
    citation = result.results[0]
    assert (citation.resource_id, citation.resource_version_id, citation.chunk_id) == (
        resource.id,
        version.id,
        chunks[0].id,
    )
    assert citation.excerpt == CONTENT and citation.title == "Synced handbook"
    with case.factory.begin() as session:
        source = session.get(KnowledgeSource, case.source_id)
        assert source is not None
        source.status, source.disabled_at = "disabled", case.now
    with case.factory() as session:
        hidden = KnowledgeSearchService(
            session, Embeddings(), audit_secret="test-search-secret"
        ).search(
            identity=identity,
            project_id=case.project_id,
            query="Durable",
            limit=10,
            audit=RequestAuditContext(trace_id="sync-search-disabled", ip=None, user_agent=None),
        )
    assert hidden.results == []


@pytest.mark.integration
@pytest.mark.parametrize("change", ["credential_ref", "external_id", "generation", "deleted_resource"])
def test_changed_source_identity_and_deleted_resource_cannot_publish(
    sync_case: SyncCase,
    change: str,
) -> None:
    case = sync_case
    if change == "deleted_resource":
        assert case.run()
        case.next_sync()
        case.reader.value = snapshot(revision_id=13)

    def change_source() -> None:
        with case.factory.begin() as session:
            source = session.get(KnowledgeSource, case.source_id)
            assert source is not None
            if change == "deleted_resource":
                resource = session.scalar(select(KnowledgeResource))
                assert resource is not None
                resource.deleted_at = case.now
                resource.deleted_by = case.user_id
            elif change == "generation":
                source.generation += 1
                source.access_state = "unverified"
            else:
                setattr(source, change, "ChangedIdentity")

    case.reader.after_read = change_source
    before_writes = list(case.store.writes)
    assert case.run()
    case.assert_terminal("parser_failed")
    assert case.store.writes == before_writes
    if change != "deleted_resource":
        case.assert_no_result()
    else:
        with case.factory() as session:
            resource = session.scalar(select(KnowledgeResource))
            assert resource is not None and resource.deleted_at == case.now
            assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    "failure", ["feishu_access_denied", "feishu_not_found", "feishu_unavailable"]
)
def test_upstream_failure_keeps_previously_shared_snapshot(
    sync_case: SyncCase, failure: str
) -> None:
    case = sync_case
    assert case.run()
    with case.factory.begin() as session:
        resource = session.scalar(select(KnowledgeResource))
        version = session.scalar(select(KnowledgeResourceVersion))
        assert resource is not None and version is not None
        resource.current_version_id = version.id
        original = (resource.id, version.id, version.sha256, resource.title)
    objects = dict(case.store.objects)
    case.next_sync()
    case.reader.value = FeishuFailure(failure, PRIVATE, retryable=failure == "feishu_unavailable")
    assert case.run()
    assert case.job().status == ("queued" if failure == "feishu_unavailable" else "failed")
    with case.factory() as session:
        resource = session.scalar(select(KnowledgeResource))
        version = session.scalar(select(KnowledgeResourceVersion))
        assert resource is not None and version is not None
        assert resource.deleted_at is None
        assert (
            resource.id,
            resource.current_version_id,
            version.sha256,
            resource.title,
        ) == original
        assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 1
    assert case.store.objects == objects and len(case.store.writes) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure_code", "retryable", "expected_state"),
    [
        ("feishu_access_denied", False, "access_denied"),
        ("feishu_not_found", False, "not_found"),
        ("feishu_auth_failed", False, "unverified"),
        ("feishu_rate_limited", True, "available"),
        ("feishu_unavailable", True, "available"),
        ("feishu_document_changed", True, "available"),
        ("feishu_request_rejected", False, "available"),
    ],
)
def test_failed_read_persists_safe_outcome_after_handler_rollback(
    sync_case: SyncCase, failure_code: str, retryable: bool, expected_state: str,
) -> None:
    case = sync_case
    assert case.run()
    with case.factory() as session:
        prior = session.get(KnowledgeSource, case.source_id)
        assert prior is not None and prior.access_state == "available"
        last_success = prior.last_success_at
    case.next_sync()
    case.reader.value = FeishuFailure(failure_code, PRIVATE, retryable=retryable)

    assert case.run()

    with case.factory() as session:
        source = session.get(KnowledgeSource, case.source_id)
        sync = session.get(KnowledgeSourceSync, case.sync_id)
        assert source is not None and sync is not None
        assert source.access_state == expected_state
        assert source.last_error_code == failure_code
        assert source.last_success_at == last_success
        assert sync.failure_code == failure_code
        assert source.last_checked_at == (last_success if failure_code == "feishu_auth_failed" else case.now)
        assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 1
    assert case.job().status == ("queued" if retryable else "failed")
    assert PRIVATE not in repr((source.last_error_code, sync.failure_code))


@pytest.mark.integration
def test_stale_generation_failure_cannot_change_new_source_state(sync_case: SyncCase) -> None:
    case = sync_case
    assert case.run()
    case.next_sync()
    case.reader.value = FeishuFailure("feishu_access_denied", PRIVATE, retryable=False)

    def replace_identity() -> None:
        with case.factory.begin() as session:
            source = session.get(KnowledgeSource, case.source_id)
            assert source is not None
            source.generation += 1
            source.access_state = "unverified"
            source.credential_ref = "replacement"
            source.last_error_code = None

    case.reader.after_read = replace_identity
    assert case.run()
    with case.factory() as session:
        source = session.get(KnowledgeSource, case.source_id)
        sync = session.get(KnowledgeSourceSync, case.sync_id)
        assert source is not None and source.generation == 2
        assert source.access_state == "unverified" and source.last_error_code is None
        assert sync is not None and sync.failure_code == "feishu_access_denied"


@pytest.mark.integration
def test_reclaimed_lease_rejects_old_failure_outcome(sync_case: SyncCase) -> None:
    case = sync_case
    assert case.run()
    case.next_sync()
    case.reader.value = FeishuFailure("feishu_access_denied", PRIVATE, retryable=False)

    def reclaim() -> None:
        case.now += timedelta(minutes=6)
        with case.factory.begin() as session:
            assert claim_next_job(session, worker_id="replacement:1", now=case.now,
                job_kinds={JobKind.SYNC_FEISHU_SOURCE}) is not None

    case.reader.after_read = reclaim
    with pytest.raises(WorkerFailure, match="lease_lost"):
        case.run()
    with case.factory() as session:
        source = session.get(KnowledgeSource, case.source_id)
        sync = session.get(KnowledgeSourceSync, case.sync_id)
        job = session.get(IngestionJob, case.job_id)
        assert source is not None and source.access_state == "available"
        assert source.last_error_code is None
        assert sync is not None and sync.failure_code is None
        assert job is not None and job.status == "running" and job.lease_owner == "replacement:1"


@pytest.mark.integration
def test_successful_recheck_restores_explicit_shared_source_without_duplicate_version(
    sync_case: SyncCase,
) -> None:
    case = sync_case
    assert case.run()
    case.next_sync()
    case.reader.value = FeishuFailure("feishu_access_denied", PRIVATE, retryable=False)
    assert case.run()
    with case.factory() as session:
        denied = session.get(KnowledgeSource, case.source_id)
        assert denied is not None and denied.access_state == "access_denied"
    case.next_sync()
    case.reader.value = snapshot()

    assert case.run()

    with case.factory() as session:
        source = session.get(KnowledgeSource, case.source_id)
        sync = session.get(KnowledgeSourceSync, case.sync_id)
        assert source is not None and source.access_state == "available"
        assert source.last_error_code is None and source.last_success_at == case.now
        assert sync is not None and sync.failure_code is None
        assert sync.resource_version_id is not None
        assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 1


@pytest.mark.integration
@pytest.mark.parametrize("after_write", [False, True])
def test_heartbeat_lease_loss_rolls_back_only_this_attempt_objects(
    sync_case: SyncCase,
    after_write: bool,
) -> None:
    class LostHeartbeat(_Heartbeat):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.checks = 0

        def ensure_owned(self) -> None:
            self.checks += 1
            if self.checks == (2 if after_write else 1):
                raise WorkerFailure("lease_lost", PRIVATE, retryable=True)

    case = sync_case
    with pytest.raises(WorkerFailure, match="lease_lost"):
        case.run(heartbeat_factory=LostHeartbeat)
    case.assert_no_result()
    assert len(case.store.writes) == int(after_write)
    assert case.job().status == "running"
    case.now += timedelta(minutes=6)
    assert case.run()
    assert case.job().status == "completed" and case.job().attempt == 2
    assert len(case.store.objects) == 1
    assert len(set(case.store.writes)) == 1 + int(after_write)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("retry_after", "expected_delay"), [(-100, 5), (0, 5), (30, 30), (999999, 3600)]
)
def test_reader_retry_after_is_locally_bounded(
    sync_case: SyncCase, retry_after: int, expected_delay: int
) -> None:
    case = sync_case
    case.reader.value = FeishuFailure(
        "feishu_rate_limited", PRIVATE, retryable=True, retry_after_seconds=retry_after
    )
    assert case.run()
    assert case.job().next_attempt_at == case.now + timedelta(seconds=expected_delay)
    case.assert_no_result()


@pytest.mark.integration
def test_duplicate_sync_and_index_publication_complete_without_fk_lock_deadlock(
    sync_case: SyncCase,
) -> None:
    """The sync result FK must not deadlock with index's version→resource locks."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, local

    import cairn_worker.feishu_sync as sync_module
    import cairn_worker.indexing as indexing_module
    import cairn_worker.runner as runner_module
    from sqlalchemy import event, text

    case = sync_case
    assert case.run()
    case.next_sync()
    with case.factory.begin() as session:
        index = session.scalar(
            select(IngestionJob).where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
        )
        assert index is not None
        index.next_attempt_at = case.now
        index_id = index.id

    resource_held, version_held = Event(), Event()
    thread_state = local()
    errors: list[BaseException] = []
    original_claim = claim_next_job
    original_completion = sync_module._record_completion  # pyright: ignore[reportPrivateUsage]
    original_target = indexing_module._target  # pyright: ignore[reportPrivateUsage]

    def claim_selected_kind(*args: Any, **kwargs: Any) -> ClaimedJob | None:
        kwargs["job_kinds"] = {thread_state.kind}
        return original_claim(*args, **kwargs)

    def before_completion(*args: Any, **kwargs: Any) -> None:
        # Actual sync handler already owns resource/source and set the duplicate result IDs.
        resource_held.set()
        assert version_held.wait(5), "index did not reach its final version lock"
        original_completion(*args, **kwargs)

    def index_target(*args: Any, **kwargs: Any) -> Any:
        thread_state.publishing = kwargs["lock"]
        return original_target(*args, **kwargs)

    def after_sql(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: Any,
    ) -> None:
        if (
            getattr(thread_state, "publishing", False)
            and "FROM knowledge_resource_versions" in statement
            and "FOR " in statement
        ):
            # Fired after PostgreSQL acquired the version lock, before resource lock.
            version_held.set()

    def transaction_deadlines(connection: Any) -> None:
        connection.execute(text("SET LOCAL lock_timeout = '8s'"))
        connection.execute(text("SET LOCAL statement_timeout = '10s'"))

    def record_database_error(context: Any) -> None:
        errors.append(context.original_exception)

    def run_sync() -> bool:
        thread_state.kind = JobKind.SYNC_FEISHU_SOURCE
        return case.run()

    def run_index() -> bool:
        thread_state.kind = JobKind.INDEX_RESOURCE_VERSION
        handler = build_index_handler(case.store, Embeddings(), now=lambda: case.now)
        return run_once(
            session_factory=case.factory,
            worker_id="index-lock-regression:1",
            now=lambda: case.now,
            heartbeat_factory=_Heartbeat,
            handlers={JobKind.EXPAND_ARCHIVE: handler, JobKind.INDEX_RESOURCE_VERSION: handler},
        )

    event.listen(case.engine, "begin", transaction_deadlines)
    event.listen(case.engine, "after_cursor_execute", after_sql)
    event.listen(case.engine, "handle_error", record_database_error)
    try:
        with (
            patch.object(runner_module, "claim_next_job", claim_selected_kind),
            patch.object(sync_module, "_record_completion", before_completion),
            patch.object(indexing_module, "_target", index_target),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            sync_future = executor.submit(run_sync)
            assert resource_held.wait(5), "sync did not reach duplicate completion"
            index_future = executor.submit(run_index)
            assert sync_future.result(timeout=15)
            assert index_future.result(timeout=15)
    finally:
        version_held.set()
        event.remove(case.engine, "begin", transaction_deadlines)
        event.remove(case.engine, "after_cursor_execute", after_sql)
        event.remove(case.engine, "handle_error", record_database_error)

    assert errors == [], repr(errors)
    with case.factory() as session:
        for job_id in (case.job_id, index_id):
            job = session.get(IngestionJob, job_id)
            assert job is not None
            assert (job.status, job.attempt, job.last_error_code) == ("completed", 1, None)
            attempts = list(
                session.scalars(
                    select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job_id)
                )
            )
            assert len(attempts) == 1 and attempts[0].status == "succeeded"
        sync = session.get(KnowledgeSourceSync, case.sync_id)
        resource = session.scalar(select(KnowledgeResource))
        version = session.scalar(select(KnowledgeResourceVersion))
        assert sync is not None and resource is not None and version is not None
        assert sync.resource_id == resource.id
        assert sync.resource_version_id == resource.current_version_id == version.id
        assert version.status == "ready"
        assert session.scalar(select(func.count()).select_from(KnowledgeResourceVersion)) == 1
        assert session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "knowledge.resource_version_indexed")
            )
            == 1
        )
    assert len(case.store.objects) == len(case.store.writes) == 1


@pytest.mark.integration
def test_resource_deleted_during_indexing_is_not_published(sync_case: SyncCase) -> None:
    case = sync_case
    assert case.run()
    case.now += timedelta(seconds=1)

    class DeletingEmbeddings(Embeddings):
        def embed(self, inputs: Sequence[str]) -> list[list[float]]:
            with case.factory.begin() as session:
                resource = session.scalar(select(KnowledgeResource))
                assert resource is not None
                resource.deleted_at, resource.deleted_by = case.now, case.user_id
            return super().embed(inputs)

    handler = build_index_handler(case.store, DeletingEmbeddings(), now=lambda: case.now)
    assert run_once(
        session_factory=case.factory,
        worker_id="deleted-index:1",
        now=lambda: case.now,
        heartbeat_factory=_Heartbeat,
        handlers={JobKind.EXPAND_ARCHIVE: handler, JobKind.INDEX_RESOURCE_VERSION: handler},
    )
    with case.factory() as session:
        resource = session.scalar(select(KnowledgeResource))
        version = session.scalar(select(KnowledgeResourceVersion))
        index = session.scalar(
            select(IngestionJob).where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
        )
        assert resource is not None and version is not None and index is not None
        assert resource.deleted_at == case.now and resource.current_version_id is None
        assert version.status == "processing" and version.ready_at is None
        assert index.status == "queued" and index.last_error_code == "parser_failed"
        assert session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "knowledge.resource_version_indexed")
            )
            == 0
        )
    assert len(case.store.objects) == len(case.store.writes) == 1
