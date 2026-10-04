import pytest
from alembic import command
from alembic.config import Config
from cairn_api.auth.oauth_models import ExternalIdentity
from cairn_api.db.session import Database
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from sqlalchemy import Engine, text


@pytest.mark.integration
def test_oauth_downgrade_refuses_to_destroy_linked_identities(
    database: Database, migrated_engine: Engine, test_database_url: str
) -> None:
    del migrated_engine
    from uuid import UUID

    seed_demo_identity(Settings(database_url=test_database_url, _env_file=None), database)  # pyright: ignore[reportCallIssue]
    with database.session_factory.begin() as session:
        session.add(
            ExternalIdentity(
                user_id=UUID("00000000-0000-4000-8000-000000001001"),
                provider="github",
                client_id="test",
                subject="remote",
            )
        )
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    try:
        with pytest.raises(RuntimeError, match="OAuth identities or passwordless users exist"):
            command.downgrade(config, "0009_feishu_lifecycle")
        with database.session_factory() as session:
            assert (
                session.scalar(text("SELECT version_num FROM alembic_version"))
                == "0012_native_registration"
            )
            assert session.scalar(text("SELECT count(*) FROM external_identities")) == 1
    finally:
        command.upgrade(config, "head")


@pytest.mark.integration
def test_registration_downgrade_preserves_nullable_user_and_email_uniqueness(
    database: Database, migrated_engine: Engine, test_database_url: str
) -> None:
    from uuid import uuid4

    from cairn_api.auth.models import User
    from sqlalchemy.exc import IntegrityError

    del migrated_engine
    settings = Settings(database_url=test_database_url, _env_file=None)  # pyright: ignore[reportCallIssue]
    seed_demo_identity(settings, database)
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    user_ids = [uuid4(), uuid4()]
    with database.session_factory.begin() as session:
        session.add_all(
            User(id=user_id, email=None, normalized_email=None, password_hash=None)
            for user_id in user_ids
        )
    try:
        with pytest.raises(RuntimeError, match="OAuth users without email exist"):
            command.downgrade(config, "0010_oauth_identities")
        with database.session_factory() as session:
            assert (
                session.scalar(text("SELECT version_num FROM alembic_version"))
                == "0012_native_registration"
            )
            assert session.scalar(text("SELECT count(*) FROM users WHERE email IS NULL")) == 2
        with pytest.raises(IntegrityError), database.session_factory.begin() as session:
            session.add(
                User(email="demo@cairn.dev", normalized_email="demo@cairn.dev", password_hash=None)
            )
        with database.session_factory.begin() as session:
            session.execute(text("DELETE FROM users WHERE email IS NULL"))
        command.downgrade(config, "0010_oauth_identities")
        command.upgrade(config, "head")
        with database.session_factory() as session:
            assert session.scalar(text("SELECT email FROM users")) == "demo@cairn.dev"
    finally:
        command.upgrade(config, "head")


@pytest.mark.integration
@pytest.mark.parametrize(
    "pending",
    [
        {"provider": None, "client": "test", "subject": "remote"},
        {"provider": "github", "client": None, "subject": "remote"},
        {"provider": "other", "client": "test", "subject": "remote"},
    ],
)
def test_pending_registration_constraint_rejects_incomplete_or_unknown_identity(
    database: Database, migrated_engine: Engine, pending: dict[str, str | None]
) -> None:
    from sqlalchemy.exc import IntegrityError

    del migrated_engine
    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO browser_login_claims (token_digest, expires_at, pending_provider, pending_client_id, pending_subject) "
                "VALUES (:digest, now() + interval '5 minutes', :provider, :client, :subject)"
            ),
            {"digest": b"x" * 32, **pending},
        )
