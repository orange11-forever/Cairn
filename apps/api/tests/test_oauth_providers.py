import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest


def test_github_uses_pkce_and_fetches_stable_id_not_email() -> None:
    from cairn_api.auth.oauth_providers import HttpOAuthProvider

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("access_token"):
            return httpx.Response(200, json={"access_token": "test-token", "token_type": "bearer"})
        return httpx.Response(200, json={"id": 42, "login": "name", "email": "existing@cairn.dev"})

    provider = HttpOAuthProvider(
        "github", "test-client", "test-secret", httpx.MockTransport(respond)
    )
    query = parse_qs(
        urlsplit(
            provider.authorization_url(
                state="state", verifier="v" * 43, redirect_uri="https://app.example/callback"
            )
        ).query
    )
    assert query["code_challenge_method"] == ["S256"]
    assert "scope" not in query
    identity = provider.exchange(
        code="test-code", verifier="v" * 43, redirect_uri="https://app.example/callback"
    )
    assert identity.subject == "42"
    assert requests[1].url == "https://api.github.com/user"
    assert requests[1].headers["authorization"] == "Bearer test-token"
    assert parse_qs(requests[0].content.decode())["code_verifier"] == ["v" * 43]


def test_feishu_uses_v2_token_and_app_scoped_open_id() -> None:
    from cairn_api.auth.oauth_providers import HttpOAuthProvider

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("oauth/token"):
            return httpx.Response(200, json={"code": 0, "access_token": "test-token"})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"open_id": "ou-test", "name": "Test", "email": "existing@cairn.dev"},
            },
        )

    provider = HttpOAuthProvider("feishu", "test-app", "test-secret", httpx.MockTransport(respond))
    query = parse_qs(
        urlsplit(
            provider.authorization_url(
                state="state", verifier="v" * 43, redirect_uri="https://app.example/callback"
            )
        ).query
    )
    assert query["response_type"] == ["code"]
    assert "scope" not in query
    assert (
        provider.exchange(
            code="code", verifier="v" * 43, redirect_uri="https://app.example/callback"
        ).subject
        == "ou-test"
    )
    assert requests[0].url == "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    assert json.loads(requests[0].content)["redirect_uri"] == "https://app.example/callback"


@pytest.mark.parametrize(
    "response", [{"id": True}, {"id": "42"}, {"email": "existing@cairn.dev"}, {"id": -1}]
)
def test_github_rejects_missing_or_invalid_stable_subject(response: dict[str, object]) -> None:
    from cairn_api.auth.oauth_providers import HttpOAuthProvider, ProviderFailure

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("access_token"):
            return httpx.Response(200, json={"access_token": "test-token"})
        return httpx.Response(200, json=response)

    provider = HttpOAuthProvider("github", "client", "secret", httpx.MockTransport(respond))
    with pytest.raises(ProviderFailure):
        provider.exchange(
            code="code", verifier="v" * 43, redirect_uri="https://app.example/callback"
        )
