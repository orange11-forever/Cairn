import hashlib
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO, cast
from uuid import UUID

from cairn_api.audit.repository import add_audit_log
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    ChunkEmbedding,
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobStatus,
    JobKind,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
)
from cairn_api.knowledge.object_store import ObjectNotFound, ObjectStoreUnavailable
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cairn_worker.chunking import ChunkDraft, ChunkingConfig, build_chunks
from cairn_worker.embedding import EmbeddingClient
from cairn_worker.errors import WorkerFailure
from cairn_worker.leases import ClaimedJob, finish_job
from cairn_worker.parsers import ParserRegistry
from cairn_worker.parsers.limits import PARSER_READ_CHUNK_BYTES, PARSER_SOURCE_MAX_BYTES

_SOURCE_SPOOL_BYTES = 8 * 1024 * 1024

Now = Callable[[], datetime]


@dataclass(frozen=True)
class IndexingContext:
    session: Any
    heartbeat: Any
    object_store: Any
    embedding_client: EmbeddingClient
    now: Now


@dataclass(frozen=True)
class _IndexTarget:
    job: IngestionJob
    resource: KnowledgeResource
    version: KnowledgeResourceVersion
    item: IngestionItem | None
    profile: EmbeddingProfile
    completed: bool


def _failure(code: str) -> WorkerFailure:
    if code == "upload_size_mismatch":
        return WorkerFailure(code, "", retryable=False)
    return WorkerFailure.for_code(code, "")


def _profile_value(client: EmbeddingClient, name: str) -> object:
    return getattr(client, name, None)


def _validate_profile(profile: EmbeddingProfile, client: EmbeddingClient) -> ChunkingConfig:
    try:
        chunking = ChunkingConfig.from_profile(profile.chunking_config)
    except ValueError:
        raise _failure("parser_failed") from None
    candidate_limit = profile.index_config.get("candidateLimit")
    client_provider = _profile_value(client, "provider_key")
    client_model = _profile_value(client, "model")
    client_dimensions = _profile_value(client, "dimensions")
    client_batch = _profile_value(client, "maximum_batch_size")
    if (
        client_provider is None
        or profile.provider_key not in {"default", client_provider}
        or profile.model != client_model
        or profile.dimensions != client_dimensions
        or profile.distance_metric != "cosine"
        or profile.index_config.get("strategy") != "exact"
        or isinstance(candidate_limit, bool)
        or not isinstance(candidate_limit, int)
        or candidate_limit <= 0
        or isinstance(client_batch, bool)
        or not isinstance(client_batch, int)
        or client_batch < 1
        or client_batch > 10
    ):
        raise _failure("parser_failed")
    return chunking


def _active_profile(
    session: Session,
    *,
    org_id: UUID,
    lock: bool,
) -> EmbeddingProfile | None:
    organization = select(EmbeddingProfile).where(
        EmbeddingProfile.org_id == org_id,
        EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE,
    )
    if lock:
        organization = organization.with_for_update()
    profile = session.scalar(organization)
    if profile is not None:
        return profile
    global_profile = select(EmbeddingProfile).where(
        EmbeddingProfile.org_id.is_(None),
        EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE,
    )
    if lock:
        global_profile = global_profile.with_for_update()
    return session.scalar(global_profile)


def _target(
    session: Session,
    claim: ClaimedJob,
    client: EmbeddingClient,
    *,
    lock: bool,
) -> _IndexTarget:
    job_statement = select(IngestionJob).where(
        IngestionJob.id == claim.job_id,
        IngestionJob.org_id == claim.org_id,
        IngestionJob.project_id == claim.project_id,
        IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION,
        IngestionJob.target_id == claim.target_id,
    )
    version_statement = select(KnowledgeResourceVersion).where(
        KnowledgeResourceVersion.id == claim.target_id,
        KnowledgeResourceVersion.org_id == claim.org_id,
        KnowledgeResourceVersion.project_id == claim.project_id,
    )
    if lock:
        job_statement = job_statement.with_for_update()
        version_statement = version_statement.with_for_update()
    job = session.scalar(job_statement)
    version = session.scalar(version_statement)
    if job is None or version is None:
        raise _failure("parser_failed")
    resource_statement = select(KnowledgeResource).where(
        KnowledgeResource.id == version.resource_id,
        KnowledgeResource.org_id == claim.org_id,
        KnowledgeResource.project_id == claim.project_id,
        KnowledgeResource.deleted_at.is_(None),
    )
    item_statement = select(IngestionItem).where(
        IngestionItem.org_id == claim.org_id,
        IngestionItem.project_id == claim.project_id,
        IngestionItem.resource_id == version.resource_id,
        IngestionItem.resource_version_id == version.id,
    )
    if lock:
        resource_statement = resource_statement.with_for_update()
        item_statement = item_statement.with_for_update()
    resource = session.scalar(resource_statement)
    item = session.scalar(item_statement)
    profile = _active_profile(session, org_id=claim.org_id, lock=lock)
    if (
        resource is None
        or profile is None
        or job.profile_version != profile.version
        or version.parser_profile != repository.PARSER_PROFILE
        or version.chunking_profile != profile.version
    ):
        raise _failure("parser_failed")
    _validate_profile(profile, client)
    completed = (
        job.status == IngestionJobStatus.COMPLETED
        and version.status == ResourceVersionStatus.READY
        and resource.current_version_id == version.id
    )
    if not completed and version.status == ResourceVersionStatus.READY:
        raise _failure("parser_failed")
    return _IndexTarget(
        job=job,
        resource=resource,
        version=version,
        item=item,
        profile=profile,
        completed=completed,
    )


def _copy_source(version: KnowledgeResourceVersion, context: IndexingContext) -> BinaryIO:
    spool = cast(
        BinaryIO,
        SpooledTemporaryFile(max_size=_SOURCE_SPOOL_BYTES, mode="w+b"),  # noqa: SIM115
    )
    size_bytes = 0
    digest = hashlib.sha256()
    try:
        source_context = context.object_store.open_object(object_key=version.object_key)
        with source_context as source:
            while True:
                chunk = source.read(PARSER_READ_CHUNK_BYTES)
                if not isinstance(chunk, bytes):
                    raise ObjectStoreUnavailable()
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > PARSER_SOURCE_MAX_BYTES:
                    raise _failure("file_too_large")
                digest.update(chunk)
                spool.write(chunk)
    except ObjectNotFound:
        spool.close()
        raise _failure("upload_object_missing") from None
    except ObjectStoreUnavailable:
        spool.close()
        raise _failure("object_store_unavailable") from None
    except OSError:
        spool.close()
        raise _failure("object_store_unavailable") from None
    if size_bytes != version.size_bytes:
        spool.close()
        raise _failure("upload_size_mismatch")
    if digest.hexdigest() != version.sha256:
        spool.close()
        raise _failure("upload_checksum_mismatch")
    spool.seek(0)
    return spool


def _prepare_document(
    version: KnowledgeResourceVersion,
    profile: EmbeddingProfile,
    context: IndexingContext,
) -> list[ChunkDraft]:
    config = _validate_profile(profile, context.embedding_client)
    context.heartbeat.ensure_owned()
    source = _copy_source(version, context)
    try:
        context.heartbeat.ensure_owned()
        parser = ParserRegistry().for_media_type(version.media_type)
        blocks = parser.parse(source)
        context.heartbeat.ensure_owned()
        return build_chunks(blocks, config)
    finally:
        source.close()


def _embed_drafts(
    drafts: Sequence[ChunkDraft],
    client: EmbeddingClient,
    heartbeat: Any,
) -> list[list[float]]:
    batch_size = _profile_value(client, "maximum_batch_size")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 10:
        raise _failure("parser_failed")
    vectors: list[list[float]] = []
    for offset in range(0, len(drafts), batch_size):
        heartbeat.ensure_owned()
        batch = drafts[offset : offset + batch_size]
        produced = client.embed([draft.text for draft in batch])
        heartbeat.ensure_owned()
        if len(produced) != len(batch):
            raise _failure("embedding_unavailable")
        for vector in produced:
            values = cast(Sequence[object], vector)
            if len(values) != _profile_value(client, "dimensions"):
                raise _failure("embedding_dimension_mismatch")
            if any(
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
                for value in values
            ):
                raise _failure("embedding_unavailable")
            vectors.append([float(cast(int | float, value)) for value in values])
    return vectors


def _replace_chunks(
    session: Session,
    *,
    claim: ClaimedJob,
    target: _IndexTarget,
    drafts: Sequence[ChunkDraft],
) -> list[KnowledgeChunk]:
    existing = list(
        session.scalars(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.org_id == claim.org_id,
                KnowledgeChunk.project_id == claim.project_id,
                KnowledgeChunk.resource_id == target.resource.id,
                KnowledgeChunk.resource_version_id == target.version.id,
            )
            .order_by(KnowledgeChunk.ordinal)
            .with_for_update()
        )
    )
    matching = len(existing) == len(drafts) and all(
        chunk.ordinal == draft.ordinal
        and chunk.kind == draft.kind.value
        and chunk.text == draft.text
        and chunk.normalized_text == draft.normalized_text
        and chunk.locator == draft.locator.model_dump(by_alias=True, mode="json")
        for chunk, draft in zip(existing, drafts, strict=True)
    )
    if matching:
        session.execute(
            delete(ChunkEmbedding).where(
                ChunkEmbedding.org_id == claim.org_id,
                ChunkEmbedding.project_id == claim.project_id,
                ChunkEmbedding.resource_id == target.resource.id,
                ChunkEmbedding.resource_version_id == target.version.id,
                ChunkEmbedding.embedding_profile_id == target.profile.id,
            )
        )
        session.flush()
        return existing
    other_profile_embedding = session.scalar(
        select(ChunkEmbedding.id)
        .where(
            ChunkEmbedding.org_id == claim.org_id,
            ChunkEmbedding.project_id == claim.project_id,
            ChunkEmbedding.resource_id == target.resource.id,
            ChunkEmbedding.resource_version_id == target.version.id,
            ChunkEmbedding.embedding_profile_id != target.profile.id,
        )
        .limit(1)
        .with_for_update()
    )
    if other_profile_embedding is not None:
        raise WorkerFailure("parser_failed", "", retryable=False)
    session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.org_id == claim.org_id,
            KnowledgeChunk.project_id == claim.project_id,
            KnowledgeChunk.resource_id == target.resource.id,
            KnowledgeChunk.resource_version_id == target.version.id,
        )
    )
    chunks: list[KnowledgeChunk] = []
    for draft in drafts:
        chunk = KnowledgeChunk(
            org_id=claim.org_id,
            project_id=claim.project_id,
            resource_id=target.resource.id,
            resource_version_id=target.version.id,
            ordinal=draft.ordinal,
            kind=draft.kind.value,
            text=draft.text,
            normalized_text=draft.normalized_text,
            locator=draft.locator.model_dump(by_alias=True, mode="json"),
        )
        session.add(chunk)
        chunks.append(chunk)
    session.flush()
    return chunks


def _persist_embeddings(
    session: Session,
    *,
    claim: ClaimedJob,
    target: _IndexTarget,
    chunks: Sequence[KnowledgeChunk],
    vectors: Sequence[Sequence[float]],
) -> None:
    for chunk, vector in zip(chunks, vectors, strict=True):
        session.add(
            ChunkEmbedding(
                org_id=claim.org_id,
                project_id=claim.project_id,
                resource_id=target.resource.id,
                resource_version_id=target.version.id,
                chunk_id=chunk.id,
                embedding_profile_scope_org_id=target.profile.scope_org_id,
                embedding_profile_id=target.profile.id,
                embedding=list(vector),
            )
        )
    session.flush()


def _publish(
    session: Session,
    *,
    claim: ClaimedJob,
    target: _IndexTarget,
    now: datetime,
    chunk_count: int,
) -> None:
    target.version.status = ResourceVersionStatus.READY
    target.version.error_code = None
    target.version.ready_at = now
    target.resource.current_version_id = target.version.id
    target.resource.updated_at = now
    batch_id: UUID | None = None
    if target.item is not None:
        target.item.status = IngestionItemStatus.READY
        target.item.error_code = None
        target.item.error_detail = None
        target.item.completed_at = now
        batch_id = target.item.batch_id
        repository.refresh_batch_summary(
            session,
            org_id=claim.org_id,
            project_id=claim.project_id,
            batch_id=batch_id,
            now=now,
        )
    details: dict[str, object] = {
        "projectId": str(claim.project_id),
        "resourceId": str(target.resource.id),
        "versionId": str(target.version.id),
        "jobId": str(claim.job_id),
        "profileId": str(target.profile.id),
        "chunkCount": chunk_count,
    }
    if batch_id is not None and target.item is not None:
        details.update({"batchId": str(batch_id), "itemId": str(target.item.id)})
    add_audit_log(
        session,
        org_id=claim.org_id,
        actor_type="system",
        actor_id=None,
        action="knowledge.resource_version_indexed",
        resource_type="knowledge_resource_version",
        resource_id=target.version.id,
        trace_id=f"worker:{claim.attempt_id}",
        ip=None,
        user_agent=None,
        details=details,
    )
    repository.add_project_outbox_event(
        session,
        org_id=claim.org_id,
        project_id=claim.project_id,
        event_type="knowledge.resource_version_indexed",
        payload={**details, "status": ResourceVersionStatus.READY.value},
    )
    finish_job(session, claim=claim, now=now)


def handle_index_resource_version(claim: ClaimedJob, context: IndexingContext) -> None:
    if claim.job_kind != JobKind.INDEX_RESOURCE_VERSION:
        raise _failure("parser_failed")
    session = cast(Session, context.session)
    target = _target(session, claim, context.embedding_client, lock=False)
    if target.completed:
        return
    drafts = _prepare_document(target.version, target.profile, context)
    context.heartbeat.ensure_owned()
    chunks = _replace_chunks(
        session,
        claim=claim,
        target=target,
        drafts=drafts,
    )
    vectors = _embed_drafts(drafts, context.embedding_client, context.heartbeat)
    context.heartbeat.ensure_owned()
    locked = _target(session, claim, context.embedding_client, lock=True)
    if locked.completed:
        return
    if locked.profile.id != target.profile.id:
        raise _failure("parser_failed")
    _persist_embeddings(
        session,
        claim=claim,
        target=locked,
        chunks=chunks,
        vectors=vectors,
    )
    context.heartbeat.ensure_owned()
    publication_time = context.now()
    for boundary in (locked.version.processing_started_at, locked.job.heartbeat_at):
        if boundary is not None:
            publication_time = max(publication_time, boundary)
    _publish(
        session,
        claim=claim,
        target=locked,
        now=publication_time,
        chunk_count=len(drafts),
    )


def build_index_handler(
    object_store: Any,
    embedding_client: EmbeddingClient,
    now: Now | None = None,
) -> Callable[[Any, ClaimedJob, Any], None]:
    current_time = now or (lambda: datetime.now(UTC))

    def handler(session: Any, claim: ClaimedJob, heartbeat: Any) -> None:
        handle_index_resource_version(
            claim,
            IndexingContext(
                session=session,
                heartbeat=heartbeat,
                object_store=object_store,
                embedding_client=embedding_client,
                now=current_time,
            ),
        )

    return handler


__all__ = [
    "IndexingContext",
    "build_index_handler",
    "handle_index_resource_version",
]
