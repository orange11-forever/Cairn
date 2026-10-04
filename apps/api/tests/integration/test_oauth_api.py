from collections.abc import Generator
from typing import cast
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from cairn_api.app import create_app
from cairn_api.auth.oauth_providers import ProviderIdentity
from cairn_api.db.session import Database
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text

ORIGIN = "http://localhost:5500"


class MockProvider:
    client_id = "test-client"

    def authorization_url(self, *, state: str, verifier: str, redirect_uri: str) -> str:
        return "https://provider.example/authorize?" + urlencode({"state": state})

    def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> ProviderIdentity:
        return ProviderIdentity(subject=code, display_name="Provider user")


@pytest.fixture()
def oauth_client(database: Database, migrated_engine: Engine) -> Generator[TestClient, None, None]:
    del migrated_engine
    settings = Settings(
        environment="test",
        database_url=str(database.engine.url.render_as_string(hide_password=False)),
        app_url=ORIGIN,
        cors_origins=[ORIGIN],
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    seed_demo_identity(settings, database)
    app = create_app(settings, database)
    app.state.oauth_providers = {"github": MockProvider(), "feishu": MockProvider()}
    with TestClient(app, raise_server_exceptions=False) as client:
        assert (
            client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code == 204
        )
        yield client


def password_login(client: TestClient) -> dict[str, str]:
    if not client.cookies.get("cairn_session_oauth_browser"):
        assert (
            client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code == 204
        )
    response = client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "demo@cairn.dev", "password": "cairn-demo-2026"},
    )
    assert response.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrfToken"]}


def start(
    client: TestClient,
    provider: str = "github",
    intent: str = "login",
    headers: dict[str, str] | None = None,
    return_to: str = "/projects",
) -> str:
    if intent == "login" and not client.cookies.get("cairn_session_oauth_browser"):
        assert (
            client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code == 204
        )
    response = client.post(
        f"/api/v1/auth/oauth/{provider}/start",
        headers=headers or {"Origin": ORIGIN},
        json={"intent": intent, "returnTo": return_to},
    )
    assert response.status_code == 200, response.text
    return parse_qs(urlsplit(str(response.json()["authorizationUrl"])).query)["state"][0]


def callback(
    client: TestClient, state: str, code: str = "remote-1", provider: str = "github"
) -> Response:
    return client.get(
        f"/api/v1/auth/oauth/{provider}/callback",
        params={"state": state, "code": code},
        follow_redirects=False,
    )


@pytest.mark.integration
def test_two_verified_providers_bind_to_one_account_and_login(oauth_client: TestClient) -> None:
    headers = password_login(oauth_client)
    before = oauth_client.cookies.get("cairn_session")
    for provider in ("github", "feishu"):
        state = start(oauth_client, provider, "link", headers, "/account/identities")
        result = callback(oauth_client, state, provider=provider)
        assert result.status_code == 303
        assert result.headers["location"] == ORIGIN + "/account/identities?oauth=linked"
        assert oauth_client.cookies.get("cairn_session") == before
    identities = oauth_client.get("/api/v1/auth/identities").json()
    assert {item["provider"] for item in identities["identities"]} == {"github", "feishu"}
    assert oauth_client.post("/api/v1/logout", headers=headers).status_code == 204
    for provider in ("github", "feishu"):
        state = start(oauth_client, provider)
        ready = callback(oauth_client, state, provider=provider)
        assert ready.status_code == 303
        assert (
            "set-cookie" not in ready.headers or "cairn_session=" not in ready.headers["set-cookie"]
        )
        assert (
            oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).status_code
            == 200
        )
        identity = oauth_client.get("/api/v1/session").json()
        assert identity["user"]["email"] == "demo@cairn.dev"
        assert identity["organization"]["slug"] == "cairn-demo"
        assert (
            oauth_client.post(
                "/api/v1/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": identity["csrfToken"]}
            ).status_code
            == 204
        )


@pytest.mark.integration
@pytest.mark.parametrize("provider", ["github", "feishu"])
def test_first_identity_registers_only_after_final_confirmation(
    oauth_client: TestClient, database: Database, provider: str
) -> None:
    counts = text(
        "SELECT (SELECT count(*) FROM users), "
        "(SELECT count(*) FROM organizations), "
        "(SELECT count(*) FROM memberships), "
        "(SELECT count(*) FROM external_identities), "
        "(SELECT count(*) FROM auth_sessions)"
    )
    with database.engine.connect() as connection:
        before = tuple(connection.execute(counts).one())
    ready = callback(
        oauth_client, start(oauth_client, provider), code="demo@cairn.dev", provider=provider
    )
    assert ready.status_code == 303
    assert ready.headers["location"] == ORIGIN + "/login?oauth=login_ready"
    assert ready.headers["cache-control"] == "no-store"
    assert ready.headers["referrer-policy"] == "no-referrer"
    assert oauth_client.cookies.get("cairn_session") is None
    with database.engine.connect() as connection:
        assert tuple(connection.execute(counts).one()) == before
    result = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})
    assert result.status_code == 200, result.text
    identity = result.json()
    assert identity["user"]["email"] is None
    assert identity["user"]["displayName"] == "Provider user"
    assert identity["membership"]["role"] == "owner"
    assert identity["organization"]["slug"] != "cairn-demo"
    assert result.headers["x-request-id"]
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["referrer-policy"] == "no-referrer"
    assert result.headers["access-control-allow-origin"] == ORIGIN
    assert result.headers["access-control-allow-credentials"] == "true"
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert oauth_client.get("/api/v1/session").json() == identity
    with database.engine.connect() as connection:
        assert tuple(connection.execute(counts).one()) == tuple(value + 1 for value in before)


@pytest.mark.integration
def test_login_csrf_origin_and_binding_csrf_are_required(oauth_client: TestClient) -> None:
    endpoint = "/api/v1/auth/oauth/github/start"
    assert oauth_client.post(endpoint, json={"intent": "login"}).status_code == 403
    assert (
        oauth_client.post(
            endpoint, headers={"Origin": "https://evil.example"}, json={"intent": "login"}
        ).status_code
        == 403
    )
    password_login(oauth_client)
    assert (
        oauth_client.post(endpoint, headers={"Origin": ORIGIN}, json={"intent": "link"}).status_code
        == 403
    )


@pytest.mark.integration
def test_callback_is_bound_to_browser_provider_and_single_use(oauth_client: TestClient) -> None:
    state = start(oauth_client)
    browser = oauth_client.cookies.get("cairn_session_oauth_github")
    login_browser = oauth_client.cookies.get("cairn_session_oauth_browser")
    oauth_client.cookies.clear()
    assert callback(oauth_client, state).status_code == 400
    oauth_client.cookies.set(
        "cairn_session_oauth_github", browser or "", path="/api/v1/auth/oauth/github"
    )
    oauth_client.cookies.set("cairn_session_oauth_browser", login_browser or "", path="/api/v1")
    assert callback(oauth_client, state, provider="feishu").status_code == 400
    assert callback(oauth_client, state).status_code == 303
    oauth_client.cookies.set(
        "cairn_session_oauth_github", browser or "", path="/api/v1/auth/oauth/github"
    )
    assert callback(oauth_client, state).status_code == 400


@pytest.mark.integration
def test_explicit_identity_owner_cannot_be_reassigned(
    oauth_client: TestClient, database: Database
) -> None:
    from uuid import uuid4

    from cairn_api.auth.models import User
    from cairn_api.auth.security import hash_password
    from cairn_api.organizations.models import Membership

    headers = password_login(oauth_client)
    state = start(oauth_client, intent="link", headers=headers)
    assert callback(oauth_client, state).status_code == 303
    user_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            User(
                id=user_id,
                email="other@cairn.dev",
                normalized_email="other@cairn.dev",
                password_hash=hash_password("other-test-password"),
            )
        )
        session.flush()
        session.add(
            Membership(
                user_id=user_id, org_id="00000000-0000-4000-8000-000000002001", role="member"
            )
        )
    oauth_client.post("/api/v1/logout", headers=headers)
    oauth_client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN})
    result = oauth_client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "other@cairn.dev", "password": "other-test-password"},
    )
    assert result.status_code == 200
    state = start(
        oauth_client,
        intent="link",
        headers={"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrfToken"]},
    )
    result = callback(oauth_client, state)
    assert "oauth=identity_conflict" in result.headers["location"]
    assert oauth_client.get("/api/v1/auth/identities").json()["identities"] == []


@pytest.mark.integration
def test_unlink_requires_csrf_recent_auth_and_keeps_last_factor(
    oauth_client: TestClient, database: Database
) -> None:
    headers = password_login(oauth_client)
    for provider in ("github", "feishu"):
        state = start(oauth_client, provider, "link", headers)
        assert callback(oauth_client, state, provider=provider).status_code == 303
    linked = oauth_client.get("/api/v1/auth/identities").json()["identities"]
    endpoint = "/api/v1/auth/identities/" + linked[0]["id"]
    assert oauth_client.delete(endpoint, headers={"Origin": ORIGIN}).status_code == 403
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE auth_sessions SET created_at = now() - interval '11 minutes'"))
    assert (
        oauth_client.delete(endpoint, headers=headers).json()["code"] == "reauthentication_required"
    )
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE auth_sessions SET created_at = now()"))
        session.execute(text("UPDATE users SET password_hash = NULL"))
    assert oauth_client.delete(endpoint, headers=headers).status_code == 204
    last = "/api/v1/auth/identities/" + linked[1]["id"]
    assert oauth_client.delete(last, headers=headers).json()["code"] == "last_login_method"
    assert len(oauth_client.get("/api/v1/auth/identities").json()["identities"]) == 1


@pytest.mark.integration
def test_unlink_cannot_remove_another_accounts_identity(
    oauth_client: TestClient, database: Database
) -> None:
    from uuid import uuid4

    from cairn_api.auth.models import User
    from cairn_api.auth.oauth_models import ExternalIdentity

    headers = password_login(oauth_client)
    foreign_id = uuid4()
    user_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            User(
                id=user_id,
                email="foreign@cairn.dev",
                normalized_email="foreign@cairn.dev",
                password_hash=None,
            )
        )
        session.flush()
        session.add(
            ExternalIdentity(
                id=foreign_id,
                user_id=user_id,
                provider="github",
                client_id="test-client",
                subject="foreign-remote",
            )
        )
    assert (
        oauth_client.delete(f"/api/v1/auth/identities/{foreign_id}", headers=headers).status_code
        == 404
    )
    with database.session_factory() as session:
        assert session.get(ExternalIdentity, foreign_id) is not None


@pytest.mark.integration
def test_invalid_callback_never_caches_authorization_material(oauth_client: TestClient) -> None:
    response = callback(oauth_client, "fake-state", code="test-private-code")
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "test-private-code" not in response.text


@pytest.mark.integration
def test_concurrent_unlink_cannot_remove_both_last_factors(
    oauth_client: TestClient, database: Database
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import UUID

    from cairn_api.auth.oauth_service import OAuthService
    from cairn_api.auth.service import RequestAuditContext
    from cairn_api.errors import ApiProblem

    headers = password_login(oauth_client)
    for provider in ("github", "feishu"):
        callback(oauth_client, start(oauth_client, provider, "link", headers), provider=provider)
    identities = oauth_client.get("/api/v1/auth/identities").json()["identities"]
    token = oauth_client.cookies.get("cairn_session")
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE users SET password_hash = NULL"))
    barrier = Barrier(2)
    settings = cast(Settings, cast(FastAPI, oauth_client.app).state.settings)

    def remove(value: str) -> str:
        barrier.wait(timeout=10)
        with database.session_factory() as session:
            try:
                OAuthService(session, settings).unlink(
                    identity_id=UUID(value),
                    session_token=token,
                    enabled_clients={"github": "test-client", "feishu": "test-client"},
                    audit=RequestAuditContext(
                        trace_id="concurrent-unlink", ip=None, user_agent=None
                    ),
                )
            except ApiProblem as exc:
                return exc.code
            return "removed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(remove, [str(item["id"]) for item in identities]))
    assert sorted(results) == ["last_login_method", "removed"]
    assert len(oauth_client.get("/api/v1/auth/identities").json()["identities"]) == 1


@pytest.mark.integration
def test_concurrent_provider_callbacks_only_establish_one_browser_session(
    oauth_client: TestClient, database: Database
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import UUID, uuid4

    from cairn_api.auth.models import User
    from cairn_api.auth.oauth_models import ExternalIdentity
    from cairn_api.organizations.models import Membership, Organization

    barrier = Barrier(2)

    class RacingProvider(MockProvider):
        def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> ProviderIdentity:
            barrier.wait(timeout=10)
            return ProviderIdentity(subject=code, display_name="Concurrent provider")

    app = cast(FastAPI, oauth_client.app)
    app.state.oauth_providers = {"github": RacingProvider(), "feishu": RacingProvider()}
    other_user, other_org = uuid4(), uuid4()
    with database.session_factory.begin() as session:
        session.add(
            User(
                id=other_user,
                email="other-race@cairn.dev",
                normalized_email="other-race@cairn.dev",
                password_hash=None,
            )
        )
        session.add(Organization(id=other_org, slug="other-race", name="Other"))
        session.flush()
        session.add(Membership(user_id=other_user, org_id=other_org, role="member"))
        session.add_all(
            [
                ExternalIdentity(
                    user_id=UUID("00000000-0000-4000-8000-000000001001"),
                    provider="github",
                    client_id="test-client",
                    subject="remote-a",
                ),
                ExternalIdentity(
                    user_id=other_user,
                    provider="feishu",
                    client_id="test-client",
                    subject="remote-b",
                ),
            ]
        )
    github_state, feishu_state = start(oauth_client), start(oauth_client, "feishu")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(callback, oauth_client, github_state, "remote-a", "github")
        second = executor.submit(callback, oauth_client, feishu_state, "remote-b", "feishu")
        results = [first.result(timeout=20), second.result(timeout=20)]
    assert all(result.status_code == 303 for result in results)
    assert all("cairn_session=" not in result.headers.get("set-cookie", "") for result in results)
    assert (
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).status_code
        == 200
    )
    assert (
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).status_code
        == 409
    )
    assert sum("oauth=session_changed" in result.headers["location"] for result in results) == 1


@pytest.mark.integration
def test_stale_session_cannot_start_binding(oauth_client: TestClient, database: Database) -> None:
    headers = password_login(oauth_client)
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE auth_sessions SET created_at = now() - interval '11 minutes'"))
    response = oauth_client.post(
        "/api/v1/auth/oauth/github/start", headers=headers, json={"intent": "link"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "reauthentication_required"


@pytest.mark.integration
def test_oauth_attempt_secrets_are_hashed_and_callback_is_not_host_derived(
    oauth_client: TestClient, database: Database
) -> None:
    result = oauth_client.post(
        "/api/v1/auth/oauth/github/start",
        headers={"Origin": ORIGIN, "Host": "evil.example"},
        json={"intent": "login"},
    )
    assert result.status_code == 200
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/api/v1/auth/oauth/github" in cookie
    state = parse_qs(urlsplit(str(result.json()["authorizationUrl"])).query)["state"][0]
    with database.session_factory() as session:
        row = session.execute(
            text(
                "SELECT state_digest, browser_digest FROM oauth_attempts WHERE consumed_at IS NULL ORDER BY expires_at DESC LIMIT 1"
            )
        ).one()
        assert bytes(row[0]) != state.encode()
        assert len(row[0]) == 32 and len(row[1]) == 32
    # Restore Host for browser cookie scope after the deliberate malicious Host request.
    result = callback(oauth_client, state)
    assert result.headers["location"].startswith(ORIGIN + "/login?")
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["referrer-policy"] == "no-referrer"


@pytest.mark.integration
def test_disabled_alternative_does_not_allow_last_method_unlink(
    oauth_client: TestClient, database: Database
) -> None:
    headers = password_login(oauth_client)
    for provider in ("github", "feishu"):
        state = start(oauth_client, provider, "link", headers)
        callback(oauth_client, state, provider=provider)
    identities = oauth_client.get("/api/v1/auth/identities").json()["identities"]
    providers = cast(dict[str, MockProvider], cast(FastAPI, oauth_client.app).state.oauth_providers)
    providers.pop("feishu")
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE users SET password_hash = NULL"))
    github = next(item for item in identities if item["provider"] == "github")
    assert (
        oauth_client.delete("/api/v1/auth/identities/" + github["id"], headers=headers).json()[
            "code"
        ]
        == "last_login_method"
    )


@pytest.mark.integration
def test_identity_query_revocation_uses_standard_session_expiry(
    oauth_client: TestClient, database: Database
) -> None:
    password_login(oauth_client)
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE auth_sessions SET revoked_at = now()"))
    response = oauth_client.get("/api/v1/auth/identities")
    assert response.status_code == 401
    assert response.json()["code"] == "session_invalid"
    assert "set-cookie" not in response.headers
    assert (
        oauth_client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code
        == 204
    )
    assert oauth_client.cookies.get("cairn_session") is None


@pytest.mark.integration
def test_provider_failure_consumes_state_and_preserves_session(oauth_client: TestClient) -> None:
    from cairn_api.auth.oauth_providers import ProviderFailure

    class FailingProvider(MockProvider):
        def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> ProviderIdentity:
            raise ProviderFailure()

    cast(FastAPI, oauth_client.app).state.oauth_providers = {"github": FailingProvider()}
    headers = password_login(oauth_client)
    token = oauth_client.cookies.get("cairn_session")
    state = start(oauth_client, intent="link", headers=headers)
    browser = oauth_client.cookies.get("cairn_session_oauth_github")
    assert "oauth=provider_failed" in callback(oauth_client, state).headers["location"]
    assert oauth_client.cookies.get("cairn_session") == token
    oauth_client.cookies.set(
        "cairn_session_oauth_github", browser or "", path="/api/v1/auth/oauth/github"
    )
    assert callback(oauth_client, state).status_code == 400


@pytest.mark.integration
def test_client_rotation_does_not_count_old_identity_as_available(
    oauth_client: TestClient, database: Database
) -> None:
    headers = password_login(oauth_client)
    for provider in ("github", "feishu"):
        callback(oauth_client, start(oauth_client, provider, "link", headers), provider=provider)
    identities = oauth_client.get("/api/v1/auth/identities").json()["identities"]
    providers = cast(dict[str, MockProvider], cast(FastAPI, oauth_client.app).state.oauth_providers)
    providers["feishu"].client_id = "rotated-client"
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE users SET password_hash = NULL"))
    github = next(item for item in identities if item["provider"] == "github")
    assert (
        oauth_client.delete("/api/v1/auth/identities/" + github["id"], headers=headers).json()[
            "code"
        ]
        == "last_login_method"
    )


@pytest.mark.integration
def test_binding_callback_rejects_changed_or_revoked_session(oauth_client: TestClient) -> None:
    headers = password_login(oauth_client)
    state = start(oauth_client, intent="link", headers=headers)
    oauth_client.post("/api/v1/logout", headers=headers)
    password_login(oauth_client)
    response = callback(oauth_client, state)
    assert response.status_code == 303
    assert response.headers["location"] == ORIGIN + "/account/identities?oauth=session_changed"
    assert oauth_client.get("/api/v1/auth/identities").json()["identities"] == []


@pytest.mark.integration
def test_login_callback_preserves_newly_authenticated_session(oauth_client: TestClient) -> None:
    state = start(oauth_client)
    password_login(oauth_client)
    session_cookie = oauth_client.cookies.get("cairn_session")
    response = callback(oauth_client, state)
    assert response.status_code == 303
    assert response.headers["location"] == ORIGIN + "/login?oauth=session_changed"
    assert oauth_client.cookies.get("cairn_session") == session_cookie


@pytest.mark.integration
@pytest.mark.parametrize(
    "return_to",
    ["https://evil.example", "//evil.example", "/\\evil", "/%2f%2fevil", "/projects?next=evil"],
)
def test_return_destination_is_allowlisted(oauth_client: TestClient, return_to: str) -> None:
    response = oauth_client.post(
        "/api/v1/auth/oauth/github/start",
        headers={"Origin": ORIGIN},
        json={"intent": "login", "returnTo": return_to},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_expired_and_cancelled_attempts_cannot_replay(
    oauth_client: TestClient, database: Database
) -> None:
    before = registration_counts(database)
    state = start(oauth_client)
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE oauth_attempts SET expires_at = now() - interval '1 minute'"))
    assert callback(oauth_client, state).status_code == 400
    state = start(oauth_client)
    result = oauth_client.get(
        "/api/v1/auth/oauth/github/callback",
        params={"state": state, "error": "access_denied"},
        follow_redirects=False,
    )
    assert result.status_code == 303
    assert "oauth=cancelled" in result.headers["location"]
    assert callback(oauth_client, state).status_code == 400
    assert_oauth_error(
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}),
        409,
        "session_changed",
    )
    assert registration_counts(database) == before


@pytest.mark.integration
def test_login_actions_require_bootstrapped_browser_context(oauth_client: TestClient) -> None:
    oauth_client.cookies.clear()
    response = oauth_client.post(
        "/api/v1/auth/oauth/github/start", headers={"Origin": ORIGIN}, json={"intent": "login"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "login_context_required"
    response = oauth_client.post(
        "/api/v1/login",
        headers={"Origin": ORIGIN},
        json={"email": "demo@cairn.dev", "password": "cairn-demo-2026"},
    )
    assert response.status_code == 409
    assert oauth_client.cookies.get("cairn_session") is None


@pytest.mark.integration
@pytest.mark.parametrize("linked", [False, True])
def test_logout_cancels_inflight_anonymous_oauth_callback(
    oauth_client: TestClient, database: Database, linked: bool
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from uuid import UUID

    from cairn_api.auth.oauth_models import ExternalIdentity

    entered, resume = Event(), Event()

    class WaitingProvider(MockProvider):
        def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> ProviderIdentity:
            entered.set()
            assert resume.wait(timeout=10)
            return ProviderIdentity(subject=code, display_name="Waiting provider")

    cast(FastAPI, oauth_client.app).state.oauth_providers = {"github": WaitingProvider()}
    with database.session_factory.begin() as session:
        if linked:
            session.add(
                ExternalIdentity(
                    user_id=UUID("00000000-0000-4000-8000-000000001001"),
                    provider="github",
                    client_id="test-client",
                    subject="remote-1",
                )
            )
    before = registration_counts(database)
    state = start(oauth_client)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(callback, oauth_client, state)
        assert entered.wait(timeout=10)
        try:
            assert (
                oauth_client.post("/api/v1/logout", headers={"Origin": ORIGIN}).status_code == 204
            )
        finally:
            resume.set()
        response = pending.result(timeout=15)
    assert "oauth=session_changed" in response.headers["location"]
    assert "cairn_session=" not in response.headers.get("set-cookie", "")
    assert registration_counts(database) == before
    with database.session_factory() as session:
        assert (
            session.scalar(text("SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL")) == 0
        )


@pytest.mark.integration
@pytest.mark.parametrize("linked", [False, True])
def test_logout_revokes_committed_callback_even_before_cookie_arrives(
    oauth_client: TestClient, database: Database, linked: bool
) -> None:
    from uuid import UUID

    from cairn_api.auth.oauth_models import ExternalIdentity

    # A callback commits its claim/session, while its response is delayed in transit.
    with database.session_factory.begin() as session:
        if linked:
            session.add(
                ExternalIdentity(
                    user_id=UUID("00000000-0000-4000-8000-000000001001"),
                    provider="github",
                    client_id="test-client",
                    subject="remote-1",
                )
            )
    response = callback(oauth_client, start(oauth_client))
    assert "cairn_session=" not in response.headers.get("set-cookie", "")
    assert (
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).status_code
        == 200
    )
    delayed_token = oauth_client.cookies.get("cairn_session")
    # Simulate logout sent before the browser received that response cookie.
    oauth_client.cookies.delete("cairn_session")
    assert oauth_client.post("/api/v1/logout", headers={"Origin": ORIGIN}).status_code == 204
    oauth_client.cookies.set("cairn_session", delayed_token or "", path="/")
    assert oauth_client.get("/api/v1/session").status_code == 401


@pytest.mark.integration
def test_new_attempt_refreshes_browser_claim_deadline(
    oauth_client: TestClient, database: Database
) -> None:
    with database.session_factory.begin() as session:
        session.execute(
            text("UPDATE browser_login_claims SET expires_at = now() + interval '1 second'")
        )
    start(oauth_client)
    with database.session_factory() as session:
        remaining = session.scalar(
            text("SELECT extract(epoch FROM (expires_at-now())) FROM browser_login_claims")
        )
        assert remaining is not None and remaining > 290


@pytest.mark.integration
def test_binding_rechecks_revocation_after_provider_exchange(
    oauth_client: TestClient, database: Database
) -> None:
    class RevokingProvider(MockProvider):
        def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> ProviderIdentity:
            with database.session_factory.begin() as session:
                session.execute(text("UPDATE auth_sessions SET revoked_at = now()"))
            return ProviderIdentity(subject=code, display_name="Revoked while exchanging")

    cast(FastAPI, oauth_client.app).state.oauth_providers = {"github": RevokingProvider()}
    headers = password_login(oauth_client)
    response = callback(oauth_client, start(oauth_client, intent="link", headers=headers))
    assert "oauth=session_changed" in response.headers["location"]
    with database.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM external_identities")) == 0


@pytest.mark.integration
def test_anonymous_restore_preserves_pending_browser_claim(oauth_client: TestClient) -> None:
    token = oauth_client.cookies.get("cairn_session_oauth_browser")
    assert oauth_client.get("/api/v1/session").status_code == 401
    assert oauth_client.cookies.get("cairn_session_oauth_browser") == token
    assert (
        oauth_client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code
        == 204
    )
    assert oauth_client.cookies.get("cairn_session_oauth_browser") == token


@pytest.mark.integration
def test_expired_session_can_prepare_a_new_login_context(
    oauth_client: TestClient, database: Database
) -> None:
    password_login(oauth_client)
    previous = oauth_client.cookies.get("cairn_session_oauth_browser")
    with database.session_factory.begin() as session:
        session.execute(text("UPDATE auth_sessions SET expires_at = now() - interval '1 minute'"))
    assert oauth_client.get("/api/v1/session").status_code == 401
    assert (
        oauth_client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code
        == 204
    )
    assert oauth_client.cookies.get("cairn_session_oauth_browser") != previous
    assert password_login(oauth_client)["X-CSRF-Token"]


@pytest.mark.integration
def test_stale_anonymous_or_expired_queries_never_delete_new_login_cookie(
    oauth_client: TestClient,
) -> None:
    # Capture an anonymous response and simulate it arriving after a sign-in.
    old_anonymous = oauth_client.get("/api/v1/session")
    assert old_anonymous.status_code == 401
    assert "set-cookie" not in old_anonymous.headers
    password_login(oauth_client)
    current = oauth_client.cookies.get("cairn_session")
    assert current
    # Stale credential queries preserve both the newer cookie and browser claim.
    old_expired = oauth_client.get(
        "/api/v1/session", headers={"Cookie": "cairn_session=old-expired-session"}
    )
    assert old_expired.status_code == 401
    assert "set-cookie" not in old_expired.headers
    assert oauth_client.cookies.get("cairn_session") == current
    assert oauth_client.get("/api/v1/session").status_code == 200
    assert (
        oauth_client.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code
        == 409
    )
    assert oauth_client.cookies.get("cairn_session") == current


@pytest.mark.integration
def test_delayed_callback_cannot_overwrite_login_after_logout(
    oauth_client: TestClient, database: Database
) -> None:
    from uuid import UUID

    from cairn_api.auth.oauth_models import ExternalIdentity

    with database.session_factory.begin() as session:
        session.add(
            ExternalIdentity(
                user_id=UUID("00000000-0000-4000-8000-000000001001"),
                provider="github",
                client_id="test-client",
                subject="remote-1",
            )
        )
    delayed = callback(oauth_client, start(oauth_client))
    assert "oauth=login_ready" in delayed.headers["location"]
    assert "set-cookie" not in delayed.headers
    with database.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM auth_sessions")) == 0
    assert oauth_client.post("/api/v1/logout", headers={"Origin": ORIGIN}).status_code == 204
    password_login(oauth_client)
    new_token = oauth_client.cookies.get("cairn_session")
    # Receiving the captured callback now cannot mutate any newer cookies.
    assert "set-cookie" not in delayed.headers
    assert (
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).status_code
        == 409
    )
    assert oauth_client.cookies.get("cairn_session") == new_token
    assert oauth_client.get("/api/v1/session").status_code == 200


@pytest.mark.integration
def test_finalize_requires_origin_pending_identity_and_rechecks_enabled_provider(
    oauth_client: TestClient, database: Database
) -> None:
    from uuid import UUID

    from cairn_api.auth.oauth_models import ExternalIdentity

    endpoint = "/api/v1/auth/oauth/finalize"
    assert oauth_client.post(endpoint).status_code == 403
    assert oauth_client.post(endpoint, headers={"Origin": ORIGIN}).status_code == 409
    with database.session_factory.begin() as session:
        session.add(
            ExternalIdentity(
                user_id=UUID("00000000-0000-4000-8000-000000001001"),
                provider="github",
                client_id="test-client",
                subject="remote-1",
            )
        )
    assert "login_ready" in callback(oauth_client, start(oauth_client)).headers["location"]
    cast(FastAPI, oauth_client.app).state.oauth_providers = {}
    assert oauth_client.post(endpoint, headers={"Origin": ORIGIN}).status_code == 409
    assert oauth_client.cookies.get("cairn_session") is None


@pytest.mark.integration
def test_finalize_rechecks_identity_unlink_and_expiry(
    oauth_client: TestClient, database: Database
) -> None:
    from uuid import UUID

    from cairn_api.auth.oauth_models import ExternalIdentity

    with database.session_factory.begin() as session:
        session.add(
            ExternalIdentity(
                user_id=UUID("00000000-0000-4000-8000-000000001001"),
                provider="github",
                client_id="test-client",
                subject="remote-1",
            )
        )
    assert "login_ready" in callback(oauth_client, start(oauth_client)).headers["location"]
    with database.session_factory.begin() as session:
        session.execute(text("DELETE FROM external_identities"))
    assert (
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).status_code
        == 409
    )
    with database.session_factory.begin() as session:
        session.execute(
            text("UPDATE browser_login_claims SET expires_at = now() - interval '1 minute'")
        )
    assert (
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).status_code
        == 409
    )


def registration_counts(database: Database) -> tuple[int, ...]:
    with database.engine.connect() as connection:
        return tuple(
            connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM organizations), "
                    "(SELECT count(*) FROM memberships), (SELECT count(*) FROM external_identities), "
                    "(SELECT count(*) FROM auth_sessions), (SELECT count(*) FROM audit_logs)"
                )
            ).one()
        )


def assert_oauth_error(
    response: Response, status: int, code: str, *, trusted_origin: bool = True
) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"message", "code", "traceId"}
    assert body["code"] == code
    assert body["message"]
    assert body["traceId"] == response.headers["x-request-id"]
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    if trusted_origin:
        assert response.headers["access-control-allow-origin"] == ORIGIN
    else:
        assert "access-control-allow-origin" not in response.headers
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "set-cookie" not in response.headers


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["database", "unexpected"])
def test_registration_audit_failure_rolls_back_every_fact_and_can_retry(
    oauth_client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from cairn_api.auth import oauth_service
    from sqlalchemy.exc import OperationalError

    before = registration_counts(database)
    assert "login_ready" in callback(oauth_client, start(oauth_client)).headers["location"]

    def fail(*args: object, **kwargs: object) -> None:
        if failure == "database":
            raise OperationalError("audit unavailable", {}, RuntimeError("local failure"))
        raise RuntimeError("private unexpected error")

    with monkeypatch.context() as patch:
        patch.setattr(oauth_service, "add_audit_log", fail)
        response = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})
    assert_oauth_error(
        response,
        503 if failure == "database" else 500,
        "database_unavailable" if failure == "database" else "internal_error",
    )
    assert "private" not in response.text
    assert registration_counts(database) == before
    assert oauth_client.cookies.get("cairn_session") is None
    assert (
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).status_code
        == 200
    )


@pytest.mark.integration
@pytest.mark.parametrize("change", ["expired", "logout", "disabled", "rotated"])
def test_pending_registration_rechecks_claim_and_provider_without_creating_accounts(
    oauth_client: TestClient, database: Database, change: str
) -> None:
    before = registration_counts(database)
    assert "login_ready" in callback(oauth_client, start(oauth_client)).headers["location"]
    if change == "expired":
        with database.session_factory.begin() as session:
            session.execute(
                text("UPDATE browser_login_claims SET expires_at = now() - interval '1 minute'")
            )
    elif change == "logout":
        assert oauth_client.post("/api/v1/logout", headers={"Origin": ORIGIN}).status_code == 204
    else:
        providers = cast(
            dict[str, MockProvider], cast(FastAPI, oauth_client.app).state.oauth_providers
        )
        if change == "disabled":
            providers.clear()
        else:
            providers["github"].client_id = "rotated"
    result = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})
    assert_oauth_error(
        result,
        409,
        "session_changed" if change in ("expired", "logout") else "provider_not_configured",
    )
    assert registration_counts(database) == before


@pytest.mark.integration
@pytest.mark.parametrize("same_browser", [False, True])
def test_concurrent_registration_finalizes_once_without_orphan_accounts(
    oauth_client: TestClient, database: Database, same_browser: bool
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    app = cast(FastAPI, oauth_client.app)
    before = registration_counts(database)
    assert "login_ready" in callback(oauth_client, start(oauth_client)).headers["location"]
    other = TestClient(app, raise_server_exceptions=False)
    if same_browser:
        other.cookies.update(oauth_client.cookies)
    else:
        assert (
            other.post("/api/v1/auth/login-context", headers={"Origin": ORIGIN}).status_code == 204
        )
        assert "login_ready" in callback(other, start(other)).headers["location"]
    barrier = Barrier(2)

    def confirm(client: TestClient) -> Response:
        barrier.wait(timeout=10)
        return client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(confirm, (oauth_client, other)))
    assert sorted(result.status_code for result in responses) == [200, 409]
    rejected = next(result for result in responses if result.status_code == 409)
    assert_oauth_error(rejected, 409, "session_changed" if same_browser else "identity_conflict")
    after = registration_counts(database)
    assert after[:5] == tuple(value + 1 for value in before[:5])
    assert after[5] == before[5] + 2
    other.close()


@pytest.mark.integration
def test_registered_account_is_isolated_and_can_bind_second_identity_and_relogin(
    oauth_client: TestClient, database: Database
) -> None:
    headers = password_login(oauth_client)
    old_project = oauth_client.post(
        "/api/v1/projects", headers=headers, json={"name": "Existing"}
    ).json()
    assert oauth_client.post("/api/v1/logout", headers=headers).status_code == 204
    callback(oauth_client, start(oauth_client), code="new-person")
    identity = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).json()
    org_id = identity["organization"]["id"]
    denied = oauth_client.get("/api/v1/projects/" + old_project["id"])
    assert denied.status_code == 404
    assert denied.json()["traceId"] == denied.headers["x-request-id"]
    assert oauth_client.get("/api/v1/projects").json()["items"] == []
    assert (
        oauth_client.get(
            "/api/v1/projects/" + old_project["id"] + "/knowledge/resources"
        ).status_code
        == 404
    )
    assert (
        oauth_client.get("/api/v1/organizations/00000000-0000-4000-8000-000000002001").status_code
        == 404
    )
    members = oauth_client.get(f"/api/v1/organizations/{org_id}/memberships").json()["items"]
    assert len(members) == 1 and members[0]["email"] is None
    headers = {"Origin": ORIGIN, "X-CSRF-Token": identity["csrfToken"]}
    own = oauth_client.post("/api/v1/projects", headers=headers, json={"name": "Personal"})
    assert own.status_code == 201
    assert oauth_client.get("/api/v1/projects/" + own.json()["id"]).status_code == 200
    with database.engine.connect() as connection:
        assert (
            str(
                connection.scalar(
                    text("SELECT org_id FROM projects WHERE id = :id"), {"id": own.json()["id"]}
                )
            )
            == org_id
        )
    linked = oauth_client.get("/api/v1/auth/identities").json()
    assert linked["passwordAvailable"] is False
    last_id = linked["identities"][0]["id"]
    assert_oauth_error(
        oauth_client.delete("/api/v1/auth/identities/" + last_id, headers=headers),
        409,
        "last_login_method",
    )
    assert (
        "oauth=linked"
        in callback(
            oauth_client,
            start(oauth_client, "feishu", "link", headers),
            code="second",
            provider="feishu",
        ).headers["location"]
    )
    before = registration_counts(database)
    for provider, subject in (("github", "new-person"), ("feishu", "second")):
        assert oauth_client.post("/api/v1/logout", headers=headers).status_code == 204
        callback(oauth_client, start(oauth_client, provider), code=subject, provider=provider)
        response = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        restored = response.json()
        assert restored["user"]["id"] == identity["user"]["id"]
        assert restored["organization"]["id"] == org_id
        headers["X-CSRF-Token"] = restored["csrfToken"]
    assert registration_counts(database)[:4] == before[:4]


@pytest.mark.integration
@pytest.mark.parametrize("when", ["callback", "finalize"])
def test_disabled_linked_user_cannot_turn_into_registration(
    oauth_client: TestClient, database: Database, when: str
) -> None:
    headers = password_login(oauth_client)
    callback(oauth_client, start(oauth_client, intent="link", headers=headers))
    oauth_client.post("/api/v1/logout", headers=headers)
    before = registration_counts(database)
    state = start(oauth_client)
    if when == "callback":
        with database.session_factory.begin() as session:
            session.execute(text("UPDATE users SET is_active = false"))
    response = callback(oauth_client, state)
    if when == "callback":
        assert "oauth=identity_not_linked" in response.headers["location"]
    else:
        assert "oauth=login_ready" in response.headers["location"]
        with database.session_factory.begin() as session:
            session.execute(text("UPDATE users SET is_active = false"))
        assert_oauth_error(
            oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}),
            409,
            "identity_not_linked",
        )
    assert registration_counts(database) == before


@pytest.mark.integration
def test_pending_registration_cannot_replace_identity_bound_before_final_confirmation(
    oauth_client: TestClient, database: Database
) -> None:
    callback(oauth_client, start(oauth_client))
    app = cast(FastAPI, oauth_client.app)
    other = TestClient(app)
    headers = password_login(other)
    callback(other, start(other, intent="link", headers=headers))
    before = registration_counts(database)
    assert_oauth_error(
        oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}),
        409,
        "identity_conflict",
    )
    assert registration_counts(database) == before
    other.close()


@pytest.mark.integration
def test_registration_validation_and_method_errors_preserve_pending_confirmation(
    oauth_client: TestClient, database: Database
) -> None:
    before = registration_counts(database)
    invalid = oauth_client.post(
        "/api/v1/auth/oauth/github/start", headers={"Origin": ORIGIN}, json={"intent": "invalid"}
    )
    assert_oauth_error(invalid, 422, "validation_error")
    callback(oauth_client, start(oauth_client))
    endpoint = "/api/v1/auth/oauth/finalize"
    assert_oauth_error(
        oauth_client.post(endpoint, headers={"Origin": "https://evil.example"}),
        403,
        "csrf_failed",
        trusted_origin=False,
    )
    wrong_method = oauth_client.get(endpoint, headers={"Origin": ORIGIN})
    assert_oauth_error(wrong_method, 405, "method_not_allowed")
    assert wrong_method.headers["allow"] == "POST"
    assert registration_counts(database) == before
    assert oauth_client.post(endpoint, headers={"Origin": ORIGIN}).status_code == 200
    assert_oauth_error(
        oauth_client.post(endpoint, headers={"Origin": ORIGIN}), 409, "session_changed"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "name,expected",
    [(None, "Cairn 用户"), ("   ", "Cairn 用户"), (" 名" + "称" * 150, "名" + "称" * 119)],
)
def test_registration_display_name_is_bounded_and_has_nonempty_fallback(
    oauth_client: TestClient, name: str | None, expected: str
) -> None:
    class NamedProvider(MockProvider):
        def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> ProviderIdentity:
            return ProviderIdentity(subject=code, display_name=name)

    cast(FastAPI, oauth_client.app).state.oauth_providers = {"github": NamedProvider()}
    callback(oauth_client, start(oauth_client))
    result = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})
    assert result.status_code == 200
    assert result.json()["user"]["displayName"] == expected


@pytest.mark.integration
def test_two_subjects_with_same_provider_name_have_separate_personal_accounts(
    oauth_client: TestClient, database: Database
) -> None:
    before = registration_counts(database)
    callback(oauth_client, start(oauth_client), code="subject-a")
    first = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN}).json()
    assert (
        oauth_client.post(
            "/api/v1/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": first["csrfToken"]}
        ).status_code
        == 204
    )
    callback(oauth_client, start(oauth_client), code="subject-b")
    result = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})
    assert result.status_code == 200
    second = result.json()
    assert second["user"]["displayName"] == first["user"]["displayName"]
    assert second["user"]["id"] != first["user"]["id"]
    assert second["organization"]["id"] != first["organization"]["id"]
    assert registration_counts(database)[:4] == tuple(value + 2 for value in before[:4])


@pytest.mark.integration
def test_registration_openapi_declares_nullable_consumers_and_failure_contract(
    oauth_client: TestClient,
) -> None:
    document = oauth_client.get("/openapi.json").json()
    response = document["paths"]["/api/v1/auth/oauth/finalize"]["post"]["responses"]
    for status in ("409", "500", "503"):
        assert (
            response[status]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/ErrorBody"
        )
    schemas = document["components"]["schemas"]
    for name in ("UserResponse", "MembershipDetailResponse"):
        assert {item["type"] for item in schemas[name]["properties"]["email"]["anyOf"]} == {
            "string",
            "null",
        }
    assert schemas["LoginRequest"]["properties"]["email"]["type"] == "string"


@pytest.mark.integration
def test_identity_binding_wins_mid_registration_without_orphan_account(
    oauth_client: TestClient, database: Database
) -> None:
    from sqlalchemy import event

    # Explicit binding commits after finalize's lookup but before its INSERT.
    other = TestClient(cast(FastAPI, oauth_client.app), raise_server_exceptions=False)
    headers = password_login(other)
    link_state = start(other, intent="link", headers=headers)
    callback(oauth_client, start(oauth_client))
    before = registration_counts(database)
    bound = False

    def bind_during_insert(*args: object) -> None:
        nonlocal bound
        statement = str(args[2])
        if not bound and statement.startswith("INSERT INTO users"):
            bound = True
            result = callback(other, link_state)
            assert "oauth=linked" in result.headers["location"]

    event.listen(database.engine, "before_cursor_execute", bind_during_insert)
    try:
        result = oauth_client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})
    finally:
        event.remove(database.engine, "before_cursor_execute", bind_during_insert)
        other.close()
    assert bound
    assert_oauth_error(result, 409, "identity_conflict")
    after = registration_counts(database)
    assert after[:3] == before[:3]
    assert after[3] == before[3] + 1
    assert after[4] == before[4]
    assert after[5] == before[5] + 1
