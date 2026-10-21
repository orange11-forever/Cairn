from collections.abc import Generator
from datetime import datetime
from typing import cast

import pytest
from cairn_api.app import create_app
from cairn_api.db.session import Database
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, event, text

ORIGIN = "http://localhost:5500"
TRUSTED_OTHER_ORIGIN = "http://localhost:5501"
PASSWORD = "  original-password-2026  "


class CapturedMail:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, datetime]] = []
        self.reset_messages: list[tuple[str, str, datetime]] = []
        self.registration_notices: list[str] = []
        self.reset_notices: list[str] = []

    def send_verification(
        self, recipient: str, verification_url: str, expires_at: datetime
    ) -> None:
        self.messages.append((recipient, verification_url, expires_at))

    def send_password_reset(self, recipient: str, reset_url: str, expires_at: datetime) -> None:
        self.reset_messages.append((recipient, reset_url, expires_at))

    def send_registration_notice(self, recipient: str) -> None:
        self.registration_notices.append(recipient)

    def send_password_reset_notice(self, recipient: str) -> None:
        self.reset_notices.append(recipient)


@pytest.fixture()
def registration_client(
    database: Database, migrated_engine: Engine
) -> Generator[TestClient, None, None]:
    del migrated_engine
    settings = Settings(
        environment="test",
        database_url=database.engine.url.render_as_string(hide_password=False),
        app_url=ORIGIN,
        cors_origins=[ORIGIN, TRUSTED_OTHER_ORIGIN],
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )  # pyright: ignore[reportCallIssue]
    seed_demo_identity(settings, database)
    app = create_app(settings, database)
    app.state.registration_mail_sender = CapturedMail()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def mail(client: TestClient) -> CapturedMail:
    return cast(CapturedMail, cast(FastAPI, client.app).state.registration_mail_sender)


def counts(database: Database) -> tuple[int, ...]:
    with database.engine.connect() as connection:
        return tuple(
            connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM organizations), (SELECT count(*) FROM memberships), (SELECT count(*) FROM auth_sessions)"
                )
            ).one()
        )


def contract(response: Response, status: int, code: str | None = None) -> None:
    assert response.status_code == status, response.text
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-type"].startswith("application/json")
    request_origin = response.request.headers.get("Origin")
    if request_origin in (ORIGIN, TRUSTED_OTHER_ORIGIN):
        assert response.headers["access-control-allow-origin"] == request_origin
        assert response.headers["access-control-allow-credentials"] == "true"
        assert "Origin" in response.headers["vary"]
        assert {"X-Request-ID", "Retry-After"} <= set(
            response.headers["access-control-expose-headers"].split(", ")
        )
    else:
        assert "access-control-allow-origin" not in response.headers
        if request_origin is None:
            assert "access-control-allow-credentials" not in response.headers
            assert "access-control-expose-headers" not in response.headers
        else:
            # Credentials without Allow-Origin do not grant a foreign page permission.
            assert response.headers["access-control-allow-credentials"] == "true"
    assert "set-cookie" not in response.headers
    if status == 405:
        assert response.headers["allow"] == "POST"
    if response.request.method == "HEAD":
        # HEAD retains GET error headers/length, without an observable JSON body.
        assert response.content == b""
        assert int(response.headers["content-length"]) > 0
        return
    if code:
        assert set(response.json()) == {"code", "message", "traceId"}
        assert response.json()["code"] == code
        message = response.json()["message"]
        assert isinstance(message, str) and bool(message.strip())
        assert response.json()["traceId"] == response.headers["x-request-id"]


def register(
    client: TestClient, email: str = "new@example.com", password: str = PASSWORD
) -> Response:
    return client.post(
        "/api/v1/auth/register",
        headers={"Origin": ORIGIN, "Host": "evil.example"},
        json={"email": email, "password": password, "displayName": "新用户"},
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "payload",
    [
        {"email": "bad", "password": PASSWORD},
        {"email": "new@example.com", "password": "short"},
        {"email": "new@example.com", "password": "x" * 129},
    ],
)
def test_validation_contract_without_state_change(
    registration_client: TestClient, database: Database, payload: dict[str, str]
) -> None:
    before = counts(database)
    response = registration_client.post(
        "/api/v1/auth/register", headers={"Origin": ORIGIN}, json=payload
    )
    contract(response, 422, "validation_error")
    assert counts(database) == before
    assert not mail(registration_client).messages


@pytest.mark.integration
@pytest.mark.parametrize("stage", ["flush", "commit", "audit", "unexpected", "unknown_integrity"])
def test_registration_failures_roll_back_entire_account_boundary(
    registration_client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from cairn_api.auth import registration_service
    from sqlalchemy.exc import IntegrityError, OperationalError
    from sqlalchemy.orm import Session

    client = registration_client
    before = counts(database)
    original_flush = Session.flush

    def fail_flush(self: Session, objects: object = None) -> None:
        if any(
            obj.__class__.__name__ in ("User", "Organization", "Membership") for obj in self.new
        ):
            if stage == "unknown_integrity":
                raise IntegrityError("hidden", {}, Exception("secret unrelated constraint"))
            raise OperationalError("hidden", {}, Exception("secret database"))
        original_flush(self, objects)  # type: ignore[arg-type]

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret unexpected")

    def before_commit(session: Session) -> None:
        if any(obj.__class__.__name__ == "AuditLog" for obj in session.new):
            raise OperationalError("hidden", {}, Exception("secret database"))

    if stage in ("flush", "unknown_integrity"):
        monkeypatch.setattr(Session, "flush", fail_flush)
    elif stage == "commit":
        event.listen(Session, "before_commit", before_commit)
    else:
        monkeypatch.setattr(
            registration_service,
            "add_audit_log" if stage == "audit" else "hash_password",
            fail_audit,
        )
    try:
        response = register(client)
        contract(
            response,
            503 if stage in ("flush", "commit") else 500,
            "database_unavailable" if stage in ("flush", "commit") else "internal_error",
        )
        assert "secret" not in response.text
    finally:
        if stage == "commit":
            event.remove(Session, "before_commit", before_commit)
        monkeypatch.undo()
    assert counts(database) == before
    with database.session_factory() as session:
        assert session.scalar(text("SELECT consumed_at FROM pending_registrations")) is None
        assert (
            session.scalar(text("SELECT count(*) FROM audit_logs WHERE action = 'auth.registered'"))
            == 0
        )
    contract(register(client), 201)


@pytest.mark.integration
def test_registration_does_not_replace_authenticated_or_logged_out_cookie(
    registration_client: TestClient,
) -> None:
    client = registration_client
    identity = client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "demo@cairn.dev", "password": "cairn-demo-2026"},
    ).json()
    cookie = client.cookies.get("cairn_session")
    contract(register(client), 201)
    assert client.cookies.get("cairn_session") == cookie
    assert client.get("/api/v1/session").json()["user"]["id"] == identity["user"]["id"]
    assert (
        client.post(
            "/api/v1/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": identity["csrfToken"]}
        ).status_code
        == 204
    )
    contract(register(client, "other@example.com"), 201)
    assert client.cookies.get("cairn_session") is None
    assert client.get("/api/v1/session").status_code == 401


@pytest.mark.integration
def test_unexpected_registration_errors_never_log_proof_or_password_material(
    registration_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import logging

    from cairn_api.auth import registration_service

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("private-password-proof-recipient@example.com")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(request_id)s %(message)s"))
    logger = logging.getLogger("cairn_api")
    logger.addHandler(handler)
    try:
        monkeypatch.setattr(registration_service, "hash_password", fail)
        response = register(registration_client)
        contract(response, 500, "internal_error")
        assert "private-password-proof" not in stream.getvalue()
        assert response.headers["x-request-id"] in stream.getvalue()
    finally:
        logger.removeHandler(handler)


@pytest.mark.integration
def test_native_owner_is_denied_old_project_and_knowledge_then_can_explicitly_link_oauth(
    registration_client: TestClient,
) -> None:
    from .test_oauth_api import MockProvider, callback, start

    client = registration_client
    original = client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "demo@cairn.dev", "password": "cairn-demo-2026"},
    ).json()
    headers = {"Origin": ORIGIN, "X-CSRF-Token": original["csrfToken"]}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Old tenant"}).json()
    assert client.post("/api/v1/logout", headers=headers).status_code == 204
    contract(register(client), 201)
    login = client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "new@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    identity = login.json()
    assert identity["organization"]["id"] != original["organization"]["id"]
    for path in (
        "/api/v1/projects/" + project["id"],
        "/api/v1/projects/" + project["id"] + "/knowledge/resources",
    ):
        denied = client.get(path)
        assert denied.status_code == 404
        assert denied.json()["traceId"] == denied.headers["x-request-id"]
    app = cast(FastAPI, client.app)
    app.state.oauth_providers = {"github": MockProvider()}
    headers = {"Origin": ORIGIN, "X-CSRF-Token": identity["csrfToken"]}
    cookie = client.cookies.get("cairn_session")
    linked = callback(
        client,
        start(client, "github", "link", headers, "/account/identities"),
        "native-explicit-identity",
    )
    assert linked.status_code == 303 and "oauth=linked" in linked.headers["location"]
    assert client.cookies.get("cairn_session") == cookie
    methods = client.get("/api/v1/auth/identities").json()
    assert methods["passwordAvailable"] is True and len(methods["identities"]) == 1
    assert (
        client.delete(
            "/api/v1/auth/identities/" + methods["identities"][0]["id"], headers=headers
        ).status_code
        == 204
    )
    assert client.post("/api/v1/logout", headers=headers).status_code == 204
    assert client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code == 204
    restored = client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "new@example.com", "password": PASSWORD},
    )
    assert restored.status_code == 200
    assert restored.json()["user"]["id"] == identity["user"]["id"]


def seed_legacy_pending(database: Database, email: str = "new@example.com") -> None:
    """Retained proofs predate direct signup; seed persistence without invoking mail APIs."""
    from datetime import UTC, timedelta
    from uuid import uuid4

    from cairn_api.auth.registration_models import PendingRegistration
    from cairn_api.auth.security import digest_token, hash_password

    now = datetime.now(UTC)
    with database.session_factory.begin() as session:
        session.add(
            PendingRegistration(
                email=email,
                normalized_email=email,
                password_hash=hash_password(PASSWORD),
                token_digest=digest_token(str(uuid4())),
                receipt_digest=digest_token(str(uuid4())),
                generation=1,
                created_at=now,
                expires_at=now + timedelta(minutes=30),
                last_sent_at=now,
            )
        )
