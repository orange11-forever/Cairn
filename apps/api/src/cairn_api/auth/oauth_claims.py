"""Serialize browser sign-ins across in-flight callbacks and password sign-in."""

import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, true
from sqlalchemy.orm import Session

from cairn_api.auth.models import AuthSession
from cairn_api.auth.oauth_models import BrowserLoginClaim
from cairn_api.auth.security import digest_token
from cairn_api.errors import ApiProblem


def browser_cookie_name(session_cookie_name: str) -> str:
    return session_cookie_name + "_oauth_browser"


def ensure_claim(
    session: Session, token: str | None, *, invalid_session_digest: bytes | None = None
) -> tuple[str, BrowserLoginClaim]:
    now = datetime.now(UTC)
    session.execute(delete(BrowserLoginClaim).where(BrowserLoginClaim.expires_at < now))
    claim = None
    if token and token.isascii() and len(token) <= 512:
        claim = session.scalar(
            select(BrowserLoginClaim)
            .where(BrowserLoginClaim.token_digest == digest_token(token))
            .with_for_update()
        )
    if claim is not None and claim.claimed_session_digest is not None:
        established = session.scalar(
            select(AuthSession)
            .where(AuthSession.token_digest == claim.claimed_session_digest)
            .with_for_update()
        )
        if established is not None and established.token_digest == invalid_session_digest:
            established.revoked_at = now
        if (
            established is not None
            and established.revoked_at is None
            and established.expires_at > now
        ):
            raise ApiProblem(
                status_code=409, code="session_changed", message="当前登录状态已改变，请刷新页面"
            )
        # The previous session is no longer usable. Its claim can never authenticate again.
        claim.expires_at = now
        claim = None
    if claim is None:
        token = secrets.token_urlsafe(32)
        claim = BrowserLoginClaim(
            token_digest=digest_token(token), expires_at=now + timedelta(seconds=300)
        )
        session.add(claim)
        session.flush()
    if claim.pending_identity_id is None:
        claim.expires_at = now + timedelta(seconds=300)
    assert token is not None
    return token, claim


def lock_claim(
    session: Session, token: str | None, *, include_expired: bool = False
) -> BrowserLoginClaim | None:
    if not token or not token.isascii() or len(token) > 512:
        return None
    return session.scalar(
        select(BrowserLoginClaim)
        .where(
            BrowserLoginClaim.token_digest == digest_token(token),
            (true() if include_expired else BrowserLoginClaim.expires_at > datetime.now(UTC)),
        )
        .with_for_update()
    )


def claim_login(
    session: Session,
    token: str | None,
    new_digest: bytes,
    current_session_token: str | None = None,
    *,
    required: bool = False,
) -> None:
    claim = lock_claim(session, token)
    if claim is None:
        if not required:
            return
    elif claim.claimed_session_digest is None:
        claim.claimed_session_digest = new_digest
        claim.pending_identity_id = None
        claim.expires_at = datetime.now(UTC) + timedelta(days=31)
        return
    elif (
        current_session_token
        and current_session_token.isascii()
        and hmac.compare_digest(digest_token(current_session_token), claim.claimed_session_digest)
    ):
        # An explicit password sign-in from the already established session may rotate it.
        claim.claimed_session_digest = new_digest
        claim.pending_identity_id = None
        claim.expires_at = datetime.now(UTC) + timedelta(days=31)
        return
    raise ApiProblem(
        status_code=409,
        code="session_changed",
        message="当前登录状态已改变，请刷新页面",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def require_login_claim(session: Session, token: str | None) -> BrowserLoginClaim:
    claim = lock_claim(session, token)
    if claim is not None and (
        claim.claimed_session_digest is not None or claim.pending_identity_id is not None
    ):
        raise ApiProblem(
            status_code=409, code="session_changed", message="当前登录状态已改变，请刷新页面"
        )
    if claim is None:
        raise ApiProblem(
            status_code=409, code="login_context_required", message="请刷新页面后重新登录"
        )
    claim.expires_at = datetime.now(UTC) + timedelta(seconds=300)
    return claim
