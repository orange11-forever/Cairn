from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from cairn_api.auth.models import User
from cairn_api.auth.rate_limit_repository import BucketKey, BucketState
from cairn_api.auth.repository import MembershipRecord
from cairn_api.auth.security import DUMMY_PASSWORD_HASH
from cairn_api.auth.service import AuthService, RequestAuditContext
from cairn_api.errors import ApiProblem
from cairn_api.organizations.models import Membership, Organization
from cairn_api.settings import Settings
from sqlalchemy.orm import Session

AUDIT = RequestAuditContext(trace_id="req-login", ip="198.51.100.7", user_agent="test")
NOW = datetime(2026, 8, 5, tzinfo=UTC)


def test_restore_rejects_non_ascii_session_tokens_as_invalid() -> None:
    session = MagicMock(spec=Session)
    service = AuthService(
        session,
        Settings(_env_file=None),  # pyright: ignore[reportCallIssue]
    )

    with pytest.raises(ApiProblem) as raised:
        service.restore(
            session_token="\N{LATIN SMALL LETTER E WITH ACUTE}",
            audit=RequestAuditContext(trace_id="req-cookie", ip=None, user_agent=None),
        )

    assert raised.value.status_code == 401
    assert raised.value.code == "session_invalid"
    session.begin.assert_not_called()


def test_blocked_login_skips_user_and_password_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api.auth import rate_limit_repository, service

    session = MagicMock(spec=Session)
    blocked = BucketState("email", b"e" * 32, 5, NOW, NOW + timedelta(minutes=10))
    monkeypatch.setattr(
        rate_limit_repository.RateLimitRepository,
        "lock_buckets",
        MagicMock(return_value={BucketKey("email", b"e" * 32): blocked}),
    )
    user_lookup = MagicMock()
    password_check = MagicMock()
    monkeypatch.setattr(service, "get_user_by_normalized_email", user_lookup)
    monkeypatch.setattr(service, "verify_password", password_check)
    monkeypatch.setattr(service, "add_audit_log", MagicMock())

    with pytest.raises(ApiProblem) as raised:
        AuthService(session, Settings(_env_file=None)).login(  # pyright: ignore[reportCallIssue]
            email="blocked@example.com",
            password="wrong",
            audit=AUDIT,
            client_ip="198.51.100.7",
            now=lambda: NOW,
        )

    assert raised.value.status_code == 429
    assert raised.value.headers == {"Retry-After": "600"}
    user_lookup.assert_not_called()
    password_check.assert_not_called()


def test_unknown_user_uses_dummy_hash_and_records_both_failure_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api.auth import rate_limit_repository, service

    session = MagicMock(spec=Session)
    monkeypatch.setattr(rate_limit_repository.RateLimitRepository, "lock_buckets", MagicMock(return_value={}))
    monkeypatch.setattr(service, "get_user_by_normalized_email", MagicMock(return_value=None))
    password_check = MagicMock(return_value=False)
    monkeypatch.setattr(service, "verify_password", password_check)
    recorded: list[BucketKey] = []

    def record_failure(_session: Session, key: BucketKey, *, now: datetime) -> BucketState:
        recorded.append(key)
        return BucketState(key.bucket_type, key.key_digest, 1, now, None)

    monkeypatch.setattr(rate_limit_repository.RateLimitRepository, "record_failure", record_failure)
    monkeypatch.setattr(service, "add_audit_log", MagicMock())

    with pytest.raises(ApiProblem) as raised:
        AuthService(session, Settings(_env_file=None)).login(  # pyright: ignore[reportCallIssue]
            email="unknown@example.com",
            password="wrong",
            audit=AUDIT,
            client_ip="198.51.100.7",
            now=lambda: NOW,
        )

    assert raised.value.code == "invalid_credentials"
    password_check.assert_called_once_with("wrong", DUMMY_PASSWORD_HASH)
    assert [key.bucket_type for key in recorded] == ["email", "ip"]


def test_successful_login_clears_email_bucket_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from cairn_api.auth import rate_limit_repository, service

    session = MagicMock(spec=Session)
    user = User(
        id=uuid4(),
        email="user@example.com",
        normalized_email="user@example.com",
        password_hash="digest",
        is_active=True,
    )
    organization = Organization(id=uuid4(), slug="test-org", name="Test Org")
    membership = Membership(id=uuid4(), org_id=organization.id, user_id=user.id, role="owner")
    monkeypatch.setattr(rate_limit_repository.RateLimitRepository, "lock_buckets", MagicMock(return_value={}))
    monkeypatch.setattr(service, "get_user_by_normalized_email", MagicMock(return_value=user))
    monkeypatch.setattr(service, "verify_password", MagicMock(return_value=True))
    monkeypatch.setattr(
        service,
        "get_memberships_for_user",
        MagicMock(return_value=[MembershipRecord(membership, organization)]),
    )
    clear_email = MagicMock()
    monkeypatch.setattr(rate_limit_repository.RateLimitRepository, "clear_email_bucket", clear_email)
    monkeypatch.setattr(service, "add_audit_log", MagicMock())

    result = AuthService(session, Settings(_env_file=None)).login(  # pyright: ignore[reportCallIssue]
        email="user@example.com",
        password="correct",
        audit=AUDIT,
        client_ip="198.51.100.7",
        now=lambda: NOW,
    )

    assert result.identity.user.email == "user@example.com"
    clear_email.assert_called_once()
    assert clear_email.call_args.args[1] != b""
