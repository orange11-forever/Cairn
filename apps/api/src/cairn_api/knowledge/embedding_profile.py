from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cairn_api.db.metadata import load_model_metadata
from cairn_api.knowledge.models import EmbeddingProfile, EmbeddingProfileStatus
from cairn_api.settings import Settings

PROFILE_VERSION = "default-v1"
CHUNKING_CONFIG: dict[str, object] = {
    "maxCodepoints": 1800,
    "overlapCodepoints": 180,
}
INDEX_CONFIG: dict[str, object] = {"strategy": "exact", "candidateLimit": 50}


def _compatible(profile: Any, settings: Settings) -> bool:
    return (
        profile.provider_key in {"default", settings.embedding_provider_key}
        and profile.model == settings.embedding_model
        and profile.dimensions == settings.embedding_dimensions
        and profile.distance_metric == "cosine"
        and profile.chunking_config == CHUNKING_CONFIG
        and profile.index_config == INDEX_CONFIG
        and profile.version == PROFILE_VERSION
    )


def bootstrap_embedding_profile(session: Session | Any, settings: Settings) -> bool:
    """Create or activate the first compatible global profile without rewriting one."""
    session.execute(text("LOCK TABLE embedding_profiles IN EXCLUSIVE MODE"))
    profiles = list(
        session.scalars(select(EmbeddingProfile).where(EmbeddingProfile.org_id.is_(None))).all()
    )
    active = next(
        (profile for profile in profiles if profile.status == EmbeddingProfileStatus.ACTIVE),
        None,
    )
    if active is not None:
        if not _compatible(active, settings):
            raise RuntimeError(
                "active global embedding profile is incompatible with configured provider, model, or dimensions"
            )
        return False
    version = next((profile for profile in profiles if profile.version == PROFILE_VERSION), None)
    if version is not None:
        if not _compatible(version, settings):
            raise RuntimeError(
                "existing global embedding profile version is incompatible; create a new version and rebuild vectors"
            )
        version.status = EmbeddingProfileStatus.ACTIVE
        return True
    session.add(
        EmbeddingProfile(
            org_id=None,
            provider_key=settings.embedding_provider_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            distance_metric="cosine",
            chunking_config=dict(CHUNKING_CONFIG),
            index_config=dict(INDEX_CONFIG),
            version=PROFILE_VERSION,
            status=EmbeddingProfileStatus.ACTIVE,
        )
    )
    return True


def run_embedding_profile_bootstrap(settings: Settings) -> int:
    from cairn_api.db.session import Database

    load_model_metadata()
    database = Database(settings.database_url)
    try:
        with database.session_factory.begin() as session:
            changed = bootstrap_embedding_profile(session, settings)
        print("Embedding profile ready" + (" (created or activated)" if changed else ""))
        return 0
    finally:
        database.dispose()


__all__ = ["bootstrap_embedding_profile", "run_embedding_profile_bootstrap"]
