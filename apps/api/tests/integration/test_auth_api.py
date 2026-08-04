from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cairn_api.app import create_app
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession, User
from cairn_api.auth.security import DUMMY_PASSWORD_HASH, digest_token
from cairn_api.db.session import Database
from cairn_api.organizations.models import Membership, Organization
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, delete, func, select, text, update

APP_ORIGIN = "http://localhost:5500"
DEMO_EMAIL = "demo@cairn.dev"
DEMO_PASSWORD = "cairn-demo-2026"


@pytest.fixture()
def api_settings(test_database_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=test_database_url,
        app_url=APP_ORIGIN,
        cors_origins=[APP_ORIGIN],
        csrf_secret="test-only-csrf-secret-with-at-least-32-bytes",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


@pytest.fixture()
def client(
    database: Database,
    migrated_engine: Engine,
    api_settings: Settings,
) -> Generator[TestClient, None, None]:
    seed_demo_identity(api_settings, database)
    with TestClient(create_app(api_settings, database)) as test_client:
        yield test_client


@pytest.fixture()
def other_org_id(database: Database, client: TestClient) -> UUID:
    organization_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(Organization(id=organization_id, slug="other-org", name="Other Org"))
    return organization_id


def login(client: TestClient, *, password: str = DEMO_PASSWORD) -> Response:
    return client.post(
        "/api/v1/login",
        headers={"Origin": APP_ORIGIN, "X-Request-ID": "req-login"},
        json={"email": DEMO_EMAIL, "password": password},
    )


@pytest.mark.integration
def test_login_sets_cookie_and_persists_only_token_digests(
    client: TestClient,
    database: Database,
) -> None:
    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {
        "id": "00000000-0000-4000-8000-000000001001",
        "email": DEMO_EMAIL,
        "displayName": "演示用户",
    }
    assert body["organization"]["slug"] == "cairn-demo"
    assert body["membership"]["role"] == "owner"
    assert "password" not in response.text
    cookie = response.headers["set-cookie"]
    assert "cairn_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=604800" in cookie
    with database.session_factory() as session:
        stored = session.scalar(select(AuthSession))
        actions = session.scalars(select(AuditLog.action)).all()
    assert stored is not None
    raw_session_token = client.cookies.get("cairn_session")
    assert raw_session_token is not None
    assert digest_token(raw_session_token) == stored.token_digest
    assert raw_session_token.encode("ascii") not in {stored.token_digest, stored.csrf_digest}
    assert len(stored.token_digest) == 32
    assert len(stored.csrf_digest) == 32
    assert body["csrfToken"].encode("ascii") not in {
        stored.token_digest,
        stored.csrf_digest,
    }
    assert actions == ["auth.login_succeeded"]


@pytest.mark.integration
def test_refresh_restores_session_and_csrf_token(
    client: TestClient,
    database: Database,
) -> None:
    signed_in = login(client)
    restored = client.get("/api/v1/session", headers={"X-Request-ID": "req-restore"})

    assert restored.status_code == 200
    assert restored.json()["csrfToken"] == signed_in.json()["csrfToken"]
    with database.session_factory() as session:
        actions = session.scalars(select(AuditLog.action).order_by(AuditLog.created_at)).all()
    assert actions == ["auth.login_succeeded", "auth.session_restored"]


@pytest.mark.integration
def test_current_and_cross_org_reads_use_only_cookie_organization(
    client: TestClient,
    other_org_id: UUID,
) -> None:
    signed_in = login(client)
    own_id = signed_in.json()["organization"]["id"]

    own = client.get(
        f"/api/v1/organizations/{own_id}",
        headers={"X-Organization-ID": str(other_org_id)},
        params={"organizationId": str(other_org_id)},
    )
    other = client.get(f"/api/v1/organizations/{other_org_id}")

    assert own.status_code == 200
    assert own.json()["id"] == own_id
    assert other.status_code == 404
    assert other.json()["code"] == "not_found"


@pytest.mark.integration
def test_unknown_email_uses_dummy_hash_and_returns_traced_invalid_credentials(
    client: TestClient,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api.auth import security, service

    checked_hashes: list[str] = []
    real_verify = security.verify_password

    def recording_verify(password: str, digest: str) -> bool:
        checked_hashes.append(digest)
        return real_verify(password, digest)

    monkeypatch.setattr(service, "verify_password", recording_verify)
    response = client.post(
        "/api/v1/login",
        headers={"Origin": APP_ORIGIN, "X-Request-ID": "req-unknown"},
        json={"email": "unknown@example.com", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert response.json()["traceId"] == response.headers["x-request-id"] == "req-unknown"
    assert checked_hashes == [DUMMY_PASSWORD_HASH]
    with database.session_factory() as session:
        audit = session.scalar(select(AuditLog))
    assert audit is not None
    assert audit.action == "auth.login_failed"
    assert audit.actor_id is None
    assert audit.org_id is None


@pytest.mark.integration
def test_wrong_password_returns_invalid_credentials(client: TestClient) -> None:
    response = login(client, password="wrong-password")
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


@pytest.mark.integration
def test_disabled_user_returns_invalid_credentials(
    client: TestClient,
    database: Database,
) -> None:
    with database.session_factory.begin() as session:
        session.execute(update(User).values(is_active=False))
    response = login(client)
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


@pytest.mark.integration
def test_user_without_membership_returns_invalid_credentials(
    client: TestClient,
    database: Database,
) -> None:
    with database.session_factory.begin() as session:
        session.execute(delete(Membership))
    response = login(client)
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


@pytest.mark.integration
def test_multiple_memberships_require_explicit_organization_selection(
    client: TestClient,
    database: Database,
) -> None:
    with database.session_factory.begin() as session:
        user_id = session.scalar(select(User.id))
        other = Organization(id=uuid4(), slug="second-org", name="Second Org")
        session.add(other)
        session.flush()
        session.add(Membership(org_id=other.id, user_id=user_id, role="viewer"))
    response = login(client)
    assert response.status_code == 409
    assert response.json()["code"] == "organization_selection_required"


@pytest.mark.integration
def test_login_and_logout_reject_bad_origin(client: TestClient) -> None:
    bad_login = client.post(
        "/api/v1/login",
        headers={"Origin": "http://localhost:5500.attacker.example"},
        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    bad_logout = client.post(
        "/api/v1/logout",
        headers={"Origin": "http://localhost:5500.attacker.example"},
    )
    assert bad_login.status_code == 403
    assert bad_login.json()["code"] == "csrf_failed"
    assert bad_logout.status_code == 403
    assert bad_logout.json()["code"] == "csrf_failed"


@pytest.mark.integration
def test_logout_rejects_bad_csrf_without_revoking_session(
    client: TestClient,
    database: Database,
) -> None:
    assert login(client).status_code == 200
    response = client.post(
        "/api/v1/logout",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": "wrong"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    with database.session_factory() as session:
        assert session.scalar(select(AuthSession.revoked_at)) is None


@pytest.mark.integration
@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_expired_or_revoked_session_is_invalid_and_clears_cookie(
    client: TestClient,
    database: Database,
    state: str,
) -> None:
    assert login(client).status_code == 200
    values = (
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        if state == "expired"
        else {"revoked_at": datetime.now(UTC)}
    )
    with database.session_factory.begin() as session:
        session.execute(update(AuthSession).values(**values))
    response = client.get("/api/v1/session")
    assert response.status_code == 401
    assert response.json()["code"] == "session_invalid"
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.integration
@pytest.mark.parametrize("change", ["remove_membership", "disable_user"])
def test_membership_removal_or_disabled_user_invalidates_session(
    client: TestClient,
    database: Database,
    change: str,
) -> None:
    assert login(client).status_code == 200
    with database.session_factory.begin() as session:
        if change == "remove_membership":
            session.execute(delete(Membership))
        else:
            session.execute(update(User).values(is_active=False))
    response = client.get("/api/v1/session")
    assert response.status_code == 401
    assert response.json()["code"] == "session_invalid"


@pytest.mark.integration
def test_logout_is_idempotent_and_audited_once(
    client: TestClient,
    database: Database,
) -> None:
    signed_in = login(client)
    csrf_token = signed_in.json()["csrfToken"]
    first = client.post(
        "/api/v1/logout",
        headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
    )
    second = client.post("/api/v1/logout", headers={"Origin": APP_ORIGIN})

    assert first.status_code == second.status_code == 204
    assert "Max-Age=0" in first.headers["set-cookie"]
    with database.session_factory() as session:
        session_row = session.scalar(select(AuthSession))
        logout_count = session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "auth.logout")
        )
    assert session_row is not None and session_row.revoked_at is not None
    assert logout_count == 1


@pytest.mark.integration
def test_login_audit_failure_rolls_back_session_atomically(
    client: TestClient,
    database: Database,
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE FUNCTION cairn_fail_audit_insert() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'forced audit failure'; END; $$;
                CREATE TRIGGER fail_audit_insert BEFORE INSERT ON audit_logs
                FOR EACH ROW EXECUTE FUNCTION cairn_fail_audit_insert();
                """
            )
        )
    try:
        response = login(client)
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(text("DROP TRIGGER IF EXISTS fail_audit_insert ON audit_logs"))
            connection.execute(text("DROP FUNCTION IF EXISTS cairn_fail_audit_insert()"))

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0


@pytest.mark.integration
def test_logout_audit_failure_rolls_back_revocation_atomically(
    client: TestClient,
    database: Database,
    migrated_engine: Engine,
) -> None:
    signed_in = login(client)
    csrf_token = signed_in.json()["csrfToken"]
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE FUNCTION cairn_fail_logout_audit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.action = 'auth.logout' THEN
                        RAISE EXCEPTION 'forced logout audit failure';
                    END IF;
                    RETURN NEW;
                END; $$;
                CREATE TRIGGER fail_logout_audit BEFORE INSERT ON audit_logs
                FOR EACH ROW EXECUTE FUNCTION cairn_fail_logout_audit();
                """
            )
        )
    try:
        response = client.post(
            "/api/v1/logout",
            headers={"Origin": APP_ORIGIN, "X-CSRF-Token": csrf_token},
        )
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(text("DROP TRIGGER IF EXISTS fail_logout_audit ON audit_logs"))
            connection.execute(text("DROP FUNCTION IF EXISTS cairn_fail_logout_audit()"))

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    with database.session_factory() as session:
        assert session.scalar(select(AuthSession.revoked_at)) is None


@pytest.mark.integration
def test_database_connection_failure_returns_503(api_settings: Settings) -> None:
    unavailable_url = (
        "postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:1/cairn_test"
        "?connect_timeout=1"
    )
    settings = api_settings.model_copy(update={"database_url": unavailable_url})
    database = Database(unavailable_url)
    try:
        with TestClient(create_app(settings, database), raise_server_exceptions=False) as client:
            response = client.post(
                "/api/v1/login",
                headers={"Origin": APP_ORIGIN},
                json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
            )
    finally:
        database.dispose()
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
