from uuid import UUID, uuid4

import pytest
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.models import EmbeddingProfile
from cairn_desktop.embedding_binding import bind_embedding_profile, embedding_identity
from cairn_desktop.models import EmbeddingConnection, ModelSettingsError
from sqlalchemy import delete, select

from apps.api.tests.integration.authorization_helpers import seed_actor
from apps.api.tests.integration.knowledge_helpers import seed_project
from apps.api.tests.integration.test_knowledge_search import seed_search_resource

DEFAULT = UUID("00000000-0000-4000-8000-000000000501")


def connection(address="http://localhost:11434/v1", model="desktop-index", key="test-placeholder"):
    return EmbeddingConnection(baseUrl=address, model=model, apiKey=key)


@pytest.fixture
def profile(database: Database):
    with database.session_factory.begin() as session:
        original = session.get(EmbeddingProfile, DEFAULT)
        if original is None:
            original = EmbeddingProfile(
                id=DEFAULT,
                org_id=None,
                provider_key="default",
                model="text-embedding-v4",
                dimensions=1024,
                distance_metric="cosine",
                chunking_config={"maxCodepoints": 1800, "overlapCodepoints": 180},
                index_config={"strategy": "exact", "candidateLimit": 50},
                version="default-v1",
                status="active",
            )
            session.add(original)
            session.flush()
        retained = {
            name: getattr(original, name)
            for name in (
                "provider_key",
                "model",
                "dimensions",
                "distance_metric",
                "chunking_config",
                "index_config",
                "version",
                "status",
            )
        }
        ids = set(session.scalars(select(EmbeddingProfile.id)))
    yield
    with database.session_factory.begin() as session:
        session.execute(delete(EmbeddingProfile).where(EmbeddingProfile.id.not_in(ids)))
        row = session.get(EmbeddingProfile, DEFAULT)
        assert row is not None
        for name, value in retained.items():
            setattr(row, name, value)


def bind(database, config, apply=True):
    with database.session_factory.begin() as session:
        return bind_embedding_profile(session, config, apply=apply)


@pytest.mark.integration
def test_first_binding_and_empty_project_correction_preserve_default_profile_contract(
    database: Database, profile
):
    first = connection()
    bind(database, first)
    assert embedding_identity(first) == embedding_identity(connection("http://LOCALHOST:11434/v1/"))
    assert len(embedding_identity(first)) == 64
    bind(database, connection("http://localhost:9001/api", model="corrected-model"))
    with database.session_factory() as session:
        row = session.get(EmbeddingProfile, DEFAULT)
        assert row is not None
        assert row.provider_key == embedding_identity(
            connection("http://localhost:9001/api", model="corrected-model")
        )
        assert (
            row.model == "corrected-model"
            and row.version == "default-v1"
            and row.dimensions == 1024
        )
        assert row.chunking_config == {"maxCodepoints": 1800, "overlapCodepoints": 180}
        assert row.index_config == {"strategy": "exact", "candidateLimit": 50}


@pytest.mark.integration
@pytest.mark.parametrize("signal", ["historical_vector", "ready", "current"])
@pytest.mark.parametrize("change", ["endpoint", "model"])
def test_any_existing_index_signal_locks_endpoint_and_model_even_for_old_versions(
    database: Database, profile, signal, change
):
    first = connection()
    bind(database, first)
    actor = seed_actor(database, MembershipRole.MEMBER)
    pid = seed_project(database, actor, permission="read")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=pid,
        title="old.txt",
        chunks=[(uuid4(), "old", [1.0] + [0.0] * 1023)] if signal == "historical_vector" else [],
        current=signal == "current",
        ready=signal == "ready",
    )
    requested = (
        connection("http://localhost:9002/v1")
        if change == "endpoint"
        else connection(model="another-model")
    )
    with pytest.raises(ModelSettingsError, match="已存在索引"):
        bind(database, requested, apply=False)
    with database.session_factory() as session:
        row = session.get(EmbeddingProfile, DEFAULT)
        assert (
            row is not None
            and row.provider_key == embedding_identity(first)
            and row.model == first.model
        )
    bind(database, connection(key="rotated-key"))
    bind(database, None)
    with database.session_factory() as session:
        row = session.get(EmbeddingProfile, DEFAULT)
        assert (
            row is not None
            and row.model == first.model
            and row.provider_key == embedding_identity(first)
        )


@pytest.mark.integration
def test_unbound_legacy_vectors_cannot_be_claimed_by_desktop_configuration(
    database: Database, profile
):
    actor = seed_actor(database, MembershipRole.MEMBER)
    pid = seed_project(database, actor, permission="read")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=pid,
        title="legacy.txt",
        chunks=[],
        current=False,
        ready=True,
    )
    with pytest.raises(ModelSettingsError, match="已存在索引"):
        bind(database, connection(model="text-embedding-v4"))
    with database.session_factory() as session:
        row = session.get(EmbeddingProfile, DEFAULT)
        assert row is not None and row.provider_key == "default"
    bind(database, None)


@pytest.mark.integration
@pytest.mark.parametrize("invalid", ["extra", "organization", "dimensions", "chunking"])
def test_desktop_rejects_other_profiles_and_incompatible_default_contract(
    database: Database, profile, invalid
):
    with database.session_factory.begin() as session:
        row = session.get(EmbeddingProfile, DEFAULT)
        assert row is not None
        if invalid in {"extra", "organization"}:
            actor = (
                seed_actor(database, MembershipRole.MEMBER) if invalid == "organization" else None
            )
            session.add(
                EmbeddingProfile(
                    org_id=actor.organization_id if actor else None,
                    provider_key="default",
                    model="m",
                    dimensions=1024,
                    version="other",
                    status="inactive",
                )
            )
        elif invalid == "dimensions":
            row.dimensions = 768
        else:
            row.chunking_config = {"maxCodepoints": 100, "overlapCodepoints": 0}
    with pytest.raises(ModelSettingsError, match="默认索引契约"):
        bind(database, connection())
