import hashlib
import json
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO, Self, cast
from uuid import UUID, uuid4

import cairn_worker.indexing as indexing_module
import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.knowledge import repository as knowledge_repository
from cairn_api.knowledge.models import (
    ChunkEmbedding,
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobAttemptStatus,
    IngestionJobStatus,
    JobKind,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceSourceType,
    ResourceVersionStatus,
)
from cairn_api.knowledge.object_store import ObjectStoreUnavailable
from cairn_api.projects.models import OutboxEvent
from cairn_worker.errors import WorkerFailure
from cairn_worker.indexing import (
    IndexingContext,
    build_index_handler,
    handle_index_resource_version,
)
from cairn_worker.leases import ClaimedJob
from cairn_worker.runner import run_once
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from .conftest import seed_job

CONTENT = b"Alpha beta gamma"


class _Store:
    def __init__(self, value: bytes | Exception = CONTENT) -> None:
        self.value = value
        self.opens = 0

    @contextmanager
    def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:
        del object_key
        self.opens += 1
        if isinstance(self.value, Exception):
            raise self.value
        from io import BytesIO

        yield BytesIO(self.value)


class _Embedding:
    provider_key = "test-provider"
    model = "test-model"
    dimensions = 1024

    def __init__(
        self,
        *,
        maximum_batch_size: int = 2,
        failure: Exception | None = None,
        after_call: Any = None,
    ) -> None:
        self.maximum_batch_size = maximum_batch_size
        self.failure = failure
        self.after_call = after_call
        self.calls: list[list[str]] = []
        self.produced = 0

    def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(inputs))
        if self.failure is not None:
            raise self.failure
        vectors: list[list[float]] = []
        for _value in inputs:
            vectors.append([float(self.produced)] + [0.0] * 1023)
            self.produced += 1
        if self.after_call is not None:
            callback, self.after_call = self.after_call, None
            callback()
        return vectors


class _Heartbeat:
    def __init__(self, *_args: object, fail_at: int | None = None, **_kwargs: object) -> None:
        self.fail_at = fail_at
        self.checks = 0

    def __enter__(self) -> Self:
        return self

    def ensure_owned(self) -> None:
        self.checks += 1
        if self.fail_at == self.checks:
            raise WorkerFailure.for_code("lease_lost", "")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback


@dataclass(frozen=True)
class _Seed:
    now: datetime
    job_id: UUID
    org_id: UUID
    project_id: UUID
    batch_id: UUID
    item_id: UUID
    resource_id: UUID
    old_version_id: UUID
    target_version_id: UUID
    profile_id: UUID
    stale_chunk_id: UUID
    old_chunk_id: UUID


def _seed(engine: Engine) -> _Seed:
    now = datetime.now(UTC) + timedelta(minutes=1)
    target_version_id = uuid4()
    job_id, org_id, project_id = seed_job(
        engine,
        job_kind=JobKind.INDEX_RESOURCE_VERSION,
        target_id=target_version_id,
        now=now,
    )
    batch_id, item_id, resource_id, old_version_id = uuid4(), uuid4(), uuid4(), uuid4()
    stale_chunk_id, old_chunk_id = uuid4(), uuid4()
    profile_id = uuid4()
    with Session(engine) as session, session.begin():
        profile = EmbeddingProfile(
            id=profile_id,
            org_id=org_id,
            provider_key="test-provider",
            model="test-model",
            dimensions=1024,
            distance_metric="cosine",
            chunking_config={"maxCodepoints": 8, "overlapCodepoints": 0},
            index_config={"strategy": "exact", "candidateLimit": 50},
            version="default-v1",
            status=EmbeddingProfileStatus.ACTIVE,
        )
        session.add(profile)
        session.add(IngestionBatch(id=batch_id, org_id=org_id, project_id=project_id, item_count=1))
        resource = KnowledgeResource(
            id=resource_id,
            org_id=org_id,
            project_id=project_id,
            title="source.txt",
            source_type=ResourceSourceType.UPLOAD,
            source_id="upload-index",
            external_id="source.txt",
        )
        session.add(resource)
        session.flush()
        session.add_all(
            [
                KnowledgeResourceVersion(
                    id=old_version_id,
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    source_type=ResourceSourceType.UPLOAD,
                    source_id="upload-index",
                    external_id="source.txt",
                    source_version="old",
                    object_key=f"orgs/{org_id}/old.txt",
                    media_type="text/plain",
                    size_bytes=3,
                    sha256=hashlib.sha256(b"old").hexdigest(),
                    parser_profile="default-v1",
                    chunking_profile="default-v1",
                    status=ResourceVersionStatus.READY,
                    processing_started_at=now,
                    ready_at=now,
                ),
                KnowledgeResourceVersion(
                    id=target_version_id,
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    source_type=ResourceSourceType.UPLOAD,
                    source_id="upload-index",
                    external_id="source.txt",
                    source_version="new",
                    object_key=f"orgs/{org_id}/new.txt",
                    media_type="text/plain",
                    size_bytes=len(CONTENT),
                    sha256=hashlib.sha256(CONTENT).hexdigest(),
                    parser_profile="default-v1",
                    chunking_profile="default-v1",
                    status=ResourceVersionStatus.QUEUED,
                ),
            ]
        )
        session.flush()
        resource.current_version_id = old_version_id
        session.add(
            IngestionItem(
                id=item_id,
                org_id=org_id,
                project_id=project_id,
                batch_id=batch_id,
                normalized_path="source.txt",
                media_type="text/plain",
                size_bytes=len(CONTENT),
                sha256=hashlib.sha256(CONTENT).hexdigest(),
                status=IngestionItemStatus.QUEUED,
                resource_id=resource_id,
                resource_version_id=target_version_id,
            )
        )
        session.add_all(
            [
                KnowledgeChunk(
                    id=old_chunk_id,
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    resource_version_id=old_version_id,
                    ordinal=0,
                    kind="text",
                    text="old preserved",
                    normalized_text="old preserved",
                    locator={"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 1},
                ),
                KnowledgeChunk(
                    id=stale_chunk_id,
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    resource_version_id=target_version_id,
                    ordinal=0,
                    kind="text",
                    text="stale target",
                    normalized_text="stale target",
                    locator={"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 1},
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                ChunkEmbedding(
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    resource_version_id=old_version_id,
                    chunk_id=old_chunk_id,
                    embedding_profile_scope_org_id=profile.scope_org_id,
                    embedding_profile_id=profile_id,
                    embedding=[9.0] * 1024,
                ),
                ChunkEmbedding(
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    resource_version_id=target_version_id,
                    chunk_id=stale_chunk_id,
                    embedding_profile_scope_org_id=profile.scope_org_id,
                    embedding_profile_id=profile_id,
                    embedding=[8.0] * 1024,
                ),
            ]
        )
    return _Seed(
        now=now,
        job_id=job_id,
        org_id=org_id,
        project_id=project_id,
        batch_id=batch_id,
        item_id=item_id,
        resource_id=resource_id,
        old_version_id=old_version_id,
        target_version_id=target_version_id,
        profile_id=profile_id,
        stale_chunk_id=stale_chunk_id,
        old_chunk_id=old_chunk_id,
    )


def _run(
    engine: Engine,
    seed: _Seed,
    store: _Store,
    embedding: _Embedding,
    *,
    heartbeat_factory: Any = _Heartbeat,
) -> bool:
    factory = sessionmaker(engine, expire_on_commit=False)
    index_handler = build_index_handler(store, embedding, lambda: seed.now)

    def unused_archive_handler(_session: Any, _claim: ClaimedJob, _heartbeat: Any) -> None:
        return None

    return run_once(
        session_factory=factory,
        worker_id="worker-a:1",
        handlers={
            JobKind.INDEX_RESOURCE_VERSION: index_handler,
            JobKind.EXPAND_ARCHIVE: unused_archive_handler,
        },
        now=lambda: seed.now,
        heartbeat_factory=heartbeat_factory,
    )


@pytest.mark.integration
def test_success_atomically_replaces_target_facts_and_publishes_exact_version(
    migrated_engine: Engine,
) -> None:
    """Break caught: partial or cross-version index publication must never become current."""
    seed = _seed(migrated_engine)
    store = _Store()
    embedding = _Embedding()

    assert _run(migrated_engine, seed, store, embedding)

    assert embedding.calls == [["Alpha", "beta"], ["gamma"]]
    with Session(migrated_engine) as session:
        resource = session.get(KnowledgeResource, seed.resource_id)
        version = session.get(KnowledgeResourceVersion, seed.target_version_id)
        item = session.get(IngestionItem, seed.item_id)
        batch = session.get(IngestionBatch, seed.batch_id)
        job = session.get(IngestionJob, seed.job_id)
        attempt = session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == seed.job_id)
        )
        chunks = list(
            session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.resource_version_id == seed.target_version_id)
                .order_by(KnowledgeChunk.ordinal)
            )
        )
        vectors = list(
            session.scalars(
                select(ChunkEmbedding)
                .where(ChunkEmbedding.resource_version_id == seed.target_version_id)
                .order_by(ChunkEmbedding.created_at, ChunkEmbedding.id)
            )
        )
        assert resource is not None and resource.current_version_id == seed.target_version_id
        assert version is not None and version.status == ResourceVersionStatus.READY
        assert version.ready_at == seed.now
        assert item is not None and item.status == IngestionItemStatus.READY
        assert batch is not None and batch.status == IngestionBatchStatus.COMPLETED
        assert job is not None and job.status == IngestionJobStatus.COMPLETED
        assert attempt is not None and attempt.status == IngestionJobAttemptStatus.SUCCEEDED
        assert [chunk.text for chunk in chunks] == ["Alpha", "beta", "gamma"]
        assert [chunk.normalized_text for chunk in chunks] == ["alpha", "beta", "gamma"]
        assert [chunk.ordinal for chunk in chunks] == [0, 1, 2]
        assert [chunk.kind for chunk in chunks] == ["text", "text", "text"]
        assert [chunk.locator for chunk in chunks] == [
            {"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 1}
        ] * 3
        assert len(vectors) == 3
        assert all(vector.embedding_profile_id == seed.profile_id for vector in vectors)
        vectors_by_chunk = {vector.chunk_id: vector for vector in vectors}
        assert [next(iter(vectors_by_chunk[chunk.id].embedding)) for chunk in chunks] == [
            0.0,
            1.0,
            2.0,
        ]
        assert all(len(vector.embedding) == 1024 for vector in vectors)
        assert session.get(KnowledgeChunk, seed.stale_chunk_id) is None
        assert session.get(KnowledgeChunk, seed.old_chunk_id) is not None
        assert session.scalar(select(func.count(AuditLog.id))) == 1
        assert session.scalar(select(func.count(OutboxEvent.id))) == 1
        audit = session.scalar(select(AuditLog))
        outbox = session.scalar(select(OutboxEvent))
        assert audit is not None and audit.action == "knowledge.resource_version_indexed"
        assert audit.details["chunkCount"] == 3
        assert outbox is not None and outbox.event_type == "knowledge.resource_version_indexed"

        assert attempt is not None
        claim = ClaimedJob(
            job_id=seed.job_id,
            attempt_id=attempt.id,
            org_id=seed.org_id,
            project_id=seed.project_id,
            job_kind=JobKind.INDEX_RESOURCE_VERSION,
            target_id=seed.target_version_id,
            lease_owner="worker-a:1",
            lease_expires_at=seed.now + timedelta(minutes=5),
        )
        handle_index_resource_version(
            claim,
            IndexingContext(
                session=session,
                heartbeat=_Heartbeat(),
                object_store=store,
                embedding_client=embedding,
                now=lambda: seed.now,
            ),
        )
        assert (
            session.scalar(
                select(func.count(KnowledgeChunk.id)).where(
                    KnowledgeChunk.resource_version_id == seed.target_version_id
                )
            )
            == 3
        )
        assert session.scalar(select(func.count(AuditLog.id))) == 1
    assert store.opens == 1


@pytest.mark.integration
def test_global_active_profile_is_used_only_when_organization_has_no_active_profile(
    migrated_engine: Engine,
) -> None:
    """Break caught: global fallback must remain usable without overriding an organization Profile."""
    seed = _seed(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        organization_profile = session.get(EmbeddingProfile, seed.profile_id)
        assert organization_profile is not None
        organization_profile.status = EmbeddingProfileStatus.INACTIVE
        session.add(
            EmbeddingProfile(
                org_id=None,
                provider_key="global-provider",
                model="global-model",
                dimensions=1024,
                distance_metric="cosine",
                chunking_config={"maxCodepoints": 1800, "overlapCodepoints": 180},
                index_config={"strategy": "exact", "candidateLimit": 50},
                version="default-v1",
                status=EmbeddingProfileStatus.ACTIVE,
            )
        )
        session.flush()
        global_profile = session.scalar(
            select(EmbeddingProfile).where(
                EmbeddingProfile.org_id.is_(None),
                EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE,
            )
        )
        assert global_profile is not None
        global_profile_id = global_profile.id
        provider_key = global_profile.provider_key
        model = global_profile.model
        dimensions = global_profile.dimensions
        batch_size = 2

    embedding = _Embedding(maximum_batch_size=batch_size)
    embedding.provider_key = provider_key
    embedding.model = model
    embedding.dimensions = dimensions

    assert _run(migrated_engine, seed, _Store(), embedding)

    with Session(migrated_engine) as session:
        profile_ids = set(
            session.scalars(
                select(ChunkEmbedding.embedding_profile_id).where(
                    ChunkEmbedding.resource_version_id == seed.target_version_id
                )
            )
        )
        assert profile_ids == {global_profile_id}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("store_value", "failure", "expected_code"),
    [
        (
            CONTENT,
            WorkerFailure.for_code("embedding_unavailable", "private provider body"),
            "embedding_unavailable",
        ),
        (CONTENT, RuntimeError("private source and provider secret"), "parser_failed"),
        (ObjectStoreUnavailable("private store endpoint"), None, "object_store_unavailable"),
    ],
    ids=["provider", "unexpected", "store"],
)
def test_retryable_failures_roll_back_publication_and_keep_processing(
    migrated_engine: Engine,
    store_value: bytes | Exception,
    failure: Exception | None,
    expected_code: str,
) -> None:
    """Break caught: external/unexpected failures must reschedule without publishing partial facts."""
    seed = _seed(migrated_engine)

    assert _run(migrated_engine, seed, _Store(store_value), _Embedding(failure=failure))

    with Session(migrated_engine) as session:
        resource = session.get(KnowledgeResource, seed.resource_id)
        version = session.get(KnowledgeResourceVersion, seed.target_version_id)
        item = session.get(IngestionItem, seed.item_id)
        batch = session.get(IngestionBatch, seed.batch_id)
        job = session.get(IngestionJob, seed.job_id)
        attempt = session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == seed.job_id)
        )
        assert resource is not None and resource.current_version_id == seed.old_version_id
        assert version is not None and version.status == ResourceVersionStatus.PROCESSING
        assert item is not None and item.status == IngestionItemStatus.PROCESSING
        assert batch is not None and batch.status == IngestionBatchStatus.PROCESSING
        assert job is not None and job.status == IngestionJobStatus.QUEUED
        assert job.last_error_code == expected_code
        assert attempt is not None and attempt.error_code == expected_code
        exposed = json.dumps({"job": job.last_error_code, "attempt": attempt.safe_detail})
        assert "private" not in exposed
        assert session.get(KnowledgeChunk, seed.stale_chunk_id) is not None
        assert session.scalar(select(func.count(AuditLog.id))) == 0
        assert session.scalar(select(func.count(OutboxEvent.id))) == 0


@pytest.mark.integration
def test_dimension_mismatch_terminalizes_version_item_and_batch_first_attempt(
    migrated_engine: Engine,
) -> None:
    """Break caught: incompatible vectors must fail the full ingestion target without retry."""
    seed = _seed(migrated_engine)

    assert _run(
        migrated_engine,
        seed,
        _Store(),
        _Embedding(failure=WorkerFailure.for_code("embedding_dimension_mismatch", "secret")),
    )

    with Session(migrated_engine) as session:
        resource = session.get(KnowledgeResource, seed.resource_id)
        version = session.get(KnowledgeResourceVersion, seed.target_version_id)
        item = session.get(IngestionItem, seed.item_id)
        batch = session.get(IngestionBatch, seed.batch_id)
        job = session.get(IngestionJob, seed.job_id)
        assert resource is not None and resource.current_version_id == seed.old_version_id
        assert version is not None and version.status == ResourceVersionStatus.FAILED
        assert version.error_code == "embedding_dimension_mismatch"
        assert item is not None and item.status == IngestionItemStatus.FAILED
        assert batch is not None and batch.status == IngestionBatchStatus.FAILED
        assert job is not None and job.status == IngestionJobStatus.FAILED
        assert job.attempt == 1
        assert session.scalar(select(func.count(AuditLog.id))) == 1
        assert session.scalar(select(func.count(OutboxEvent.id))) == 1


@pytest.mark.integration
@pytest.mark.parametrize("failure_point", ["audit", "outbox", "constraint"])
def test_publication_fact_or_constraint_failure_rolls_back_everything(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """Break caught: database, audit, and Outbox failures must not expose a partial publication."""
    seed = _seed(migrated_engine)

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(f"{failure_point} unavailable")

    if failure_point == "audit":
        monkeypatch.setattr(indexing_module, "add_audit_log", unavailable)
    elif failure_point == "outbox":
        monkeypatch.setattr(knowledge_repository, "add_project_outbox_event", unavailable)
    else:
        original = cast(
            Any,
            indexing_module._persist_embeddings,  # pyright: ignore[reportPrivateUsage]
        )

        def violate(*args: object, **kwargs: object) -> None:
            original(*args, **kwargs)
            values = cast(dict[str, Any], kwargs)
            session = cast(Session, values["session"])
            session.add(
                KnowledgeChunk(
                    org_id=seed.org_id,
                    project_id=seed.project_id,
                    resource_id=seed.resource_id,
                    resource_version_id=seed.target_version_id,
                    ordinal=0,
                    kind="text",
                    text="duplicate ordinal",
                    normalized_text="duplicate ordinal",
                    locator={"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 1},
                )
            )
            session.flush()

        monkeypatch.setattr(indexing_module, "_persist_embeddings", violate)

    assert _run(migrated_engine, seed, _Store(), _Embedding())

    with Session(migrated_engine) as session:
        resource = session.get(KnowledgeResource, seed.resource_id)
        version = session.get(KnowledgeResourceVersion, seed.target_version_id)
        job = session.get(IngestionJob, seed.job_id)
        assert resource is not None and resource.current_version_id == seed.old_version_id
        assert version is not None and version.status == ResourceVersionStatus.PROCESSING
        assert job is not None and job.status == IngestionJobStatus.QUEUED
        assert job.last_error_code == "parser_failed"
        assert session.get(KnowledgeChunk, seed.stale_chunk_id) is not None
        assert session.scalar(select(func.count(AuditLog.id))) == 0
        assert session.scalar(select(func.count(OutboxEvent.id))) == 0


@pytest.mark.integration
def test_lease_loss_rolls_back_publication_without_stale_owner_finalization(
    migrated_engine: Engine,
) -> None:
    """Break caught: a stale worker must neither publish nor rewrite the live lease outcome."""
    seed = _seed(migrated_engine)

    def heartbeat_factory(*args: object, **kwargs: object) -> _Heartbeat:
        return _Heartbeat(*args, **kwargs, fail_at=4)

    with pytest.raises(WorkerFailure) as raised:
        _run(
            migrated_engine,
            seed,
            _Store(),
            _Embedding(),
            heartbeat_factory=heartbeat_factory,
        )
    assert raised.value.code == "lease_lost"

    with Session(migrated_engine) as session:
        resource = session.get(KnowledgeResource, seed.resource_id)
        job = session.get(IngestionJob, seed.job_id)
        assert resource is not None and resource.current_version_id == seed.old_version_id
        assert job is not None and job.status == IngestionJobStatus.RUNNING
        assert session.get(KnowledgeChunk, seed.stale_chunk_id) is not None
        assert session.scalar(select(func.count(AuditLog.id))) == 0
        assert session.scalar(select(func.count(OutboxEvent.id))) == 0


@pytest.mark.integration
def test_concurrent_profile_switch_is_rechecked_before_publication(
    migrated_engine: Engine,
) -> None:
    """Break caught: vectors built for a deactivated Profile must never become current facts."""
    seed = _seed(migrated_engine)

    def switch_profile() -> None:
        with Session(migrated_engine) as session, session.begin():
            old = session.get(EmbeddingProfile, seed.profile_id)
            assert old is not None
            old.status = EmbeddingProfileStatus.INACTIVE
            session.flush()
            session.add(
                EmbeddingProfile(
                    org_id=seed.org_id,
                    provider_key="test-provider",
                    model="test-model",
                    dimensions=1024,
                    distance_metric="cosine",
                    chunking_config={"maxCodepoints": 8, "overlapCodepoints": 0},
                    index_config={"strategy": "exact", "candidateLimit": 50},
                    version="switched-v2",
                    status=EmbeddingProfileStatus.ACTIVE,
                )
            )

    assert _run(
        migrated_engine,
        seed,
        _Store(),
        _Embedding(after_call=switch_profile),
    )

    with Session(migrated_engine) as session:
        resource = session.get(KnowledgeResource, seed.resource_id)
        version = session.get(KnowledgeResourceVersion, seed.target_version_id)
        job = session.get(IngestionJob, seed.job_id)
        assert resource is not None and resource.current_version_id == seed.old_version_id
        assert version is not None and version.status == ResourceVersionStatus.PROCESSING
        assert job is not None and job.status == IngestionJobStatus.QUEUED
        assert job.last_error_code == "parser_failed"
        assert session.get(KnowledgeChunk, seed.stale_chunk_id) is not None
