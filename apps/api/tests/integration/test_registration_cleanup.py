from datetime import UTC, datetime

import pytest
from cairn_api.db.session import Database
from cairn_api.maintenance.auth_cleanup import cleanup_auth_state
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from .test_registration_api import register
from .test_registration_api import registration_client as client_fixture

registration_client = client_fixture


@pytest.mark.integration
def test_cleanup_removes_sensitive_expired_consumed_state_and_old_scoped_limits(
    registration_client: TestClient, database: Database, migrated_engine: Engine
) -> None:
    del migrated_engine
    register(registration_client)
    register(registration_client, "consumed@example.com")
    register(registration_client, "live@example.com")
    with database.session_factory.begin() as session:
        session.execute(
            text(
                "UPDATE pending_registrations SET expires_at = now() - interval '1 second' WHERE email = 'new@example.com'"
            )
        )
        session.execute(
            text(
                "UPDATE pending_registrations SET consumed_at = now() WHERE email = 'consumed@example.com'"
            )
        )
        session.execute(
            text(
                "UPDATE registration_rate_limits SET expires_at = now() - interval '1 second' WHERE purpose = 'send_ip'"
            )
        )
    counts = cleanup_auth_state(
        database.session_factory, now=lambda: datetime.now(UTC), batch_size=1
    )
    assert counts.registrations_deleted == 2
    assert counts.registration_rate_limits_deleted == 1
    with database.session_factory() as session:
        assert session.scalars(text("SELECT email FROM pending_registrations")).all() == [
            "live@example.com"
        ]
        assert (
            session.scalar(
                text("SELECT count(*) FROM registration_rate_limits WHERE purpose = 'send_ip'")
            )
            == 0
        )
        assert (
            session.scalar(
                text("SELECT count(*) FROM registration_rate_limits WHERE purpose = 'send_email'")
            )
            == 3
        )
