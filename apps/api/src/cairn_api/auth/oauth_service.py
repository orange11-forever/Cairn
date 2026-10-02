"""Explicit account linking; no email-based lookup or membership provisioning."""

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.models import AuthSession, User
from cairn_api.auth.oauth_claims import claim_login, lock_claim, require_login_claim
from cairn_api.auth.oauth_models import ExternalIdentity, OAuthAttempt
from cairn_api.auth.oauth_providers import OAuthProvider, ProviderIdentity
from cairn_api.auth.oauth_schemas import (
    LinkedIdentitiesResponse,
    LinkedIdentityResponse,
    OAuthStartRequest,
    ProviderName,
)
from cairn_api.auth.rate_limit import digest_key, retry_after_seconds
from cairn_api.auth.rate_limit_repository import BucketKey, RateLimitRepository
from cairn_api.auth.repository import SessionRecord, get_memberships_for_user, get_session_record
from cairn_api.auth.security import derive_csrf_token, digest_token, issue_session_material
from cairn_api.auth.service import AuthService, LoginResult, RequestAuditContext, identity_context
from cairn_api.errors import ApiProblem
from cairn_api.settings import Settings

ATTEMPT_TTL = 300
RECENT_AUTH = timedelta(minutes=10)


def problem(code: str, message: str, status: int = 409) -> ApiProblem:
    return ApiProblem(
        status_code=status,
        code=code,
        message=message,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def token_digest(value: str | None) -> bytes:
    if not value or not value.isascii() or len(value) > 512:
        raise problem("oauth_state_invalid", "授权请求无效或已过期，请重新发起", 400)
    return digest_token(value)


@dataclass(frozen=True)
class StartedAttempt:
    state: str
    browser: str
    verifier: str
    login_browser: str | None = None


@dataclass(frozen=True)
class ConsumedAttempt:
    intent: str
    session_id: UUID | None
    verifier: str
    return_to: str
    client_id: str
    login_claim_digest: bytes | None = None


class OAuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _current(self, token: str | None, *, recent: bool = False) -> SessionRecord:
        if not token or not token.isascii() or len(token) > 512:
            raise problem("oauth_session_invalid", "请重新登录后管理登录方式", 401)
        record = get_session_record(self.session, digest_token(token))
        if record is None:
            raise problem("oauth_session_invalid", "请重新登录后管理登录方式", 401)
        # All link/unlink/login operations serialize on the owning user before session.
        self.session.scalar(
            select(User)
            .where(User.id == record.user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        self.session.scalar(
            select(AuthSession)
            .where(AuthSession.id == record.auth_session.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not AuthService.record_is_valid(
            record, csrf_token=derive_csrf_token(token, self.settings.csrf_secret.encode())
        ):
            raise problem("oauth_session_invalid", "请重新登录后管理登录方式", 401)
        if recent and record.auth_session.created_at < datetime.now(UTC) - RECENT_AUTH:
            raise problem("reauthentication_required", "请重新登录后管理登录方式", 403)
        return record

    def _audit(
        self,
        record: SessionRecord,
        action: str,
        provider: str,
        audit: RequestAuditContext,
        resource_id: UUID | None = None,
    ) -> None:
        add_audit_log(
            self.session,
            org_id=record.organization.id,
            actor_type="user",
            actor_id=record.user.id,
            action=action,
            resource_type="external_identity",
            resource_id=resource_id,
            trace_id=audit.trace_id,
            ip=audit.ip,
            user_agent=audit.user_agent,
            details={"provider": provider},
        )

    def start(
        self,
        *,
        provider: ProviderName,
        adapter: OAuthProvider,
        payload: OAuthStartRequest,
        session_token: str | None,
        audit: RequestAuditContext,
        login_browser: str | None = None,
    ) -> StartedAttempt:
        now = datetime.now(UTC)
        started = StartedAttempt(
            secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        )
        with self.session.begin():
            bucket = RateLimitRepository.record_failure(
                self.session,
                BucketKey(
                    "ip",
                    digest_key(
                        "ip",
                        "oauth-start:" + (audit.ip or "unknown"),
                        self.settings.auth_rate_limit_secret,
                    ),
                ),
                now=now,
            )
        if bucket.blocked_until is not None and bucket.blocked_until > now:
            raise ApiProblem(
                status_code=429,
                code="oauth_rate_limited",
                message="授权尝试过于频繁，请稍后再试",
                headers={"Retry-After": str(retry_after_seconds([bucket.blocked_until], now))},
            )
        with self.session.begin():
            record = self._current(session_token, recent=True) if payload.intent == "link" else None
            if payload.intent == "login" and session_token:
                raise problem("session_changed", "请退出当前账号后再使用第三方登录")
            claim = None
            if payload.intent == "login":
                claim = require_login_claim(self.session, login_browser)
            self.session.execute(delete(OAuthAttempt).where(OAuthAttempt.expires_at < now))
            self.session.add(
                OAuthAttempt(
                    state_digest=digest_token(started.state),
                    browser_digest=digest_token(started.browser),
                    provider=provider,
                    client_id=adapter.client_id,
                    intent=payload.intent,
                    session_id=record.auth_session.id if record else None,
                    login_claim_digest=claim.token_digest if claim else None,
                    verifier=started.verifier,
                    return_to=payload.return_to,
                    expires_at=now + timedelta(seconds=ATTEMPT_TTL),
                )
            )
        return StartedAttempt(started.state, started.browser, started.verifier, login_browser)

    def consume(
        self,
        *,
        provider: ProviderName,
        client_id: str,
        state: str | None,
        browser: str | None,
        login_browser: str | None = None,
    ) -> ConsumedAttempt:
        state_digest, browser_digest = token_digest(state), token_digest(browser)
        with self.session.begin():
            attempt = self.session.scalar(
                select(OAuthAttempt)
                .where(OAuthAttempt.state_digest == state_digest)
                .with_for_update()
            )
            if (
                attempt is None
                or attempt.provider != provider
                or attempt.client_id != client_id
                or attempt.consumed_at is not None
                or attempt.expires_at <= datetime.now(UTC)
                or not hmac.compare_digest(attempt.browser_digest, browser_digest)
            ):
                raise problem("oauth_state_invalid", "授权请求无效或已过期，请重新发起", 400)
            if attempt.intent == "login" and not hmac.compare_digest(
                attempt.login_claim_digest or b"", token_digest(login_browser)
            ):
                raise problem("oauth_state_invalid", "授权请求无效或已过期，请重新发起", 400)
            result = ConsumedAttempt(
                attempt.intent,
                attempt.session_id,
                attempt.verifier,
                attempt.return_to,
                attempt.client_id,
                attempt.login_claim_digest,
            )
            attempt.consumed_at = datetime.now(UTC)
            attempt.verifier = ""  # erase temporary PKCE material on consumption
        return result

    def validate_callback_session(
        self, attempt: ConsumedAttempt, session_token: str | None
    ) -> None:
        if attempt.intent == "login":
            if session_token:
                raise problem("session_changed", "当前会话已改变，请重新发起")
            return
        with self.session.begin():
            try:
                record = self._current(session_token, recent=True)
            except ApiProblem:
                raise problem("session_changed", "当前会话已改变，请重新发起") from None
            if record.auth_session.id != attempt.session_id:
                raise problem("session_changed", "当前会话已改变，请重新发起")

    def finish(
        self,
        *,
        provider: ProviderName,
        adapter: OAuthProvider,
        attempt: ConsumedAttempt,
        remote: ProviderIdentity,
        session_token: str | None,
        audit: RequestAuditContext,
        login_browser: str | None = None,
    ) -> str | None:
        if not remote.subject or len(remote.subject) > 256:
            raise problem("provider_failed", "第三方身份验证失败，请重新发起", 502)
        try:
            with self.session.begin():
                if attempt.intent == "link":
                    record = self._current(session_token, recent=True)
                    if record.auth_session.id != attempt.session_id:
                        raise problem("session_changed", "当前会话已改变，请重新发起")
                    existing = self.session.scalar(
                        select(ExternalIdentity).where(
                            ExternalIdentity.provider == provider,
                            ExternalIdentity.client_id == adapter.client_id,
                            ExternalIdentity.subject == remote.subject,
                        )
                    )
                    if existing is not None:
                        if existing.user_id != record.user.id:
                            raise problem("identity_conflict", "此第三方身份已绑定其他账号")
                        return None
                    if (
                        self.session.scalar(
                            select(ExternalIdentity.id).where(
                                ExternalIdentity.user_id == record.user.id,
                                ExternalIdentity.provider == provider,
                                ExternalIdentity.client_id == adapter.client_id,
                            )
                        )
                        is not None
                    ):
                        raise problem("provider_already_linked", "请先解绑当前第三方身份")
                    linked = ExternalIdentity(
                        user_id=record.user.id,
                        provider=provider,
                        client_id=adapter.client_id,
                        subject=remote.subject,
                        display_name=remote.display_name,
                    )
                    self.session.add(linked)
                    self.session.flush()
                    self._audit(record, "auth.identity_linked", provider, audit, linked.id)
                    return None
                if session_token:
                    raise problem("session_changed", "当前会话已改变，请重新发起")
                claim = require_login_claim(self.session, login_browser)
                linked = self.session.scalar(
                    select(ExternalIdentity).where(
                        ExternalIdentity.provider == provider,
                        ExternalIdentity.client_id == adapter.client_id,
                        ExternalIdentity.subject == remote.subject,
                    )
                )
                if linked is None:
                    raise problem("identity_not_linked", "请先用已有账号登录并绑定此第三方身份")
                user = self.session.scalar(
                    select(User).where(User.id == linked.user_id).with_for_update()
                )
                # Unlink may have finished while this transaction waited for the user lock.
                if (
                    user is None
                    or not user.is_active
                    or self.session.scalar(
                        select(ExternalIdentity.id).where(ExternalIdentity.id == linked.id)
                    )
                    is None
                ):
                    raise problem("identity_not_linked", "第三方身份尚未绑定可用账号")
                memberships = get_memberships_for_user(self.session, user)
                if len(memberships) != 1:
                    raise problem("organization_selection_required", "请使用邮箱密码登录并选择组织")
                claim.pending_identity_id = linked.id
                claim.expires_at = datetime.now(UTC) + timedelta(seconds=ATTEMPT_TTL)
                return None
        except IntegrityError:
            raise problem("identity_conflict", "此第三方身份已绑定或账号已有该登录方式") from None

    def finalize(
        self,
        *,
        login_browser: str | None,
        session_token: str | None,
        enabled_clients: dict[ProviderName, str],
        audit: RequestAuditContext,
    ) -> LoginResult:
        if session_token:
            raise problem("session_changed", "当前登录状态已改变，请刷新页面")
        with self.session.begin():
            claim = lock_claim(self.session, login_browser)
            if (
                claim is None
                or claim.claimed_session_digest is not None
                or claim.pending_identity_id is None
            ):
                raise problem("session_changed", "授权已使用或失效，请重新登录")
            linked = self.session.get(ExternalIdentity, claim.pending_identity_id)
            if (
                linked is None
                or enabled_clients.get(cast(ProviderName, linked.provider)) != linked.client_id
            ):
                raise problem("identity_not_linked", "此登录方式当前不可用，请重新登录")
            user = self.session.scalar(
                select(User).where(User.id == linked.user_id).with_for_update()
            )
            if (
                user is None
                or not user.is_active
                or self.session.scalar(
                    select(ExternalIdentity.id).where(ExternalIdentity.id == linked.id)
                )
                is None
            ):
                raise problem("identity_not_linked", "第三方身份尚未绑定可用账号")
            memberships = get_memberships_for_user(self.session, user)
            if len(memberships) != 1:
                raise problem("organization_selection_required", "请使用已有登录方式选择组织")
            membership = memberships[0]
            material = issue_session_material(self.settings.csrf_secret.encode())
            claim_login(self.session, login_browser, material.session_digest, required=True)
            auth_session = AuthSession(
                user_id=user.id,
                org_id=membership.organization.id,
                token_digest=material.session_digest,
                csrf_digest=material.csrf_digest,
                expires_at=datetime.now(UTC) + timedelta(seconds=self.settings.session_ttl_seconds),
            )
            self.session.add(auth_session)
            self.session.flush()
            record = SessionRecord(
                auth_session, user, membership.membership, membership.organization
            )
            self._audit(record, "auth.oauth_login_succeeded", linked.provider, audit, linked.id)
            return LoginResult(
                identity_context(record, user=user, csrf_token=material.csrf_token), material.session_token
            )

    def identities(self, session_token: str | None) -> LinkedIdentitiesResponse:
        with self.session.begin():
            try:
                record = self._current(session_token)
            except ApiProblem:
                raise problem("session_invalid", "会话无效或已过期", 401) from None
            identities = self.session.scalars(
                select(ExternalIdentity)
                .where(ExternalIdentity.user_id == record.user.id)
                .order_by(ExternalIdentity.created_at)
            ).all()
            return LinkedIdentitiesResponse(
                password_available=bool(record.user.password_hash),
                identities=[
                    LinkedIdentityResponse(
                        id=item.id,
                        provider=cast(ProviderName, item.provider),
                        display_name=item.display_name,
                        created_at=item.created_at,
                    )
                    for item in identities
                ],
            )

    def unlink(
        self,
        *,
        identity_id: UUID,
        session_token: str | None,
        enabled_clients: dict[ProviderName, str],
        audit: RequestAuditContext,
    ) -> None:
        with self.session.begin():
            record = self._current(session_token, recent=True)
            identities = self.session.scalars(
                select(ExternalIdentity).where(ExternalIdentity.user_id == record.user.id)
            ).all()
            target = next((item for item in identities if item.id == identity_id), None)
            if target is None:
                raise problem("identity_not_linked", "此登录方式尚未绑定", 404)
            alternatives = [
                item
                for item in identities
                if item.id != target.id
                and enabled_clients.get(cast(ProviderName, item.provider)) == item.client_id
            ]
            if not record.user.password_hash and not alternatives:
                raise problem("last_login_method", "请保留至少一种可用的登录方式")
            self._audit(record, "auth.identity_unlinked", target.provider, audit, target.id)
            self.session.delete(target)
