"""Lifecycle migration facts survive safety checks and reject invalid rows."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from psycopg.errors import CheckViolation
from sqlalchemy import Engine, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from .authorization_helpers import seed_actor
from .knowledge_helpers import seed_project


@pytest.mark.integration
def test_lifecycle_migration_columns_constraints_and_due_index(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    source_columns = {item["name"]: item for item in inspector.get_columns("knowledge_sources")}
    assert set(source_columns) >= {
        "sync_interval_seconds", "next_sync_at", "last_schedule_attempt_at", "last_checked_at", "last_success_at",
        "last_error_code", "access_state", "generation",
    }
    sync_columns = {item["name"]: item for item in inspector.get_columns("knowledge_source_syncs")}
    assert set(sync_columns) >= {"source_generation", "trigger", "failure_code"}
    assert sync_columns["requested_by"]["nullable"] is True
    assert {item["name"] for item in inspector.get_check_constraints("knowledge_sources")} >= {
        "ck_knowledge_sources_access_state_values", "ck_knowledge_sources_generation_positive",
        "ck_knowledge_sources_sync_interval_range", "ck_knowledge_sources_next_sync_enabled",
    }
    assert {item["name"] for item in inspector.get_check_constraints("knowledge_source_syncs")} >= {
        "ck_knowledge_source_syncs_source_generation_positive",
        "ck_knowledge_source_syncs_trigger_values",
    }
    assert "ix_knowledge_sources_due" in {item["name"] for item in inspector.get_indexes("knowledge_sources")}
    assert "ix_knowledge_sources_due_attempt" in {item["name"] for item in inspector.get_indexes("knowledge_sources")}


@pytest.mark.integration
@pytest.mark.parametrize("column,value,constraint", [
    ("sync_interval_seconds", 299, "ck_knowledge_sources_sync_interval_range"),
    ("sync_interval_seconds", 604801, "ck_knowledge_sources_sync_interval_range"),
    ("access_state", "secret", "ck_knowledge_sources_access_state_values"),
    ("generation", 0, "ck_knowledge_sources_generation_positive"),
    ("next_sync_at", datetime.now(UTC), "ck_knowledge_sources_next_sync_enabled"),
])
def test_lifecycle_source_constraints_reject_invalid_updates(
    database: Database, column: str, value: object, constraint: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with database.session_factory.begin() as session:
        source = KnowledgeSource(org_id=actor.organization_id, project_id=project_id,
            name="Doc", external_id="DocSync1", credential_ref="team", access_policy="project_members")
        session.add(source)
        session.flush()
        source_id = source.id
    with database.session_factory.begin() as session:
        with pytest.raises(IntegrityError) as raised, session.begin_nested():
            session.execute(update(KnowledgeSource).where(KnowledgeSource.id == source_id).values({column: value}))
        assert isinstance(raised.value.orig, CheckViolation)
        assert raised.value.orig.diag.constraint_name == constraint


@pytest.mark.integration
def test_lifecycle_migration_refuses_downgrade_with_nondefault_facts(
    database: Database, test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with database.session_factory.begin() as session:
        source = KnowledgeSource(org_id=actor.organization_id, project_id=project_id,
            name="Doc", external_id="DocSync1", credential_ref="team", access_policy="project_members",
            sync_interval_seconds=300, next_sync_at=datetime.now(UTC))
        session.add(source)
        session.flush()
        source_id = source.id
        session.add(KnowledgeSourceSync(org_id=actor.organization_id, project_id=project_id,
            source_id=source_id, requested_by=None, trigger="scheduled", source_generation=1))
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="cannot downgrade while Feishu lifecycle facts exist"):
        command.downgrade(config, "0008_project_event_commit_order")
    with database.session_factory() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()
        assert session.scalar(select(KnowledgeSource.sync_interval_seconds).where(KnowledgeSource.id == source_id)) == 300
        assert session.scalar(select(KnowledgeSourceSync.trigger)) == "scheduled"


@pytest.mark.integration
def test_upgrade_preserves_legacy_shared_visibility_without_inventing_check_time(
    database: Database, test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source_id = uuid4()
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.downgrade(config, "0008_project_event_commit_order")
    try:
        with database.session_factory.begin() as session:
            session.execute(text("INSERT INTO knowledge_sources (id,org_id,project_id,provider,name,external_id,credential_ref,access_policy,status) VALUES (:id,:org,:project,'feishu','Legacy','DocSync1','team','project_members','configured')"),
                {"id": source_id, "org": actor.organization_id, "project": project_id})
        command.upgrade(config, "head")
        with database.session_factory() as session:
            source = session.get(KnowledgeSource, source_id)
            assert source is not None
            assert source.access_state == "available" and source.generation == 1
            assert source.last_checked_at is None and source.last_success_at is None
            assert source.sync_interval_seconds is None and source.next_sync_at is None
            assert source.last_schedule_attempt_at is None
    finally:
        command.upgrade(config, "head")


@pytest.mark.integration
def test_downgrade_retains_schedule_attempt_fact_even_without_period(
    database: Database, test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with database.session_factory.begin() as session:
        source = KnowledgeSource(org_id=actor.organization_id, project_id=project_id,
            name="Legacy-looking", external_id="DocSync1", credential_ref="team",
            access_policy="project_members", access_state="available",
            last_schedule_attempt_at=datetime.now(UTC))
        session.add(source)
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="cannot downgrade while Feishu lifecycle facts exist"):
        command.downgrade(config, "0008_project_event_commit_order")
    with database.session_factory() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()
        assert session.get(KnowledgeSource, source.id) is not None
