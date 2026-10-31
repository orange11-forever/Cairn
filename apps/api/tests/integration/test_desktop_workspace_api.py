import base64
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import parse_qs
from uuid import UUID, uuid4

import httpx
import pytest
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.workspace.local import DesktopWorkspace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from apps.api.tests.integration.authorization_helpers import seed_actor
from apps.api.tests.integration.test_oauth_api import ORIGIN, oauth_client, password_login

__all__ = ["oauth_client"]


class RemoteState(TypedDict):
    poll: str
    user: int
    status: int
    repository_status: int


DesktopFixture = tuple[TestClient, DesktopWorkspace, RemoteState, list[httpx.Request], list[float]]


@pytest.fixture
def desktop_client(
    oauth_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[DesktopFixture]:
    from cairn_api.workspace.github import GitHubClient

    workspace = DesktopWorkspace(
        tmp_path, Path("/usr/bin/git"), "cairn-desktop-test", base64.b64encode, base64.b64decode
    )
    calls: list[httpx.Request] = []
    remote: RemoteState = {"poll": "pending", "user": 123, "status": 200, "repository_status": 200}

    def github(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/login/device/code":
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
        if request.url.path == "/login/oauth/access_token":
            body = (
                {"error": "authorization_pending"}
                if remote["poll"] == "pending"
                else {"access_token": "secret-access", "token_type": "bearer", "scope": "repo"}
            )
            return httpx.Response(200, json=body)
        if request.url.path == "/user":
            return httpx.Response(remote["status"], json={"id": remote["user"], "login": "octo"})
        if request.url.path == "/user/repos":
            return httpx.Response(remote["status"], json=[])
        if request.url.path == "/repositories/42":
            return httpx.Response(
                remote["repository_status"],
                json={
                    "id": 42,
                    "full_name": "octo/project",
                    "private": True,
                    "default_branch": "main",
                    "permissions": {"pull": True, "push": False},
                },
            )
        raise AssertionError(request.url)

    workspace.github = GitHubClient("cairn-desktop-test", transport=httpx.MockTransport(github))
    cast(FastAPI, oauth_client.app).state.desktop_workspace = workspace
    cast(FastAPI, oauth_client.app).state.oauth_providers = {}
    clock = [100.0]
    monkeypatch.setattr("cairn_api.workspace.device.time.monotonic", lambda: clock[0])
    yield oauth_client, workspace, remote, calls, clock


def start_device(
    client: TestClient, intent: str = "login", headers: dict[str, str] | None = None
) -> str:
    result = client.post(
        "/api/v1/desktop/github/device",
        json={"intent": intent},
        headers=headers or {"Origin": ORIGIN},
    )
    assert result.status_code == 200, result.text
    assert "secret-device" not in result.text
    assert result.headers["Cache-Control"] == "no-store"
    return result.json()["attemptId"]


def poll_device(
    client: TestClient, attempt: str, headers: dict[str, str] | None = None
) -> Response:
    return client.post(
        "/api/v1/desktop/github/device/poll",
        json={"attemptId": attempt},
        headers=headers or {"Origin": ORIGIN},
    )


@pytest.mark.integration
def test_device_login_requires_confirmation_and_does_not_grant_repository_access(
    desktop_client: DesktopFixture,
) -> None:
    client, workspace, remote, calls, clock = desktop_client
    assert client.get("/api/v1/auth/oauth/providers").json()[0] == {
        "provider": "github",
        "enabled": True,
    }
    attempt = start_device(client)
    assert parse_qs(calls[0].content.decode(), keep_blank_values=True)["scope"] == [""]
    clock[0] += 5
    assert poll_device(client, attempt).json()["status"] == "pending"
    remote["poll"] = "done"
    clock[0] += 5
    ready = poll_device(client, attempt)
    assert ready.json()["status"] == "login_ready", ready.text
    assert "secret-access" not in ready.text
    assert not client.cookies.get("cairn_session")
    confirmed = client.post("/api/v1/auth/oauth/finalize", headers={"Origin": ORIGIN})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["user"]["displayName"] == "octo"
    connection = client.get("/api/v1/desktop/github/connection")
    assert connection.json()["status"] == "disconnected"
    assert workspace.credential(UUID(confirmed.json()["user"]["id"])) is None


@pytest.mark.integration
def test_polling_interval_cancel_and_browser_binding(desktop_client: DesktopFixture) -> None:
    client, _, _, calls, clock = desktop_client
    attempt = start_device(client)
    assert poll_device(client, attempt).json()["status"] == "pending"
    assert len(calls) == 1
    stolen = client.cookies.get("cairn_github_device")
    client.cookies.delete("cairn_github_device")
    clock[0] += 5
    denied = poll_device(client, attempt)
    assert denied.status_code == 400
    assert denied.json()["traceId"] == denied.headers["X-Request-ID"]
    assert stolen is not None
    client.cookies.set("cairn_github_device", stolen)
    cancelled = client.request(
        "DELETE",
        "/api/v1/desktop/github/device",
        json={"attemptId": attempt},
        headers={"Origin": ORIGIN},
    )
    assert cancelled.status_code == 204
    assert poll_device(client, attempt).status_code == 400


@pytest.mark.integration
def test_repository_grant_requires_csrf_and_cannot_finish_after_logout(
    desktop_client: DesktopFixture,
) -> None:
    client, _, remote, _, clock = desktop_client
    headers = password_login(client)
    denied = client.post(
        "/api/v1/desktop/github/device", json={"intent": "repositories"}, headers={"Origin": ORIGIN}
    )
    assert denied.status_code == 403
    attempt = start_device(client, "repositories", headers)
    assert client.post("/api/v1/logout", headers=headers).status_code == 204
    remote["poll"] = "done"
    clock[0] += 5
    result = poll_device(client, attempt, headers)
    assert result.status_code in (401, 403, 409)


@pytest.mark.integration
def test_connected_token_is_private_persists_and_revocation_is_reported(
    desktop_client: DesktopFixture,
) -> None:
    client, workspace, remote, _, clock = desktop_client
    headers = password_login(client)
    attempt = start_device(client, "repositories", headers)
    remote["poll"] = "done"
    clock[0] += 5
    ready = poll_device(client, attempt, headers)
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "connected"
    state = client.get("/api/v1/desktop/github/connection")
    assert state.json()["account"] == {"id": 123, "login": "octo"}
    assert state.json()["status"] == "connected"
    assert "secret-access" not in json.dumps([ready.json(), state.json()])
    assert b"secret-access" not in (workspace.data / "workspace-settings.dpapi").read_bytes()
    remote["status"] = 401
    state = client.get("/api/v1/desktop/github/connection")
    assert state.json()["status"] == "revoked"
    repos = client.get("/api/v1/desktop/github/repositories")
    assert repos.status_code == 401
    assert repos.json()["code"] == "github_credentials_invalid"
    assert client.delete("/api/v1/desktop/github/connection", headers=headers).status_code == 204
    assert client.get("/api/v1/desktop/github/connection").json()["status"] == "disconnected"


@pytest.mark.integration
def test_project_repository_persists_enforces_acl_and_keeps_files_on_unbind(
    desktop_client: DesktopFixture, tmp_path: Path, database: Database
) -> None:
    client, workspace, _, _, _ = desktop_client
    headers = password_login(client)
    identity = client.get("/api/v1/session").json()
    created = client.post(
        "/api/v1/projects", json={"name": "Repository acceptance"}, headers=headers
    )
    assert created.status_code == 201
    project = created.json()["id"]
    path = tmp_path.parent / ("stage2-repository-" + str(uuid4()))
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-b", "main"], check=True, capture_output=True)
    (path / "work.txt").write_text("retained user work")
    route = f"/api/v1/desktop/projects/{project}/repository"
    denied = client.put(route, json={"localPath": str(path)}, headers={"Origin": ORIGIN})
    assert denied.status_code == 403
    saved = client.put(route, json={"localPath": str(path)}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["branch"] == "main"
    assert saved.json()["localPath"] == str(path)
    assert saved.headers["Cache-Control"] == "no-store"
    assert "X-Request-ID" in saved.headers
    cast(FastAPI, client.app).state.desktop_workspace = DesktopWorkspace(
        workspace.data, workspace.git, workspace.client_id, base64.b64encode, base64.b64decode
    )
    assert client.get(route).json()["binding"]["localPath"] == str(path)
    member = seed_actor(database, MembershipRole.VIEWER, UUID(identity["organization"]["id"]))
    assert client.post("/api/v1/logout", headers=headers).status_code == 204
    login = client.post(
        "/api/v1/login",
        json={"email": member.email, "password": member.password},
        headers={"Origin": ORIGIN},
    )
    member_headers = {"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrfToken"]}
    assert client.get(route).status_code == 200
    assert client.get(route).json()["binding"] is None
    assert (
        client.put(route, json={"localPath": str(path)}, headers=member_headers).status_code == 404
    )
    assert client.delete(route, headers=member_headers).status_code == 404
    assert client.post("/api/v1/logout", headers=member_headers).status_code == 204
    headers = password_login(client)
    assert client.delete(route, headers=headers).status_code == 204
    assert client.get(route).json()["binding"] is None
    assert (path / "work.txt").read_text() == "retained user work"


@pytest.mark.integration
def test_cancelling_a_completed_repository_grant_reports_completion(
    desktop_client: DesktopFixture,
) -> None:
    client, _, remote, _, clock = desktop_client
    headers = password_login(client)
    attempt = start_device(client, "repositories", headers)
    remote["poll"] = "done"
    clock[0] += 5
    assert poll_device(client, attempt, headers).json()["status"] == "connected"
    result = client.request(
        "DELETE", "/api/v1/desktop/github/device", json={"attemptId": attempt}, headers=headers
    )
    assert result.status_code == 409
    assert result.json()["code"] == "github_authorization_completed"


@pytest.mark.integration
def test_reopening_reports_repository_permission_loss_and_changed_origin(
    desktop_client: DesktopFixture, tmp_path: Path
) -> None:
    client, _, remote, _, clock = desktop_client
    headers = password_login(client)
    attempt = start_device(client, "repositories", headers)
    remote["poll"] = "done"
    clock[0] += 5
    assert poll_device(client, attempt, headers).json()["status"] == "connected"
    project = client.post(
        "/api/v1/projects", json={"name": "Remote status"}, headers=headers
    ).json()["id"]
    path = tmp_path.parent / ("stage2-origin-" + str(uuid4()))
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "remote", "add", "origin", "https://github.com/octo/project.git"],
        check=True,
    )
    route = f"/api/v1/desktop/projects/{project}/repository"
    saved = client.put(route, json={"localPath": str(path), "repositoryId": 42}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert client.get(route).json()["repositoryStatus"] == "available"
    remote["repository_status"] = 404
    inaccessible = client.get(route).json()
    assert inaccessible["repositoryStatus"] == "unavailable"
    assert "无权访问" in inaccessible["message"]
    assert inaccessible["binding"]["localPath"] == str(path)
    remote["repository_status"] = 200
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "remote",
            "set-url",
            "origin",
            "https://github.com/octo/other.git",
        ],
        check=True,
    )
    changed = client.get(route).json()
    assert changed["repositoryStatus"] == "changed"
    assert "origin" in changed["message"]
    assert changed["binding"]["repository"]["fullName"] == "octo/project"


@pytest.mark.integration
def test_clearing_repository_access_also_cancels_pending_grants(
    desktop_client: DesktopFixture,
) -> None:
    client, _, remote, _, clock = desktop_client
    headers = password_login(client)
    attempt = start_device(client, "repositories", headers)
    assert client.delete("/api/v1/desktop/github/connection", headers=headers).status_code == 204
    remote["poll"] = "done"
    clock[0] += 5
    assert poll_device(client, attempt, headers).status_code == 400
    assert client.get("/api/v1/desktop/github/connection").json()["status"] == "disconnected"


@pytest.mark.integration
def test_device_code_expiration_does_not_call_provider_again(
    desktop_client: DesktopFixture,
) -> None:
    client, _, _, calls, clock = desktop_client
    attempt = start_device(client)
    clock[0] += 301
    result = poll_device(client, attempt)
    assert result.status_code == 400
    assert result.json()["code"] == "github_authorization_expired"
    assert len(calls) == 1
