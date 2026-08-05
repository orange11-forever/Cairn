from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthRateLimit, AuthSession, User
from cairn_api.db.session import Database
from cairn_api.maintenance.auth_cleanup import CleanupCounts, cleanup_auth_state
from cairn_api.organizations.models import Membership, Organization
from sqlalchemy import Engine, select


@pytest.mark.integration
def test_auth_cleanup_removes_only_expired_state_and_is_idempotent(
    database: Database,
    migrated_engine: Engine,
) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    with database.session_factory.begin() as session:
        organization = Organization(id=uuid4(), slug="cleanup-org", name="Cleanup Org")
        user = User(
            id=uuid4(),
            email="cleanup@example.com",
            normalized_email="cleanup@example.com",
            password_hash="not-used",
        )
        session.add_all([organization, user])
        session.flush()
        session.add(Membership(org_id=organization.id, user_id=user.id, role="member"))
        session.flush()
        expired_session = AuthSession(
            id=uuid4(),
            org_id=organization.id,
            user_id=user.id,
            token_digest=b"e" * 32,
            csrf_digest=b"c" * 32,
            expires_at=now - timedelta(seconds=1),
        )
        revoked_session = AuthSession(
            id=uuid4(),
            org_id=organization.id,
            user_id=user.id,
            token_digest=b"r" * 32,
            csrf_digest=b"c" * 32,
            expires_at=now + timedelta(days=1),
            revoked_at=now,
        )
        active_session = AuthSession(
            id=uuid4(),
            org_id=organization.id,
            user_id=user.id,
            token_digest=b"a" * 32,
            csrf_digest=b"c" * 32,
            expires_at=now + timedelta(days=1),
        )
        session.add_all([expired_session, revoked_session, active_session])
        session.flush()
        session.add_all(
            [
                AuthRateLimit(
                    bucket_type="email",
                    key_digest=b"e" * 32,
                    failure_count=1,
                    window_started_at=now - timedelta(minutes=15),
                ),
                AuthRateLimit(
                    bucket_type="ip",
                    key_digest=b"r" * 32,
                    failure_count=5,
                    window_started_at=now - timedelta(minutes=15),
                    blocked_until=now,
                ),
                AuthRateLimit(
                    bucket_type="email",
                    key_digest=b"a" * 32,
                    failure_count=1,
                    window_started_at=now - timedelta(minutes=14),
                ),
                AuthRateLimit(
                    bucket_type="ip",
                    key_digest=b"b" * 32,
                    failure_count=30,
                    window_started_at=now - timedelta(minutes=1),
                    blocked_until=now + timedelta(minutes=14),
                ),
            ]
        )
        session.add(
            AuditLog(
                actor_type="user",
                actor_id=user.id,
                org_id=organization.id,
                action="auth.login_succeeded",
                resource_type="session",
                resource_id=expired_session.id,
                trace_id="cleanup-audit",
                details={},
            )
        )

    result = cleanup_auth_state(database.session_factory, now=lambda: now)

    assert result == CleanupCounts(sessions_deleted=2, rate_limits_deleted=2)
    with database.session_factory() as session:
        assert session.scalar(select(AuthSession.id).where(AuthSession.id == expired_session.id)) is None
        assert session.scalar(select(AuthSession.id).where(AuthSession.id == revoked_session.id)) is None
        assert session.scalar(select(AuthSession.id).where(AuthSession.id == active_session.id)) == active_session.id
        assert session.scalars(select(AuthRateLimit.key_digest).order_by(AuthRateLimit.key_digest)).all() == [
            b"a" * 32,
            b"b" * 32,
        ]
        assert session.scalar(select(AuditLog.id).where(AuditLog.trace_id == "cleanup-audit")) is not None

    assert cleanup_auth_state(database.session_factory, now=lambda: now) == CleanupCounts()
