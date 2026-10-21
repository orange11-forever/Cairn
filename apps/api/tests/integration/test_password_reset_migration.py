import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text


@pytest.mark.integration
def test_password_reset_downgrade_refuses_live_limits_and_removes_expired_limits(
    migrated_engine: Engine, test_database_url: str
) -> None:
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO registration_rate_limits (purpose, key_digest, attempt_count, expires_at) "
                "VALUES ('reset_email', decode(repeat('a', 64), 'hex'), 1, now() + interval '1 hour')"
            )
        )
    try:
        with pytest.raises(RuntimeError, match="live password reset rate limits"):
            command.downgrade(config, "0019_multiple_assistants")
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0020_password_reset"
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM registration_rate_limits WHERE purpose = 'reset_email'"
                    )
                )
                == 1
            )
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE registration_rate_limits SET expires_at = now() - interval '1 second' WHERE purpose = 'reset_email'"
                )
            )
        command.downgrade(config, "0019_multiple_assistants")
        with migrated_engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM registration_rate_limits")) == 0
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0019_multiple_assistants"
            )
    finally:
        command.upgrade(config, "head")
