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
                == "0010_oauth_identities"
            )
            assert session.scalar(text("SELECT count(*) FROM external_identities")) == 1
    finally:
        command.upgrade(config, "head")
