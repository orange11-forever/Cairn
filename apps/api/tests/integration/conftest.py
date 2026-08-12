import os
from collections.abc import Generator

import pytest
from cairn_api.db.session import Database
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url


def _validated_test_url() -> str:
    value = os.environ.get("CAIRN_TEST_DATABASE_URL")
    if not value:
        pytest.skip("CAIRN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    parsed = make_url(value)
    if parsed.get_backend_name() != "postgresql" or parsed.get_driver_name() != "psycopg":
        pytest.fail("CAIRN_TEST_DATABASE_URL must use postgresql+psycopg")
    if parsed.database != "cairn_test":
        pytest.fail("integration tests require the database name cairn_test")
    return value


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return _validated_test_url()


@pytest.fixture(scope="session")
def migrated_engine(test_database_url: str) -> Generator[Engine, None, None]:
    from alembic import command
    from alembic.config import Config

    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.upgrade(config, "head")
    engine = create_engine(test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def migrated_connection(migrated_engine: Engine) -> Generator[Connection, None, None]:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture(scope="session")
def database(
    test_database_url: str,
    migrated_engine: Engine,
) -> Generator[Database, None, None]:
    del migrated_engine
    instance = Database(test_database_url)
    try:
        yield instance
    finally:
        instance.dispose()


@pytest.fixture(autouse=True)
def cleanup_identity_rows(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    yield
    if not {"migrated_connection", "migrated_engine"}.intersection(request.fixturenames):
        return
    test_database_url = request.getfixturevalue("test_database_url")
    assert make_url(test_database_url).database == "cairn_test"
    engine = request.getfixturevalue("migrated_engine")
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE chunk_embeddings, knowledge_chunks, "
                "ingestion_job_attempts, ingestion_jobs, upload_sessions, "
                "ingestion_items, knowledge_resource_versions, knowledge_resources, "
                "ingestion_batches, search_rate_limit_buckets, "
                "resource_acl_entries, outbox_events, task_dependencies, "
                "tasks, milestones, project_stages, projects, auth_rate_limits, "
                "audit_logs, auth_sessions, memberships, users, organizations CASCADE"
            )
        )
        connection.execute(
            text(
                "INSERT INTO embedding_profiles ("
                "id, org_id, provider_key, model, dimensions, distance_metric, "
                "chunking_config, index_config, version, status"
                ") VALUES ("
                "'00000000-0000-4000-8000-000000000501', NULL, 'default', "
                "'text-embedding-v4', 1024, 'cosine', "
                '\'{"maxCodepoints": 1800, "overlapCodepoints": 180}\'::jsonb, '
                '\'{"strategy": "exact", "candidateLimit": 50}\'::jsonb, '
                "'default-v1', 'active'"
                ") ON CONFLICT (version) WHERE org_id IS NULL DO NOTHING"
            )
        )
