from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, MetaData, Table, create_engine, inspect, select, text

KNOWLEDGE_TABLES = {
    "ingestion_batches",
    "upload_sessions",
    "ingestion_items",
    "knowledge_resources",
    "knowledge_resource_versions",
    "ingestion_jobs",
    "ingestion_job_attempts",
    "knowledge_chunks",
    "embedding_profiles",
    "chunk_embeddings",
    "search_rate_limit_buckets",
}


@pytest.mark.integration
def test_knowledge_migration_creates_extensions_and_all_tenant_tables(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert set(inspector.get_table_names()) >= KNOWLEDGE_TABLES

    with migrated_engine.connect() as connection:
        extensions = set(
            connection.scalars(
                text("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')")
            )
        )
    assert extensions == {"vector", "pg_trgm"}

    for table_name in KNOWLEDGE_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert "org_id" in columns, table_name
        if table_name not in {"embedding_profiles", "search_rate_limit_buckets"}:
            assert "project_id" in columns, table_name


@pytest.mark.integration
def test_knowledge_migration_exposes_stable_status_and_safety_constraints(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    expected = {
        "ingestion_batches": {
            "ck_ingestion_batches_status_values",
            "ck_ingestion_batches_nonnegative_counts",
            "ck_ingestion_batches_count_bounds",
            "ck_ingestion_batches_completion_state",
        },
        "upload_sessions": {
            "ck_upload_sessions_sha256_format",
            "ck_upload_sessions_positive_size",
            "ck_upload_sessions_completion_state",
        },
        "ingestion_items": {
            "ck_ingestion_items_status_values",
            "ck_ingestion_items_sha256_format",
            "ck_ingestion_items_result_state",
            "ck_ingestion_items_error_code_values",
        },
        "knowledge_resources": {
            "ck_knowledge_resources_source_type_values",
            "ck_knowledge_resources_deletion_actor",
            "ck_knowledge_resources_purge_order",
        },
        "knowledge_resource_versions": {
            "ck_knowledge_resource_versions_status_values",
            "ck_knowledge_resource_versions_sha256_format",
            "ck_knowledge_resource_versions_result_state",
            "ck_knowledge_resource_versions_error_code_values",
            "ck_knowledge_resource_versions_ready_order",
        },
        "ingestion_jobs": {
            "ck_ingestion_jobs_kind_values",
            "ck_ingestion_jobs_status_values",
            "ck_ingestion_jobs_attempt_bounds",
            "ck_ingestion_jobs_lease_state",
            "ck_ingestion_jobs_lease_order",
            "ck_ingestion_jobs_error_code_values",
        },
        "ingestion_job_attempts": {
            "ck_ingestion_job_attempts_trigger_values",
            "ck_ingestion_job_attempts_status_values",
            "ck_ingestion_job_attempts_result_state",
            "ck_ingestion_job_attempts_start_order",
            "ck_ingestion_job_attempts_completion_order",
            "ck_ingestion_job_attempts_error_code_values",
        },
        "embedding_profiles": {
            "ck_embedding_profiles_status_values",
            "ck_embedding_profiles_distance_metric_values",
            "ck_embedding_profiles_positive_dimensions",
        },
        "chunk_embeddings": {"ck_chunk_embeddings_profile_scope_values"},
        "search_rate_limit_buckets": {
            "ck_search_rate_limit_buckets_subject_type_values",
            "ck_search_rate_limit_buckets_nonnegative_count",
        },
    }
    for table_name, names in expected.items():
        actual = {constraint["name"] for constraint in inspector.get_check_constraints(table_name)}
        assert actual >= names, table_name


@pytest.mark.integration
def test_knowledge_migration_builds_idempotency_and_search_indexes(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    upload_uniques = inspector.get_unique_constraints("upload_sessions")
    assert any(item["column_names"] == ["object_key"] for item in upload_uniques)

    version_uniques = inspector.get_unique_constraints("knowledge_resource_versions")
    assert any(
        item["column_names"]
        == [
            "org_id",
            "source_type",
            "source_id",
            "external_id",
            "source_version",
        ]
        for item in version_uniques
    )

    job_uniques = inspector.get_unique_constraints("ingestion_jobs")
    assert any(
        item["column_names"] == ["job_kind", "target_id", "profile_version"] for item in job_uniques
    )

    chunk_indexes = {index["name"]: index for index in inspector.get_indexes("knowledge_chunks")}
    search_options = chunk_indexes["ix_knowledge_chunks_search_vector"].get("dialect_options", {})
    trigram_options = chunk_indexes["ix_knowledge_chunks_normalized_text_trgm"].get(
        "dialect_options", {}
    )
    assert search_options.get("postgresql_using") == "gin"
    assert trigram_options.get("postgresql_using") == "gin"
    assert trigram_options.get("postgresql_ops") == {"normalized_text": "gin_trgm_ops"}

    embedding_columns = {column["name"] for column in inspector.get_columns("chunk_embeddings")}
    assert "embedding_profile_scope_org_id" in embedding_columns
    embedding_foreign_keys = inspector.get_foreign_keys("chunk_embeddings")
    assert any(
        foreign_key["constrained_columns"]
        == ["embedding_profile_scope_org_id", "embedding_profile_id"]
        and foreign_key["referred_table"] == "embedding_profiles"
        and foreign_key["referred_columns"] == ["scope_org_id", "id"]
        for foreign_key in embedding_foreign_keys
    )

    with migrated_engine.connect() as connection:
        trigger_names = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgrelid IN ("
                    "'ingestion_batches'::regclass, 'ingestion_items'::regclass)"
                )
            )
        )
    assert trigger_names >= {
        "trg_ingestion_batches_derive_summary",
        "trg_ingestion_items_refresh_batch",
    }

    with migrated_engine.connect() as connection:
        attempt_trigger_names = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE NOT tgisinternal "
                    "AND tgrelid = 'ingestion_job_attempts'::regclass"
                )
            )
        )
    assert "trg_ingestion_job_attempts_preserve_history" in attempt_trigger_names

    profile_indexes = {
        index["name"]: index for index in inspector.get_indexes("embedding_profiles")
    }
    assert profile_indexes["uq_embedding_profiles_global_version"]["unique"] is True
    assert profile_indexes["uq_embedding_profiles_org_version"]["unique"] is True


@pytest.mark.integration
def test_knowledge_migration_seeds_secret_free_default_embedding_profile(
    migrated_engine: Engine,
) -> None:
    profiles = Table("embedding_profiles", MetaData(), autoload_with=migrated_engine)
    forbidden = {"api_key", "secret", "token", "credentials"}
    assert forbidden.isdisjoint(profiles.c.keys())

    with migrated_engine.connect() as connection:
        row = connection.execute(select(profiles).where(profiles.c.version == "default-v1")).one()

    assert row.id == UUID("00000000-0000-4000-8000-000000000501")
    assert row.org_id is None
    assert row.provider_key == "default"
    assert row.model == "text-embedding-v4"
    assert row.dimensions == 1024
    assert row.distance_metric == "cosine"
    assert row.status == "active"
    assert row.index_config == {"strategy": "exact", "candidateLimit": 50}


@pytest.mark.integration
def test_knowledge_migration_downgrades_to_acl_and_restores_head(
    test_database_url: str,
) -> None:
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    engine = create_engine(test_database_url, pool_pre_ping=True)
    try:
        command.upgrade(config, "head")
        try:
            command.downgrade(config, "0004_rbac_project_acl")
            assert KNOWLEDGE_TABLES.isdisjoint(inspect(engine).get_table_names())
        finally:
            command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) >= KNOWLEDGE_TABLES
    finally:
        engine.dispose()
