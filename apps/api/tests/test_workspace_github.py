import json
from urllib.parse import parse_qs

import httpx
import pytest
from cairn_api.errors import ApiProblem


def test_device_login_and_repository_grants_request_separate_scopes() -> None:
    from cairn_api.workspace.github import GitHubClient

    scopes: list[list[str]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://github.com/login/device/code"
        scopes.append(parse_qs(request.content.decode(), keep_blank_values=True)["scope"])
        return httpx.Response(
            200,
            json={
                "device_code": "secret-device",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "interval": 5,
                "expires_in": 900,
            },
        )

    client = GitHubClient("cairn-test", transport=httpx.MockTransport(upstream))
    login = client.start(repositories=False)
    repos = client.start(repositories=True)
    assert login.user_code == repos.user_code == "ABCD-EFGH"
    assert scopes == [[""], ["repo"]]


def test_device_poll_pending_slow_down_and_access_denied_are_distinct() -> None:
    from cairn_api.workspace.github import GitHubClient

    replies = iter(
        [{"error": "authorization_pending"}, {"error": "slow_down"}, {"error": "access_denied"}]
    )
    client = GitHubClient(
        "cairn-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=next(replies))),
    )
    assert client.poll("secret-device") == "pending"
    assert client.poll("secret-device") == "slow_down"
    with pytest.raises(ApiProblem) as failure:
        client.poll("secret-device")
    assert failure.value.code == "github_authorization_denied"


@pytest.mark.parametrize(
    "response",
    [
        {
            "device_code": "secret",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://evil.test/",
            "interval": 5,
            "expires_in": 900,
        },
        {"access_token": "secret", "token_type": "mac", "scope": "repo"},
    ],
)
def test_invalid_upstream_cannot_redirect_users_or_expose_tokens(
    response: dict[str, object],
) -> None:
    from cairn_api.workspace.github import GitHubClient

    client = GitHubClient(
        "cairn-test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    )
    with pytest.raises(ApiProblem) as failure:
        if "device_code" in response:
            client.start(repositories=False)
        else:
            client.poll("secret-device")
    assert failure.value.code == "github_invalid_response"
    assert "secret" not in str(failure.value)


def test_repository_listing_keeps_permission_and_pagination_and_ignores_upstream_urls() -> None:
    from cairn_api.workspace.github import GitHubClient

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.params["page"] == "2"
        assert request.headers["Authorization"] == "Bearer secret-token"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 42,
                    "full_name": "octo/project",
                    "private": True,
                    "default_branch": "main",
                    "permissions": {"pull": True, "push": False},
                    "clone_url": "https://evil.test/token",
                    "html_url": "https://evil.test/",
                }
            ],
        )

    page = GitHubClient("cairn-test", transport=httpx.MockTransport(upstream)).repositories(
        "secret-token", 2
    )
    assert page.items[0].full_name == "octo/project"
    assert page.items[0].can_push is False
    assert page.items[0].url == "https://github.com/octo/project"
    assert page.next_page is None
    assert "secret-token" not in page.model_dump_json()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "github_credentials_invalid"),
        (403, "github_permission_denied"),
        (404, "github_repository_unavailable"),
        (429, "github_rate_limited"),
        (500, "github_unavailable"),
    ],
)
def test_upstream_errors_preserve_actionable_category_without_response_body(
    status: int, code: str
) -> None:
    from cairn_api.workspace.github import GitHubClient

    client = GitHubClient(
        "cairn-test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text=json.dumps({"token": "never-echo"}))
        ),
    )
    with pytest.raises(ApiProblem) as failure:
        client.repository("secret-token", 42)
    assert failure.value.code == code
    assert "never-echo" not in str(failure.value)
