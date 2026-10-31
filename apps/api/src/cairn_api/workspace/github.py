"""GitHub's public-client device flow; upstream secrets never enter API responses."""

from typing import Literal, cast

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError

from cairn_api.errors import ApiProblem
from cairn_api.workspace.schemas import GitHubAccount, GitHubRepository, GitHubRepositoryPage


def github_problem(code: str, message: str, status: int = 502) -> ApiProblem:
    return ApiProblem(
        status_code=status,
        code=code,
        message=message,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


class DeviceCode(BaseModel):
    device_code: SecretStr = Field(min_length=1, max_length=1024)
    user_code: str = Field(pattern=r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")
    verification_uri: Literal["https://github.com/login/device"]
    expires_in: int = Field(ge=1, le=900, strict=True)
    interval: int = Field(ge=1, le=60, strict=True)


class GitHubToken(BaseModel):
    access_token: SecretStr = Field(min_length=1, max_length=4096)
    token_type: Literal["bearer"]
    scope: str = Field(default="", max_length=2000)
    expires_in: int | None = Field(default=None, gt=0, strict=True)


class RemoteAccount(BaseModel):
    id: int = Field(gt=0, strict=True)
    login: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")


class RemotePermissions(BaseModel):
    pull: bool
    push: bool


class RemoteRepository(BaseModel):
    id: int = Field(gt=0, strict=True)
    full_name: str
    private: bool
    default_branch: str
    permissions: RemotePermissions

    def public(self) -> GitHubRepository:
        if not self.permissions.pull or self.full_name.split("/")[-1] in {".", ".."}:
            raise ValueError("unreadable repository")
        return GitHubRepository(
            id=self.id,
            full_name=self.full_name,
            private=self.private,
            default_branch=self.default_branch,
            can_push=self.permissions.push,
        )


class GitHubClient:
    def __init__(self, client_id: str, *, transport: httpx.BaseTransport | None = None):
        self.client_id = client_id
        self._transport = transport

    def _request(
        self, method: str, url: str, *, token: str | None = None, data: dict[str, str] | None = None
    ) -> object:
        headers = {"Accept": "application/json", "User-Agent": "Cairn-desktop"}
        if token:
            headers.update(
                {"Authorization": "Bearer " + token, "X-GitHub-Api-Version": "2022-11-28"}
            )
        try:
            with httpx.Client(
                transport=self._transport, timeout=15, trust_env=False, follow_redirects=False
            ) as client:
                response = client.request(method, url, headers=headers, data=data)
            if response.status_code == 401:
                raise github_problem(
                    "github_credentials_invalid", "GitHub 授权已失效或被撤回，请重新授权", 401
                )
            if response.status_code == 429 or (
                response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0"
            ):
                raise github_problem(
                    "github_rate_limited", "GitHub 请求额度暂时耗尽，请稍后再试", 429
                )
            if response.status_code == 403:
                raise github_problem(
                    "github_permission_denied", "GitHub 拒绝访问，请检查仓库权限或组织授权", 403
                )
            if response.status_code == 404:
                raise github_problem(
                    "github_repository_unavailable", "仓库不存在或当前授权无权访问", 404
                )
            if response.status_code >= 500:
                raise github_problem("github_unavailable", "GitHub 服务暂时不可用，请稍后再试")
            if response.status_code != 200 or len(response.content) > 4_000_000:
                raise ValueError("unexpected response")
            return response.json()
        except httpx.RequestError:
            raise github_problem(
                "github_unavailable", "无法连接 GitHub，请检查网络后重试"
            ) from None
        except (ValueError, httpx.HTTPError):
            raise github_problem(
                "github_invalid_response", "GitHub 返回了无法识别的响应，请重新发起"
            ) from None

    def start(self, *, repositories: bool) -> DeviceCode:
        data = self._request(
            "POST",
            "https://github.com/login/device/code",
            data={"client_id": self.client_id, "scope": "repo" if repositories else ""},
        )
        if (
            isinstance(data, dict)
            and cast(dict[str, object], data).get("error") == "device_flow_disabled"
        ):
            raise github_problem(
                "github_device_flow_disabled",
                "Cairn 的 GitHub 授权应用尚未启用设备授权，请联系发布方",
                503,
            )
        try:
            return DeviceCode.model_validate(data)
        except ValidationError:
            raise github_problem(
                "github_invalid_response", "GitHub 设备授权响应无效，请检查授权应用配置"
            ) from None

    def poll(self, device_code: str) -> GitHubToken | Literal["pending", "slow_down"]:
        data = self._request(
            "POST",
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": self.client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        if isinstance(data, dict):
            error = cast(dict[str, object], data).get("error")
            if error == "authorization_pending":
                return "pending"
            if error == "slow_down":
                return "slow_down"
            if error == "access_denied":
                raise github_problem("github_authorization_denied", "已取消 GitHub 授权", 400)
            if error == "expired_token":
                raise github_problem(
                    "github_authorization_expired", "验证码已过期，请重新发起 GitHub 授权", 400
                )
        try:
            return GitHubToken.model_validate(data)
        except ValidationError:
            raise github_problem(
                "github_invalid_response", "GitHub 授权响应无效，请重新发起"
            ) from None

    def account(self, token: str) -> GitHubAccount:
        try:
            remote = RemoteAccount.model_validate(
                self._request("GET", "https://api.github.com/user", token=token)
            )
            return GitHubAccount(id=remote.id, login=remote.login)
        except ValidationError:
            raise github_problem("github_invalid_response", "GitHub 账号响应无效") from None

    def repositories(self, token: str, page: int) -> GitHubRepositoryPage:
        data = self._request(
            "GET",
            f"https://api.github.com/user/repos?per_page=50&page={page}&sort=full_name&direction=asc",
            token=token,
        )
        try:
            if not isinstance(data, list) or len(cast(list[object], data)) > 50:
                raise ValueError("invalid repository list")
            items = [
                RemoteRepository.model_validate(item).public() for item in cast(list[object], data)
            ]
            return GitHubRepositoryPage(
                items=items, next_page=page + 1 if len(items) == 50 else None
            )
        except (ValidationError, ValueError):
            raise github_problem("github_invalid_response", "GitHub 仓库列表响应无效") from None

    def repository(self, token: str, repository_id: int) -> GitHubRepository:
        try:
            remote = RemoteRepository.model_validate(
                self._request(
                    "GET", f"https://api.github.com/repositories/{repository_id}", token=token
                )
            ).public()
            if remote.id != repository_id:
                raise ValueError("repository identity mismatch")
            return remote
        except (ValidationError, ValueError):
            raise github_problem("github_invalid_response", "GitHub 仓库响应无效") from None
