from collections.abc import Generator
from datetime import datetime
from typing import cast
from urllib.parse import parse_qs, urlsplit

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

    def send_verification(
        self, recipient: str, verification_url: str, expires_at: datetime
    ) -> None:
        self.messages.append((recipient, verification_url, expires_at))

    def token(self, index: int = -1) -> str:
        link = self.messages[index][1]
        assert link.startswith(ORIGIN + "/register/verify#token=")
        assert urlsplit(link).query == ""
        return parse_qs(urlsplit(link).fragment)["token"][0]


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
    # The HTTP boundary must exist even before its mail implementation exists.
    settings = settings.model_copy(
        update={
            "registration_enabled": True,
            "smtp_host": "127.0.0.1",
            "smtp_from": "cairn@example.com",
            "smtp_security": "plain",
        }
    )
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


def verify(client: TestClient, token: str, password: str = PASSWORD) -> Response:
    return client.post(
        "/api/v1/auth/register/verify",
        headers={"Origin": ORIGIN},
        json={"token": token, "password": password},
    )


@pytest.mark.integration
def test_account_and_personal_owner_exist_only_after_email_and_original_password(
    registration_client: TestClient, database: Database
) -> None:
    client = registration_client
    before = counts(database)
    accepted = register(client)
    contract(accepted, 202)
    assert set(accepted.json()) == {"message", "registrationReceipt", "resendAfterSeconds"}
    assert accepted.json()["resendAfterSeconds"] == 60
    assert counts(database) == before
    assert client.cookies.get("cairn_session") is None
    token = mail(client).token()
    from cairn_api.auth.security import digest_token, verify_password

    with database.session_factory() as session:
        row = session.execute(
            text("SELECT token_digest, receipt_digest, password_hash FROM pending_registrations")
        ).one()
        assert bytes(row[0]) == digest_token(token)
        assert bytes(row[1]) == digest_token(accepted.json()["registrationReceipt"])
        assert row[2].startswith("$argon2")
        assert PASSWORD not in row[2] and verify_password(PASSWORD, row[2])
    for method in ("GET", "HEAD"):
        scanner = client.request(method, "/api/v1/auth/register/verify", headers={"Origin": ORIGIN})
        contract(scanner, 405, "method_not_allowed")
        assert scanner.headers["allow"] == "POST"
        assert counts(database) == before
    contract(verify(client, "x" * 43), 400, "registration_invalid")
    contract(verify(client, token, PASSWORD.strip()), 400, "registration_invalid")
    assert counts(database) == before
    pending_login = client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "new@example.com", "password": PASSWORD},
    )
    assert pending_login.status_code == 401
    success = verify(client, token)
    contract(success, 200)
    assert set(success.json()) == {"message"}
    assert counts(database) == tuple(n + 1 if i < 3 else n for i, n in enumerate(before))
    contract(verify(client, token), 400, "registration_invalid")
    login = client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "NEW@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    identity = login.json()
    assert identity["membership"]["role"] == "owner"
    assert identity["organization"]["slug"].startswith("personal-")
    assert identity["organization"]["slug"] != "cairn-demo"
    assert (
        client.get("/api/v1/organizations/00000000-0000-4000-8000-000000002001").status_code == 404
    )
    assert client.get("/api/v1/projects").json()["items"] == []


def resend(
    client: TestClient, receipt: str, email: str = "new@example.com", password: str = PASSWORD
) -> Response:
    return client.post(
        "/api/v1/auth/register/resend",
        headers={"Origin": ORIGIN},
        json={"registrationReceipt": receipt, "email": email, "password": password},
    )


@pytest.mark.integration
def test_resend_cooldown_password_receipt_ownership_rotation_and_fixed_expiry(
    registration_client: TestClient, database: Database
) -> None:
    client = registration_client
    accepted = register(client)
    receipt = accepted.json()["registrationReceipt"]
    original = mail(client).token()
    contract(resend(client, receipt), 429, "registration_rate_limited")
    contract(resend(client, "unknown"), 202)
    assert len(mail(client).messages) == 1
    with database.session_factory.begin() as session:
        session.execute(
            text("UPDATE pending_registrations SET last_sent_at = now() - interval '61 seconds'")
        )
    contract(resend(client, receipt, password="wrong-password-2026"), 202)
    assert len(mail(client).messages) == 1
    contract(resend(client, receipt, email="other@example.com"), 202)
    rotated = resend(client, receipt)
    contract(rotated, 202)
    assert rotated.json()["registrationReceipt"] == receipt
    assert len(mail(client).messages) == 2
    assert mail(client).messages[0][2] == mail(client).messages[1][2]
    contract(verify(client, original), 400, "registration_invalid")
    contract(verify(client, mail(client).token()), 200)


@pytest.mark.integration
@pytest.mark.parametrize("existing_kind", ["password", "inactive", "oauth"])
def test_existing_email_never_merges_resets_reactivates_or_sends(
    registration_client: TestClient, database: Database, existing_kind: str
) -> None:
    client = registration_client
    with database.session_factory.begin() as session:
        if existing_kind == "inactive":
            session.execute(text("UPDATE users SET is_active = false"))
        if existing_kind == "oauth":
            session.execute(text("UPDATE users SET password_hash = NULL"))
        original = tuple(
            session.execute(text("SELECT id, password_hash, is_active FROM users")).one()
        )
    before = counts(database)
    accepted = register(client, "DEMO@cairn.dev")
    contract(accepted, 202)
    contract(resend(client, accepted.json()["registrationReceipt"], "demo@cairn.dev"), 202)
    assert not mail(client).messages
    assert counts(database) == before
    with database.session_factory() as session:
        assert (
            tuple(session.execute(text("SELECT id, password_hash, is_active FROM users")).one())
            == original
        )
        assert session.scalar(text("SELECT count(*) FROM pending_registrations")) == 0


@pytest.mark.integration
@pytest.mark.parametrize("same_attempt", [True, False])
def test_parallel_email_proofs_provision_once_without_orphan_rows(
    registration_client: TestClient, database: Database, same_attempt: bool
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client = registration_client
    before = counts(database)
    contract(register(client), 202)
    first = mail(client).token()
    second = first
    if not same_attempt:
        contract(register(client, "NEW@example.com", "other-original-password"), 202)
        second = mail(client).token()
    barrier = Barrier(2)

    def confirm(args: tuple[str, str]) -> Response:
        with TestClient(client.app, raise_server_exceptions=False) as other:
            barrier.wait(timeout=10)
            return verify(other, *args)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                confirm,
                [
                    (first, PASSWORD),
                    (second, PASSWORD if same_attempt else "other-original-password"),
                ],
            )
        )
    assert sorted(result.status_code for result in results) == [200, 400]
    assert counts(database) == tuple(n + 1 if i < 3 else n for i, n in enumerate(before))
    for result in results:
        contract(
            result,
            result.status_code,
            "registration_invalid" if result.status_code == 400 else None,
        )


@pytest.mark.integration
def test_second_pending_attempt_cannot_replace_first_password_or_block_its_proof(
    registration_client: TestClient, database: Database
) -> None:
    client = registration_client
    register(client)
    first = mail(client).token()
    register(client, "NEW@example.com", "attacker-password-2026")
    second = mail(client).token()
    contract(verify(client, first, "attacker-password-2026"), 400, "registration_invalid")
    contract(verify(client, first), 200)
    contract(verify(client, second, "attacker-password-2026"), 400, "registration_invalid")
    with database.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM users WHERE normalized_email = 'new@example.com'")
            )
            == 1
        )


@pytest.mark.integration
def test_wrong_password_counts_commit_and_successful_login_does_not_clear_mail_limits(
    registration_client: TestClient, database: Database
) -> None:
    client = registration_client
    register(client)
    token = mail(client).token()
    for _ in range(5):
        contract(verify(client, token, "wrong"), 400, "registration_invalid")
    blocked = verify(client, token)
    contract(blocked, 429, "registration_rate_limited")
    assert 1 <= int(blocked.headers["retry-after"]) <= 900
    with database.session_factory.begin() as session:
        assert session.scalar(text("SELECT failed_password_count FROM pending_registrations")) == 5
        session.execute(
            text(
                "UPDATE pending_registrations SET password_window_started_at = now() - interval '16 minutes'"
            )
        )
    contract(verify(client, token), 200)
    assert (
        client.post(
            "/api/v1/login",
            headers={"Origin": ORIGIN},
            json={"email": "new@example.com", "password": PASSWORD},
        ).status_code
        == 200
    )
    for _ in range(4):
        contract(register(client), 202)
    blocked = register(client)
    contract(blocked, 429, "registration_rate_limited")
    assert int(blocked.headers["retry-after"]) > 0


@pytest.mark.integration
def test_parallel_first_use_send_bucket_is_atomic(
    registration_client: TestClient, database: Database
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(7)

    def request(index: int) -> Response:
        del index
        with TestClient(registration_client.app, raise_server_exceptions=False) as other:
            barrier.wait(timeout=10)
            return register(other)

    with ThreadPoolExecutor(max_workers=7) as pool:
        results = list(pool.map(request, range(7)))
    assert sorted(result.status_code for result in results) == [202] * 5 + [429] * 2
    with database.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT attempt_count FROM registration_rate_limits WHERE purpose = 'send_email'"
                )
            )
            == 5
        )
        assert session.scalar(text("SELECT count(*) FROM pending_registrations")) == 5


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
@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("register", {"email": "new@example.com", "password": PASSWORD}),
        (
            "register/resend",
            {"email": "new@example.com", "password": PASSWORD, "registrationReceipt": "unknown"},
        ),
        ("register/verify", {"token": "unknown", "password": PASSWORD}),
    ],
)
def test_all_mutations_require_exact_origin(
    registration_client: TestClient, endpoint: str, payload: dict[str, str]
) -> None:
    for origin in (None, "https://evil.example", ORIGIN + "/", TRUSTED_OTHER_ORIGIN):
        headers = {"Origin": origin} if origin else {}
        result = registration_client.post("/api/v1/auth/" + endpoint, headers=headers, json=payload)
        contract(result, 403, "csrf_failed")
    assert not mail(registration_client).messages


@pytest.mark.integration
def test_expiry_unicode_size_preflight_disabled_and_openapi_contract(
    registration_client: TestClient, database: Database
) -> None:
    client = registration_client
    register(client)
    token = mail(client).token()
    with database.session_factory.begin() as session:
        session.execute(
            text("UPDATE pending_registrations SET expires_at = now() - interval '1 second'")
        )
    contract(verify(client, token), 400, "registration_invalid")
    for invalid_token in ("☃", "x" * 129):
        contract(verify(client, invalid_token), 422, "validation_error")
    response = client.options(
        "/api/v1/auth/register",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Request-ID",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["x-request-id"]
    availability = client.get("/api/v1/auth/registration", headers={"Origin": ORIGIN})
    contract(availability, 200)
    assert availability.json() == {"enabled": True}
    paths = client.get("/openapi.json").json()["paths"]
    for path, status in (
        ("register", "202"),
        ("register/resend", "202"),
        ("register/verify", "200"),
    ):
        responses = paths["/api/v1/auth/" + path]["post"]["responses"]
        assert {status, "400", "403", "422", "429", "503", "500"} <= set(responses)
        assert responses[status]["content"]["application/json"]["schema"]["$ref"].startswith(
            "#/components/schemas/Registration"
        )
    app = cast(FastAPI, client.app)
    app.state.settings = app.state.settings.model_copy(update={"registration_enabled": False})
    availability = client.get("/api/v1/auth/registration", headers={"Origin": ORIGIN})
    contract(availability, 200)
    assert availability.json() == {"enabled": False}
    contract(register(client), 503, "registration_unavailable")


@pytest.mark.integration
def test_mail_failure_revokes_current_generation_and_preserves_quota(
    registration_client: TestClient, database: Database
) -> None:
    from cairn_api.auth.registration_mail import RegistrationMailUnavailable

    class FailedMail(CapturedMail):
        def send_verification(
            self, recipient: str, verification_url: str, expires_at: datetime
        ) -> None:
            super().send_verification(recipient, verification_url, expires_at)
            raise RegistrationMailUnavailable("secret transport detail")

    client = registration_client
    app = cast(FastAPI, client.app)
    app.state.registration_mail_sender = FailedMail()
    before = counts(database)
    response = register(client)
    contract(response, 503, "registration_mail_unavailable")
    assert "secret" not in response.text
    contract(verify(client, mail(client).token()), 400, "registration_invalid")
    assert counts(database) == before
    with database.session_factory() as session:
        assert session.scalar(text("SELECT token_digest FROM pending_registrations")) is None
        assert (
            session.scalar(
                text(
                    "SELECT attempt_count FROM registration_rate_limits WHERE purpose = 'send_email'"
                )
            )
            == 1
        )


@pytest.mark.integration
@pytest.mark.parametrize("stage", ["flush", "commit", "audit", "unexpected", "unknown_integrity"])
def test_verification_failures_roll_back_entire_account_boundary(
    registration_client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from cairn_api.auth import registration_service
    from sqlalchemy.exc import IntegrityError, OperationalError
    from sqlalchemy.orm import Session

    client = registration_client
    register(client)
    token = mail(client).token()
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
            "add_audit_log" if stage == "audit" else "verify_password",
            fail_audit,
        )
    try:
        response = verify(client, token)
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
            session.scalar(
                text("SELECT count(*) FROM audit_logs WHERE action = 'auth.registration_verified'")
            )
            == 0
        )
    contract(verify(client, token), 200)


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
    register(client)
    contract(verify(client, mail(client).token()), 200)
    assert client.cookies.get("cairn_session") == cookie
    assert client.get("/api/v1/session").json()["user"]["id"] == identity["user"]["id"]
    register(client, "other@example.com")
    assert (
        client.post(
            "/api/v1/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": identity["csrfToken"]}
        ).status_code
        == 204
    )
    contract(verify(client, mail(client).token()), 200)
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
        register(registration_client)
        monkeypatch.setattr(registration_service, "verify_password", fail)
        response = verify(registration_client, mail(registration_client).token())
        contract(response, 500, "internal_error")
        assert "private-password-proof" not in stream.getvalue()
        assert response.headers["x-request-id"] in stream.getvalue()
    finally:
        logger.removeHandler(handler)


@pytest.mark.integration
@pytest.mark.parametrize("stage", ["flush", "commit"])
def test_pending_persistence_failure_sends_no_mail_and_retains_reserved_quota(
    registration_client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    original_flush = Session.flush

    def fail_flush(session: Session, objects: object = None) -> None:
        if any(obj.__class__.__name__ == "PendingRegistration" for obj in session.new):
            raise OperationalError("hidden", {}, Exception("secret"))
        original_flush(session, objects)  # type: ignore[arg-type]

    def before_commit(session: Session) -> None:
        if any(
            obj.__class__.__name__ == "PendingRegistration" for obj in session.identity_map.values()
        ):
            raise OperationalError("hidden", {}, Exception("secret"))

    if stage == "flush":
        monkeypatch.setattr(Session, "flush", fail_flush)
    else:
        event.listen(Session, "before_commit", before_commit)
    before = counts(database)
    try:
        contract(register(registration_client), 503, "database_unavailable")
    finally:
        if stage == "commit":
            event.remove(Session, "before_commit", before_commit)
        monkeypatch.undo()
    assert counts(database) == before
    assert not mail(registration_client).messages
    with database.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM pending_registrations")) == 0
        assert (
            session.scalar(
                text(
                    "SELECT attempt_count FROM registration_rate_limits WHERE purpose = 'send_email'"
                )
            )
            == 1
        )


@pytest.mark.integration
def test_actual_smtp_capture_delivers_http_proof_before_account_creation(
    registration_client: TestClient, database: Database
) -> None:
    import re
    from email import policy
    from email.parser import BytesParser
    from socketserver import StreamRequestHandler, ThreadingTCPServer
    from threading import Thread

    from cairn_api.auth.registration_mail import SMTPRegistrationMailSender

    app = cast(FastAPI, registration_client.app)
    messages: list[bytes] = []

    class Capture(StreamRequestHandler):
        def handle(self) -> None:
            self.wfile.write(b"220 localhost capture\r\n")
            while line := self.rfile.readline():
                command = line.split(b" ", 1)[0].strip().upper()
                if command == b"DATA":
                    self.wfile.write(b"354 send message\r\n")
                    parts: list[bytes] = []
                    while (part := self.rfile.readline()) not in (b".\r\n", b""):
                        parts.append(part)
                    messages.append(b"".join(parts))
                    self.wfile.write(b"250 captured\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 goodbye\r\n")
                    return
                else:
                    self.wfile.write(b"250 localhost\r\n")

    with ThreadingTCPServer(("127.0.0.1", 0), Capture) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        app.state.settings = app.state.settings.model_copy(
            update={"smtp_port": server.server_address[1]}
        )
        app.state.registration_mail_sender = SMTPRegistrationMailSender(app.state.settings)
        before = counts(database)
        try:
            contract(register(registration_client), 202)
            assert counts(database) == before
            message = BytesParser(policy=policy.default).parsebytes(messages[0])
            content = cast(bytes, message.get_payload(decode=True)).decode("utf-8")
            match = re.search(
                r"http://localhost:5500/register/verify#token=([A-Za-z0-9_-]+)", content
            )
            assert match is not None
            contract(verify(registration_client, match[1]), 200)
            assert counts(database) == tuple(n + 1 if i < 3 else n for i, n in enumerate(before))
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.integration
def test_late_failed_mail_generation_cannot_revoke_a_newer_successful_resend(
    registration_client: TestClient, database: Database
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from cairn_api.auth.registration_mail import RegistrationMailUnavailable

    client = registration_client
    receipt = register(client).json()["registrationReceipt"]
    started, release = Event(), Event()

    class RacingMail(CapturedMail):
        def send_verification(
            self, recipient: str, verification_url: str, expires_at: datetime
        ) -> None:
            super().send_verification(recipient, verification_url, expires_at)
            if len(self.messages) == 1:
                started.set()
                assert release.wait(timeout=10)
                raise RegistrationMailUnavailable()

    app = cast(FastAPI, client.app)
    sender = RacingMail()
    app.state.registration_mail_sender = sender
    with database.session_factory.begin() as session:
        session.execute(
            text("UPDATE pending_registrations SET last_sent_at = now() - interval '61 seconds'")
        )

    def send_first() -> Response:
        with TestClient(app, raise_server_exceptions=False) as other:
            return resend(other, receipt)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(send_first)
        assert started.wait(timeout=10)
        # SMTP is outside held database locks; another generation can advance.
        with database.session_factory.begin() as session:
            session.execute(
                text(
                    "UPDATE pending_registrations SET last_sent_at = now() - interval '61 seconds'"
                )
            )
        try:
            contract(resend(client, receipt), 202)
        finally:
            release.set()
        contract(future.result(timeout=10), 503, "registration_mail_unavailable")
    assert len(sender.messages) == 2
    contract(verify(client, sender.token(0)), 400, "registration_invalid")
    contract(verify(client, sender.token(1)), 200)


@pytest.mark.integration
def test_verification_ip_limit_and_send_ip_limit_are_independent(
    registration_client: TestClient, database: Database
) -> None:
    client = registration_client
    for _ in range(20):
        contract(verify(client, "unknown"), 400, "registration_invalid")
    contract(verify(client, "unknown"), 429, "registration_rate_limited")
    for index in range(20):
        contract(register(client, f"existing-{index}@example.com"), 202)
    result = register(client, "another@example.com")
    contract(result, 429, "registration_rate_limited")
    with database.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT attempt_count FROM registration_rate_limits WHERE purpose = 'verify_ip'"
                )
            )
            == 20
        )
        assert (
            session.scalar(
                text("SELECT attempt_count FROM registration_rate_limits WHERE purpose = 'send_ip'")
            )
            == 20
        )


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
    register(client)
    contract(verify(client, mail(client).token()), 200)
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


@pytest.mark.integration
def test_authoritative_email_unique_constraint_rolls_back_org_on_external_writer_race(
    registration_client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn_api.auth.models import User
    from cairn_api.auth.registration_models import PendingRegistration
    from cairn_api.auth.registration_service import RegistrationService
    from cairn_api.auth.security import hash_password
    from cairn_api.auth.service import RequestAuditContext

    client = registration_client
    register(client)
    token = mail(client).token()
    before = counts(database)
    original = RegistrationService._provision  # pyright: ignore[reportPrivateUsage] - inject the external writer immediately before flush
    winning_hash = hash_password("external-existing-password")

    def external_insert(
        service: RegistrationService,
        pending: PendingRegistration,
        audit: RequestAuditContext,
        now: datetime,
    ) -> None:
        # An existing admin/seed writer does not participate in our advisory-lock namespace.
        with database.session_factory.begin() as other:
            other.add(
                User(
                    email=pending.email,
                    normalized_email=pending.normalized_email,
                    password_hash=winning_hash,
                )
            )
        original(service, pending, audit, now)

    monkeypatch.setattr(RegistrationService, "_provision", external_insert)
    contract(verify(client, token), 400, "registration_invalid")
    monkeypatch.undo()
    assert counts(database) == (before[0] + 1, *before[1:])
    with database.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT password_hash FROM users WHERE normalized_email = 'new@example.com'")
            )
            == winning_hash
        )
        assert session.scalar(text("SELECT consumed_at FROM pending_registrations")) is not None
        assert (
            session.scalar(
                text("SELECT count(*) FROM audit_logs WHERE action = 'auth.registration_verified'")
            )
            == 0
        )
    contract(verify(client, token), 400, "registration_invalid")
