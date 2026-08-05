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
    test_database_url: str,
) -> Generator[None, None, None]:
    yield
    if not {"migrated_connection", "migrated_engine"}.intersection(request.fixturenames):
        return
    assert make_url(test_database_url).database == "cairn_test"
    engine = request.getfixturevalue("migrated_engine")
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE auth_rate_limits, audit_logs, auth_sessions, memberships, "
                "users, organizations CASCADE"
            )
        )
