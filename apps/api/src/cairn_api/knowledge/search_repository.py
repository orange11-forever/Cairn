from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.knowledge.models import (
    ChunkEmbedding,
    EmbeddingProfile,
    EmbeddingProfileStatus,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
)

SEARCH_CANDIDATE_LIMIT = 50


@dataclass(frozen=True)
class RankedCandidate:
    chunk_id: UUID
    rank: int


@dataclass(frozen=True)
class SearchCitationRecord:
    resource_id: UUID
    resource_version_id: UUID
    chunk_id: UUID
    title: str
    media_type: str
    excerpt: str
    locator: dict[str, object]


def get_active_embedding_profile(
    session: Session,
    *,
    org_id: UUID,
) -> EmbeddingProfile | None:
    profile = session.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.org_id == org_id,
            EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE,
        )
    )
    if profile is not None:
        return profile
    return session.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.org_id.is_(None),
            EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE,
        )
    )


def _authorized_current_chunks(
    *,
    org_id: UUID,
    project_id: UUID,
    access_filter: ColumnElement[bool],
) -> tuple[ColumnElement[bool], ...]:
    return (
        KnowledgeChunk.org_id == org_id,
        KnowledgeChunk.project_id == project_id,
        KnowledgeResource.org_id == org_id,
        KnowledgeResource.project_id == project_id,
        KnowledgeResource.deleted_at.is_(None),
        KnowledgeResource.current_version_id == KnowledgeResourceVersion.id,
        KnowledgeResourceVersion.org_id == org_id,
        KnowledgeResourceVersion.project_id == project_id,
        KnowledgeResourceVersion.status == ResourceVersionStatus.READY,
        access_filter,
    )


def lexical_statement(
    *,
    org_id: UUID,
    project_id: UUID,
    query: str,
    access_filter: ColumnElement[bool],
    candidate_limit: int = SEARCH_CANDIDATE_LIMIT,
) -> Select[tuple[UUID, float]]:
    ts_query = func.websearch_to_tsquery("simple", query)
    fts_score = func.ts_rank_cd(KnowledgeChunk.search_vector, ts_query)
    trigram_score = func.similarity(KnowledgeChunk.normalized_text, query)
    score = (fts_score + trigram_score).label("search_score")
    return (
        select(KnowledgeChunk.id, score)
        .select_from(KnowledgeChunk)
        .join(
            KnowledgeResourceVersion,
            (KnowledgeResourceVersion.org_id == KnowledgeChunk.org_id)
            & (KnowledgeResourceVersion.project_id == KnowledgeChunk.project_id)
            & (KnowledgeResourceVersion.resource_id == KnowledgeChunk.resource_id)
            & (KnowledgeResourceVersion.id == KnowledgeChunk.resource_version_id),
        )
        .join(
            KnowledgeResource,
            (KnowledgeResource.org_id == KnowledgeResourceVersion.org_id)
            & (KnowledgeResource.project_id == KnowledgeResourceVersion.project_id)
            & (KnowledgeResource.id == KnowledgeResourceVersion.resource_id),
        )
        .where(
            *_authorized_current_chunks(
                org_id=org_id,
                project_id=project_id,
                access_filter=access_filter,
            ),
            or_(
                KnowledgeChunk.search_vector.op("@@")(ts_query),
                KnowledgeChunk.normalized_text.op("%")(query),
                KnowledgeChunk.normalized_text.contains(query, autoescape=True),
            ),
        )
        .order_by(score.desc(), KnowledgeChunk.id)
        .limit(candidate_limit)
    )


def lexical_candidates(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    query: str,
    access_filter: ColumnElement[bool],
    candidate_limit: int = SEARCH_CANDIDATE_LIMIT,
) -> list[RankedCandidate]:
    rows = session.execute(
        lexical_statement(
            org_id=org_id,
            project_id=project_id,
            query=query,
            access_filter=access_filter,
            candidate_limit=candidate_limit,
        )
    ).all()
    return [RankedCandidate(chunk_id=row[0], rank=rank) for rank, row in enumerate(rows, 1)]


def vector_statement(
    *,
    org_id: UUID,
    project_id: UUID,
    query_vector: list[float],
    embedding_profile_id: UUID,
    embedding_profile_scope_org_id: UUID,
    access_filter: ColumnElement[bool],
    candidate_limit: int = SEARCH_CANDIDATE_LIMIT,
) -> Select[tuple[UUID, float]]:
    distance = ChunkEmbedding.embedding.cosine_distance(query_vector).label("distance")
    return (
        select(KnowledgeChunk.id, distance)
        .select_from(KnowledgeChunk)
        .join(
            ChunkEmbedding,
            (ChunkEmbedding.org_id == KnowledgeChunk.org_id)
            & (ChunkEmbedding.project_id == KnowledgeChunk.project_id)
            & (ChunkEmbedding.resource_id == KnowledgeChunk.resource_id)
            & (ChunkEmbedding.resource_version_id == KnowledgeChunk.resource_version_id)
            & (ChunkEmbedding.chunk_id == KnowledgeChunk.id),
        )
        .join(
            EmbeddingProfile,
            (EmbeddingProfile.id == ChunkEmbedding.embedding_profile_id)
            & (EmbeddingProfile.scope_org_id == ChunkEmbedding.embedding_profile_scope_org_id),
        )
        .join(
            KnowledgeResourceVersion,
            (KnowledgeResourceVersion.org_id == KnowledgeChunk.org_id)
            & (KnowledgeResourceVersion.project_id == KnowledgeChunk.project_id)
            & (KnowledgeResourceVersion.resource_id == KnowledgeChunk.resource_id)
            & (KnowledgeResourceVersion.id == KnowledgeChunk.resource_version_id),
        )
        .join(
            KnowledgeResource,
            (KnowledgeResource.org_id == KnowledgeResourceVersion.org_id)
            & (KnowledgeResource.project_id == KnowledgeResourceVersion.project_id)
            & (KnowledgeResource.id == KnowledgeResourceVersion.resource_id),
        )
        .where(
            *_authorized_current_chunks(
                org_id=org_id,
                project_id=project_id,
                access_filter=access_filter,
            ),
            ChunkEmbedding.embedding_profile_id == embedding_profile_id,
            ChunkEmbedding.embedding_profile_scope_org_id == embedding_profile_scope_org_id,
        )
        .order_by(distance, KnowledgeChunk.id)
        .limit(candidate_limit)
    )


def vector_candidates(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    query_vector: list[float],
    embedding_profile_id: UUID,
    embedding_profile_scope_org_id: UUID,
    access_filter: ColumnElement[bool],
    candidate_limit: int = SEARCH_CANDIDATE_LIMIT,
) -> list[RankedCandidate]:
    rows = session.execute(
        vector_statement(
            org_id=org_id,
            project_id=project_id,
            query_vector=query_vector,
            embedding_profile_id=embedding_profile_id,
            embedding_profile_scope_org_id=embedding_profile_scope_org_id,
            access_filter=access_filter,
            candidate_limit=candidate_limit,
        )
    ).all()
    return [RankedCandidate(chunk_id=row[0], rank=rank) for rank, row in enumerate(rows, 1)]


def load_citations(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    chunk_ids: list[UUID],
    access_filter: ColumnElement[bool],
) -> list[SearchCitationRecord]:
    if not chunk_ids:
        return []
    ordering = case({chunk_id: index for index, chunk_id in enumerate(chunk_ids)}, value=KnowledgeChunk.id)
    rows = session.execute(
        select(KnowledgeResource, KnowledgeResourceVersion, KnowledgeChunk)
        .select_from(KnowledgeChunk)
        .join(
            KnowledgeResourceVersion,
            (KnowledgeResourceVersion.org_id == KnowledgeChunk.org_id)
            & (KnowledgeResourceVersion.project_id == KnowledgeChunk.project_id)
            & (KnowledgeResourceVersion.resource_id == KnowledgeChunk.resource_id)
            & (KnowledgeResourceVersion.id == KnowledgeChunk.resource_version_id),
        )
        .join(
            KnowledgeResource,
            (KnowledgeResource.org_id == KnowledgeResourceVersion.org_id)
            & (KnowledgeResource.project_id == KnowledgeResourceVersion.project_id)
            & (KnowledgeResource.id == KnowledgeResourceVersion.resource_id),
        )
        .where(
            *_authorized_current_chunks(
                org_id=org_id,
                project_id=project_id,
                access_filter=access_filter,
            ),
            KnowledgeChunk.id.in_(chunk_ids),
        )
        .order_by(ordering)
    ).all()
    return [
        SearchCitationRecord(
            resource_id=resource.id,
            resource_version_id=version.id,
            chunk_id=chunk.id,
            title=resource.title,
            media_type=version.media_type,
            excerpt=chunk.text,
            locator=cast(dict[str, object], chunk.locator),
        )
        for resource, version, chunk in rows
    ]


__all__ = [
    "SEARCH_CANDIDATE_LIMIT",
    "RankedCandidate",
    "SearchCitationRecord",
    "get_active_embedding_profile",
    "lexical_candidates",
    "lexical_statement",
    "load_citations",
    "vector_candidates",
    "vector_statement",
]
