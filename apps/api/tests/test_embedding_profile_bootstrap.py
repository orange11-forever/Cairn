import sys
from subprocess import run
from types import SimpleNamespace
from typing import Any

import pytest
from cairn_api.knowledge.embedding_profile import bootstrap_embedding_profile
from cairn_api.settings import Settings


class FakeSession:
    def __init__(self, profiles: list[Any]) -> None:
        self.profiles = profiles
        self.added: list[Any] = []

    def execute(self, _statement: object) -> None:
        return None

    def scalars(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self.profiles)

    def add(self, profile: object) -> None:
        self.added.append(profile)


def compatible_profile(**overrides: object) -> Any:
    values: dict[str, Any] = {
        "org_id": None,
        "provider_key": "local-fake",
        "model": "text-embedding-v4",
        "dimensions": 1024,
        "distance_metric": "cosine",
        "chunking_config": {"maxCodepoints": 1800, "overlapCodepoints": 180},
        "index_config": {"strategy": "exact", "candidateLimit": 50},
        "version": "default-v1",
        "status": "active",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_profile_bootstrap_creates_first_global_profile() -> None:
    session = FakeSession([])
    assert bootstrap_embedding_profile(session, Settings()) is True
    assert len(session.added) == 1
    profile = session.added[0]
    assert (profile.provider_key, profile.model, profile.dimensions) == (
        "local-fake",
        "text-embedding-v4",
        1024,
    )


def test_profile_bootstrap_is_idempotent_for_compatible_active_profile() -> None:
    session = FakeSession([compatible_profile()])
    assert bootstrap_embedding_profile(session, Settings()) is False
    assert session.added == []


def test_profile_bootstrap_accepts_existing_default_provider_alias() -> None:
    session = FakeSession([compatible_profile(provider_key="default")])
    assert bootstrap_embedding_profile(session, Settings()) is False


def test_profile_bootstrap_refuses_incompatible_existing_profile() -> None:
    session = FakeSession([compatible_profile(dimensions=768)])
    with pytest.raises(RuntimeError, match="incompatible"):
        bootstrap_embedding_profile(session, Settings())
    assert session.added == []


def test_profile_bootstrap_activates_compatible_inactive_profile() -> None:
    profile = compatible_profile(status="inactive")
    session = FakeSession([profile])
    assert bootstrap_embedding_profile(session, Settings()) is True
    assert profile.status == "active"
    assert session.added == []


def test_profile_bootstrap_propagates_infrastructure_failure_without_writes() -> None:
    class FailedSession(FakeSession):
        def execute(self, _statement: object) -> None:
            raise OSError("database unavailable")

    session = FailedSession([])
    with pytest.raises(OSError, match="database unavailable"):
        bootstrap_embedding_profile(session, Settings())
    assert session.added == []


def test_standalone_profile_bootstrap_registers_complete_foreign_key_metadata() -> None:
    script = """
from contextlib import contextmanager
from types import SimpleNamespace

import cairn_api.db.session
from cairn_api.db.base import Base
from cairn_api.knowledge.embedding_profile import run_embedding_profile_bootstrap
from cairn_api.settings import Settings


class FakeSession:
    def execute(self, _statement):
        return None

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: [])

    def add(self, _profile):
        return None


class FakeSessionFactory:
    @contextmanager
    def begin(self):
        yield FakeSession()


class FakeDatabase:
    def __init__(self, _database_url):
        self.session_factory = FakeSessionFactory()

    def dispose(self):
        return None


cairn_api.db.session.Database = FakeDatabase
assert run_embedding_profile_bootstrap(Settings()) == 0
tables = {table.name for table in Base.metadata.sorted_tables}
required = {'users', 'organizations', 'projects', 'embedding_profiles'}
assert required <= tables, required - tables
for table in Base.metadata.sorted_tables:
    for foreign_key in table.foreign_keys:
        foreign_key.column
"""
    result = run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
