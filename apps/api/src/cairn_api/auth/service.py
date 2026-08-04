import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.models import AuthSession, User
from cairn_api.auth.repository import (
    MembershipRecord,
    SessionRecord,
    get_memberships_for_user,
    get_session_record,
    get_user_by_normalized_email,
)
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.security import (
    DUMMY_PASSWORD_HASH,
    derive_csrf_token,
    digest_token,
    issue_session_material,
    normalize_email,
    verify_csrf_token,
    verify_password,
)
from cairn_api.errors import ApiProblem
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.settings import Settings


class _InvalidCredentials(Exception):
    pass


@dataclass(frozen=True)
class RequestAuditContext:
    trace_id: str
    ip: str | None
    user_agent: str | None


@dataclass(frozen=True)
class LoginResult:
    identity: IdentityContextResponse
    session_token: str


def _database_unavailable() -> ApiProblem:
    return ApiProblem(
        status_code=503,
        code="database_unavailable",
        message="数据库暂时不可用",
    )


def _invalid_credentials() -> ApiProblem:
    return ApiProblem(
        status_code=401,
        code="invalid_credentials",
        message="邮箱或密码错误",
    )


def _invalid_session() -> ApiProblem:
    return ApiProblem(
        status_code=401,
        code="session_invalid",
        message="会话无效或已过期",
    )


def _identity(
    record: MembershipRecord | SessionRecord,
    *,
    user: User,
    csrf_token: str,
) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(id=user.id, email=user.email, display_name=user.display_name),
        organization=OrganizationResponse(
            id=record.organization.id,
            slug=record.organization.slug,
            name=record.organization.name,
        ),
        membership=MembershipResponse(
            id=record.membership.id,
            role=record.membership.role,
        ),
        csrf_token=csrf_token,
    )


class AuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._csrf_secret = settings.csrf_secret.encode("utf-8")

    def login(
        self,
        *,
        email: str,
        password: str,
        audit: RequestAuditContext,
    ) -> LoginResult:
        try:
            with self._session.begin():
                user = get_user_by_normalized_email(self._session, normalize_email(email))
                password_digest = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
                password_valid = verify_password(password, password_digest)
                if user is None or not password_valid or not user.is_active:
                    raise _InvalidCredentials
                memberships = get_memberships_for_user(self._session, user)
                if not memberships:
                    raise _InvalidCredentials
                if len(memberships) > 1:
                    raise ApiProblem(
                        status_code=409,
                        code="organization_selection_required",
                        message="需要选择组织",
                    )
                membership = memberships[0]
                material = issue_session_material(self._csrf_secret)
                auth_session = AuthSession(
                    org_id=membership.organization.id,
                    user_id=user.id,
                    token_digest=material.session_digest,
                    csrf_digest=material.csrf_digest,
                    expires_at=datetime.now(UTC)
                    + timedelta(seconds=self._settings.session_ttl_seconds),
                )
                self._session.add(auth_session)
                self._session.flush()
                add_audit_log(
                    self._session,
                    org_id=membership.organization.id,
                    actor_type="user",
                    actor_id=user.id,
                    action="auth.login_succeeded",
                    resource_type="session",
                    resource_id=auth_session.id,
                    trace_id=audit.trace_id,
                    ip=audit.ip,
                    user_agent=audit.user_agent,
                )
                identity = _identity(
                    membership,
                    user=user,
                    csrf_token=material.csrf_token,
                )
            return LoginResult(identity=identity, session_token=material.session_token)
        except _InvalidCredentials:
            try:
                with self._session.begin():
                    add_audit_log(
                        self._session,
                        org_id=None,
                        actor_type="anonymous",
                        actor_id=None,
                        action="auth.login_failed",
                        resource_type="session",
                        resource_id=None,
                        trace_id=audit.trace_id,
                        ip=audit.ip,
                        user_agent=audit.user_agent,
                    )
            except SQLAlchemyError as exc:
                raise _database_unavailable() from exc
            raise _invalid_credentials() from None
        except SQLAlchemyError as exc:
            raise _database_unavailable() from exc

    def restore(
        self,
        *,
        session_token: str | None,
        audit: RequestAuditContext,
    ) -> IdentityContextResponse:
        if not session_token:
            raise _invalid_session()
        try:
            session_digest = digest_token(session_token)
            csrf_token = derive_csrf_token(session_token, self._csrf_secret)
        except UnicodeEncodeError:
            raise _invalid_session() from None
        try:
            with self._session.begin():
                record = get_session_record(self._session, session_digest)
                if not self._record_is_valid(record, csrf_token=csrf_token):
                    raise _invalid_session()
                assert record is not None
                now = datetime.now(UTC)
                record.auth_session.last_seen_at = now
                add_audit_log(
                    self._session,
                    org_id=record.organization.id,
                    actor_type="user",
                    actor_id=record.user.id,
                    action="auth.session_restored",
                    resource_type="session",
                    resource_id=record.auth_session.id,
                    trace_id=audit.trace_id,
                    ip=audit.ip,
                    user_agent=audit.user_agent,
                )
                identity = _identity(record, user=record.user, csrf_token=csrf_token)
            return identity
        except SQLAlchemyError as exc:
            raise _database_unavailable() from exc

    def logout(
        self,
        *,
        session_token: str | None,
        csrf_token: str | None,
        audit: RequestAuditContext,
    ) -> None:
        if not session_token:
            return
        try:
            session_digest = digest_token(session_token)
            derived_csrf = derive_csrf_token(session_token, self._csrf_secret)
        except UnicodeEncodeError:
            return
        try:
            with self._session.begin():
                record = get_session_record(self._session, session_digest)
                if not self._record_is_valid(record, csrf_token=derived_csrf):
                    return
                assert record is not None
                if csrf_token is None or not verify_csrf_token(
                    session_token,
                    csrf_token,
                    self._csrf_secret,
                ):
                    raise ApiProblem(
                        status_code=403,
                        code="csrf_failed",
                        message="请求来源或 CSRF 令牌无效",
                    )
                record.auth_session.revoked_at = datetime.now(UTC)
                add_audit_log(
                    self._session,
                    org_id=record.organization.id,
                    actor_type="user",
                    actor_id=record.user.id,
                    action="auth.logout",
                    resource_type="session",
                    resource_id=record.auth_session.id,
                    trace_id=audit.trace_id,
                    ip=audit.ip,
                    user_agent=audit.user_agent,
                )
        except SQLAlchemyError as exc:
            raise _database_unavailable() from exc

    @staticmethod
    def _record_is_valid(record: SessionRecord | None, *, csrf_token: str) -> bool:
        if record is None:
            return False
        auth_session = record.auth_session
        return (
            record.user.is_active
            and auth_session.revoked_at is None
            and auth_session.expires_at > datetime.now(UTC)
            and hmac.compare_digest(auth_session.csrf_digest, digest_token(csrf_token))
        )
