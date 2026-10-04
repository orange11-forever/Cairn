from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from cairn_api.db.session import Database
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from .test_registration_api import register
from .test_registration_api import registration_client as client_fixture

registration_client = client_fixture


@pytest.mark.integration
def test_native_migration_preserves_legacy_accounts_and_refuses_live_proof_loss(
    registration_client: TestClient,
    database: Database,
    migrated_engine: Engine,
    test_database_url: str,
) -> None:
    del migrated_engine
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    register(registration_client)
    with database.session_factory() as session:
        before = tuple(
            session.execute(
                text(
                    "SELECT id, normalized_email, password_hash, is_active, email_verified_at FROM users"
                )
            ).one()
        )
        assert before[-1] is None
    try:
        with pytest.raises(RuntimeError, match="live pending email proofs"):
            command.downgrade(config, "0011_oauth_registration")
        with database.session_factory() as session:
            assert (
                session.scalar(text("SELECT version_num FROM alembic_version"))
                == "0012_native_registration"
            )
            assert session.scalar(text("SELECT count(*) FROM pending_registrations")) == 1
        with database.session_factory.begin() as session:
            session.execute(
                text("UPDATE pending_registrations SET expires_at = :expired"),
                {"expired": datetime(2020, 1, 1, tzinfo=UTC)},
            )
        command.downgrade(config, "0011_oauth_registration")
        command.upgrade(config, "head")
        with database.session_factory() as session:
            assert (
                tuple(
                    session.execute(
                        text(
                            "SELECT id, normalized_email, password_hash, is_active, email_verified_at FROM users"
                        )
                    ).one()
                )
                == before
            )
            assert session.scalar(text("SELECT count(*) FROM pending_registrations")) == 0
        # Existing seed and password login continue working after upgrade.
        seed_demo_identity(Settings(database_url=test_database_url, _env_file=None), database)  # pyright: ignore[reportCallIssue]
        assert (
            registration_client.post(
                "/api/v1/login",
                headers={"Origin": "http://localhost:5500"},
                json={"email": "demo@cairn.dev", "password": "cairn-demo-2026"},
            ).status_code
            == 200
        )
    finally:
        command.upgrade(config, "head")
