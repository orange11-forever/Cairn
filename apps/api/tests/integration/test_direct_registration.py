from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import cast

import pytest
from cairn_api.auth.models import User
from cairn_api.db.session import Database
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select, text

from .test_registration_api import (
    ORIGIN,
    PASSWORD,
    TRUSTED_OTHER_ORIGIN,
    contract,
    counts,
    mail,
    register,
)
from .test_registration_api import registration_client as imported_registration_client

registration_client = imported_registration_client
pytestmark = pytest.mark.integration


def test_direct_registration_creates_unverified_owner_without_email_or_session(
    registration_client: TestClient, database: Database
) -> None:
    client = registration_client
    before = counts(database)
    response = register(client)
    contract(response, 201)
    assert set(response.json()) == {"message"}
    assert counts(database) == tuple(value + 1 for value in before[:3]) + (before[3],)
    with database.session_factory() as session:
        user = session.scalar(select(User).where(User.normalized_email == "new@example.com"))
        assert user is not None and user.email_verified_at is None
        assert user.display_name == "新用户"
        assert session.scalar(text("SELECT count(*) FROM pending_registrations")) == 0
        assert session.scalar(text("SELECT count(*) FROM password_resets")) == 0
        assert (
            session.scalar(text("SELECT count(*) FROM audit_logs WHERE action = 'auth.registered'"))
            == 1
        )
    assert client.get("/api/v1/session").status_code == 401
    login = client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "NEW@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["membership"]["role"] == "owner"
    assert login.json()["organization"]["name"] == "个人空间"
    captured = mail(client)
    assert (
        captured.messages
        == captured.reset_messages
        == captured.registration_notices
        == captured.reset_notices
        == []
    )


@pytest.mark.parametrize("existing_kind", ["password", "inactive", "oauth"])
def test_duplicate_email_does_not_change_or_merge_existing_account(
    registration_client: TestClient, database: Database, existing_kind: str
) -> None:
    with database.session_factory.begin() as session:
        if existing_kind == "inactive":
            session.execute(text("UPDATE users SET is_active = false"))
        if existing_kind == "oauth":
            session.execute(text("UPDATE users SET password_hash = NULL"))
        before_user = tuple(
            session.execute(
                text("SELECT id, password_hash, is_active, email_verified_at FROM users")
            ).one()
        )
    before = counts(database)
    contract(register(registration_client, "DEMO@cairn.dev"), 409, "registration_conflict")
    assert counts(database) == before
    with database.session_factory() as session:
        assert (
            tuple(
                session.execute(
                    text("SELECT id, password_hash, is_active, email_verified_at FROM users")
                ).one()
            )
            == before_user
        )
    assert mail(registration_client).registration_notices == []


def test_concurrent_registration_creates_one_account_and_preserves_rate_limit(
    registration_client: TestClient, database: Database
) -> None:
    barrier = Barrier(7)
    before = counts(database)

    def request(index: int) -> Response:
        with TestClient(registration_client.app, raise_server_exceptions=False) as other:
            barrier.wait(timeout=10)
            return register(other, password=f"parallel-password-{index}")

    with ThreadPoolExecutor(max_workers=7) as pool:
        results = list(pool.map(request, range(7)))
    assert sorted(result.status_code for result in results) == [201] + [409] * 4 + [429] * 2
    assert counts(database) == tuple(value + 1 for value in before[:3]) + (before[3],)
    winner = next(index for index, result in enumerate(results) if result.status_code == 201)
    login = registration_client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "new@example.com", "password": f"parallel-password-{winner}"},
    )
    assert login.status_code == 200
    for result in results:
        if result.status_code == 429:
            contract(result, 429, "registration_rate_limited")
            assert int(result.headers["retry-after"]) > 0


@pytest.mark.parametrize(
    "endpoint",
    ["register/resend", "register/verify", "password/reset/request", "password/reset/confirm"],
)
def test_email_endpoints_are_disabled_without_mutations(
    registration_client: TestClient, database: Database, endpoint: str
) -> None:
    before = counts(database)
    response = registration_client.post(
        "/api/v1/auth/" + endpoint, headers={"Origin": ORIGIN}, json={}
    )
    contract(response, 410, "email_flow_disabled")
    assert counts(database) == before
    captured = mail(registration_client)
    assert (
        captured.messages
        == captured.reset_messages
        == captured.registration_notices
        == captured.reset_notices
        == []
    )


def test_registration_requires_exact_origin(registration_client: TestClient) -> None:
    for origin in (None, "https://evil.example", ORIGIN + "/", TRUSTED_OTHER_ORIGIN):
        headers = {"Origin": origin} if origin else {}
        response = registration_client.post(
            "/api/v1/auth/register",
            headers=headers,
            json={"email": "new@example.com", "password": PASSWORD},
        )
        contract(response, 403, "csrf_failed")


def test_availability_needs_no_smtp_and_openapi_matches_current_contract(
    registration_client: TestClient,
) -> None:
    client = registration_client
    availability = client.get("/api/v1/auth/registration", headers={"Origin": ORIGIN})
    contract(availability, 200)
    assert availability.json() == {"enabled": True}
    paths = client.get("/openapi.json").json()["paths"]
    responses = paths["/api/v1/auth/register"]["post"]["responses"]
    assert {"201", "403", "409", "422", "429", "500", "503"} <= set(responses)
    assert (
        responses["201"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/RegistrationCreated"
    )
    for path in (
        "register/resend",
        "register/verify",
        "password/reset/request",
        "password/reset/confirm",
    ):
        operation = paths["/api/v1/auth/" + path]["post"]
        assert operation["deprecated"] is True
        assert "410" in operation["responses"]
        assert not any(status.startswith("2") for status in operation["responses"])
    app = cast(FastAPI, client.app)
    app.state.settings = app.state.settings.model_copy(update={"registration_enabled": False})
    assert client.get("/api/v1/auth/registration").json() == {"enabled": False}
    contract(register(client), 503, "registration_unavailable")
