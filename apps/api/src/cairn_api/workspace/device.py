"""Short-lived device codes stay in memory and are bound to one browser and session."""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import Request, Response
from pydantic import SecretStr
from sqlalchemy.orm import Session

from cairn_api.auth.csrf import require_mutation_csrf
from cairn_api.auth.dependencies import get_audit_context, get_request_settings
from cairn_api.auth.oauth_claims import browser_cookie_name
from cairn_api.auth.oauth_providers import HttpOAuthProvider, ProviderIdentity
from cairn_api.auth.oauth_schemas import OAuthStartRequest
from cairn_api.auth.oauth_service import ATTEMPT_TTL, OAuthService, StartedAttempt
from cairn_api.auth.router import require_login_origin
from cairn_api.auth.security import digest_token
from cairn_api.auth.service import AuthService
from cairn_api.errors import ApiProblem
from cairn_api.workspace.github import DeviceCode, github_problem
from cairn_api.workspace.schemas import GitHubDeviceResult, GitHubDeviceStarted

if TYPE_CHECKING:
    from cairn_api.workspace.local import DesktopWorkspace

DEVICE_COOKIE = "cairn_github_device"


@dataclass
class DeviceAttempt:
    intent: Literal["login", "link", "repositories"]
    browser: str
    session_digest: bytes | None
    login_browser_digest: bytes
    user_id: UUID | None
    code: DeviceCode
    started: StartedAttempt | None
    expires_at: float
    next_poll: float
    interval: int
    result: GitHubDeviceResult | None = None


class DeviceAuthorizations:
    def __init__(self) -> None:
        self.attempts: dict[str, DeviceAttempt] = {}
        self.last_start: dict[bytes, float] = {}

    def start(
        self,
        workspace: DesktopWorkspace,
        intent: Literal["login", "link", "repositories"],
        request: Request,
        response: Response,
        session: Session,
    ) -> GitHubDeviceStarted:
        settings = get_request_settings(request)
        require_login_origin(request, settings)
        if workspace.github is None:
            raise github_problem(
                "provider_not_configured",
                "此安装包尚未配置 Cairn GitHub 授权应用，请联系发布方",
                503,
            )
        token = request.cookies.get(settings.session_cookie_name)
        login_browser = request.cookies.get(browser_cookie_name(settings.session_cookie_name))
        user_id = None
        if intent != "login":
            require_mutation_csrf(request)
            identity = AuthService(session, settings).restore(
                session_token=token, audit=get_audit_context(request)
            )
            user_id = identity.user.id
        now = time.monotonic()
        with workspace.lock:
            self.attempts = {
                key: value for key, value in self.attempts.items() if value.expires_at > now
            }
            self.last_start = {
                key: value for key, value in self.last_start.items() if value + 15 > now
            }
            rate_key = digest_token(token or login_browser or "anonymous")
            if rate_key in self.last_start or len(self.attempts) >= 64:
                raise github_problem("github_rate_limited", "授权请求过于频繁，请稍后再试", 429)
            started = None
            if intent != "repositories":
                started = OAuthService(session, settings).start(
                    provider="github",
                    adapter=HttpOAuthProvider("github", workspace.github.client_id, ""),
                    payload=OAuthStartRequest(intent=intent),
                    session_token=token,
                    audit=get_audit_context(request),
                    login_browser=login_browser,
                )
            code = workspace.github.start(repositories=intent == "repositories")
            lifetime = min(code.expires_in, ATTEMPT_TTL)
            browser, attempt_id = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            previous = request.cookies.get(DEVICE_COOKIE)
            self.attempts = {
                key: value for key, value in self.attempts.items() if value.browser != previous
            }
            self.attempts[attempt_id] = DeviceAttempt(
                intent,
                browser,
                digest_token(token) if token else None,
                digest_token(login_browser or ""),
                user_id,
                code,
                started,
                now + lifetime,
                now + code.interval,
                code.interval,
            )
            self.last_start[rate_key] = now
            response.set_cookie(
                DEVICE_COOKIE,
                browser,
                max_age=lifetime,
                path="/api/v1/desktop/github",
                httponly=True,
                secure=settings.session_cookie_secure,
                samesite="strict",
            )
            return GitHubDeviceStarted(
                attempt_id=attempt_id,
                user_code=code.user_code,
                expires_in=lifetime,
                interval=code.interval,
            )

    def _attempt(self, attempt_id: str, request: Request, session: Session) -> DeviceAttempt:
        settings = get_request_settings(request)
        require_login_origin(request, settings)
        attempt = self.attempts.get(attempt_id)
        browser = request.cookies.get(DEVICE_COOKIE, "")
        if (
            attempt is None
            or attempt.expires_at <= time.monotonic()
            or not browser.isascii()
            or not hmac.compare_digest(attempt.browser, browser)
        ):
            raise github_problem(
                "github_authorization_expired", "授权请求无效或已过期，请重新发起", 400
            )
        token = request.cookies.get(settings.session_cookie_name)
        if (digest_token(token) if token else None) != attempt.session_digest:
            raise github_problem(
                "session_changed", "当前登录状态已改变，请重新发起 GitHub 授权", 409
            )
        if attempt.intent != "login":
            require_mutation_csrf(request)
            identity = AuthService(session, settings).restore(
                session_token=token, audit=get_audit_context(request)
            )
            if identity.user.id != attempt.user_id:
                raise github_problem("session_changed", "当前登录状态已改变，请重新授权", 409)
        elif (
            digest_token(request.cookies.get(browser_cookie_name(settings.session_cookie_name), ""))
            != attempt.login_browser_digest
        ):
            raise github_problem("session_changed", "登录页面已重置，请重新发起 GitHub 授权", 409)
        return attempt

    def poll(
        self, workspace: DesktopWorkspace, attempt_id: str, request: Request, session: Session
    ) -> GitHubDeviceResult:
        with workspace.lock:
            attempt = self._attempt(attempt_id, request, session)
            if attempt.result:
                return attempt.result
            now = time.monotonic()
            if now < attempt.next_poll:
                return GitHubDeviceResult(status="pending", interval=attempt.interval)
            assert workspace.github is not None
            try:
                result = workspace.github.poll(attempt.code.device_code.get_secret_value())
                if isinstance(result, str):
                    if result == "slow_down":
                        attempt.interval += 5
                    attempt.next_poll = time.monotonic() + attempt.interval
                    return GitHubDeviceResult(status="pending", interval=attempt.interval)
                account = workspace.github.account(result.access_token.get_secret_value())
                settings = get_request_settings(request)
                if attempt.intent == "repositories":
                    assert attempt.user_id is not None
                    workspace.connect(attempt.user_id, account, result)
                    outcome: Literal["connected", "linked", "login_ready"] = "connected"
                else:
                    assert attempt.started is not None
                    service = OAuthService(session, settings)
                    login_browser = request.cookies.get(
                        browser_cookie_name(settings.session_cookie_name)
                    )
                    consumed = service.consume(
                        provider="github",
                        client_id=workspace.github.client_id,
                        state=attempt.started.state,
                        browser=attempt.started.browser,
                        login_browser=login_browser,
                    )
                    token = request.cookies.get(settings.session_cookie_name)
                    service.validate_callback_session(consumed, token)
                    service.finish(
                        provider="github",
                        adapter=HttpOAuthProvider("github", workspace.github.client_id, ""),
                        attempt=consumed,
                        remote=ProviderIdentity(str(account.id), account.login),
                        session_token=token,
                        audit=get_audit_context(request),
                        login_browser=login_browser,
                    )
                    outcome = "linked" if attempt.intent == "link" else "login_ready"
                attempt.result = GitHubDeviceResult(status=outcome, account=account)
                # Erase provider verification material after its one successful use.
                attempt.code = attempt.code.model_copy(update={"device_code": SecretStr("")})
                return attempt.result
            except ApiProblem:
                self.attempts.pop(attempt_id, None)
                raise

    def cancel(
        self, workspace: DesktopWorkspace, attempt_id: str, request: Request, session: Session
    ) -> None:
        with workspace.lock:
            attempt = self._attempt(attempt_id, request, session)
            if attempt.result is not None:
                raise github_problem(
                    "github_authorization_completed",
                    "授权已完成，请刷新状态；如需移除仓库授权，请清除本机仓库授权",
                    409,
                )
            self.attempts.pop(attempt_id, None)
