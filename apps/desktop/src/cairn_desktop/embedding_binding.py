"""Bind the desktop's fixed default-v1 profile before any API/worker starts."""

import hashlib
import re
from uuid import UUID

from cairn_api.knowledge.embedding_profile import CHUNKING_CONFIG, INDEX_CONFIG, PROFILE_VERSION
from cairn_api.knowledge.models import (
    ChunkEmbedding,
    EmbeddingProfile,
    KnowledgeResource,
    KnowledgeResourceVersion,
)
from sqlalchemy import exists, or_, select, text
from sqlalchemy.orm import Session

from cairn_desktop.models import EmbeddingConnection, ModelSettingsError

DEFAULT_PROFILE_ID = UUID("00000000-0000-4000-8000-000000000501")


def embedding_identity(connection: EmbeddingConnection) -> str:
    endpoint = str(connection.base_url).rstrip("/") + "/embeddings"
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def bind_embedding_profile(
    session: Session, connection: EmbeddingConnection | None, *, apply: bool = True
) -> EmbeddingProfile:
    # DataLock is held by the caller. This same profile lock also excludes an
    # index publication while checking historical vectors and published versions.
    session.execute(text("LOCK TABLE embedding_profiles IN EXCLUSIVE MODE"))
    profiles = list(session.scalars(select(EmbeddingProfile)))
    if len(profiles) != 1:
        raise ModelSettingsError(
            "此桌面数据包含额外或组织级索引配置，不符合默认索引契约；未修改模型配置或数据。"
        )
    profile = profiles[0]
    bound = bool(re.fullmatch(r"[0-9a-f]{64}", profile.provider_key))
    if not (
        profile.id == DEFAULT_PROFILE_ID
        and profile.org_id is None
        and profile.version == PROFILE_VERSION
        and profile.dimensions == 1024
        and profile.distance_metric == "cosine"
        and profile.status == "active"
        and profile.chunking_config == CHUNKING_CONFIG
        and profile.index_config == INDEX_CONFIG
        and (bound or (profile.provider_key == "default" and profile.model == "text-embedding-v4"))
    ):
        raise ModelSettingsError(
            "当前索引不符合桌面默认索引契约（default-v1、1024维、cosine）；未修改模型配置或数据。"
        )
    if connection is None:
        return profile
    identity = embedding_identity(connection)
    published = session.scalar(
        select(
            or_(
                exists().where(ChunkEmbedding.id.is_not(None)),
                exists().where(KnowledgeResourceVersion.status == "ready"),
                exists().where(KnowledgeResource.current_version_id.is_not(None)),
            )
        )
    )
    if published and (
        not bound or profile.provider_key != identity or profile.model != connection.model
    ):
        raise ModelSettingsError(
            "embedding.baseUrl/model：已存在索引，服务地址和模型必须与原绑定保持一致；仅可更换API Key。原配置和数据未修改。"
        )
    if apply and (profile.provider_key != identity or profile.model != connection.model):
        profile.provider_key = identity
        profile.model = connection.model
        session.flush()
    return profile
