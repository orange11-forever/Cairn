"""Email proof lifecycle. Mail never runs inside a database transaction."""

import hmac
import math
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.models import User
from cairn_api.auth.registration_mail import (
    RegistrationMailSender,
    RegistrationMailUnavailable,
    registration_available,
)
from cairn_api.auth.registration_models import PendingRegistration, RegistrationRateLimit
from cairn_api.auth.registration_schemas import (
    RegistrationAccepted,
    RegistrationRequest,
    RegistrationResendRequest,
    RegistrationVerified,
)
from cairn_api.auth.security import (
    DUMMY_PASSWORD_HASH,
    digest_token,
    hash_password,
    normalize_email,
    verify_password,
)
from cairn_api.auth.service import RequestAuditContext
from cairn_api.errors import ApiProblem
from cairn_api.organizations.models import Membership, Organization
from cairn_api.settings import Settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def invalid() -> ApiProblem:
    return ApiProblem(
        status_code=400,
        code="registration_invalid",
        message="验证链接或密码无效，请检查或重新注册。",
    )


def limited(seconds: float) -> ApiProblem:
    return ApiProblem(
        status_code=429,
        code="registration_rate_limited",
        message="操作过于频繁，请稍后再试。",
        headers={"Retry-After": str(max(1, math.ceil(seconds)))},
    )


class RegistrationService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        sender: RegistrationMailSender,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session = session
        self.settings = settings
        self.sender = sender
        self.now = now

    def _enabled(self) -> None:
        if not registration_available(self.settings):
            raise ApiProblem(
                status_code=503,
                code="registration_unavailable",
                message="暂时无法注册，请稍后再试。",
            )

    def _reserve(self, buckets: list[tuple[str, str, int, int]]) -> None:
        """Upsert before locking handles concurrent first use; all paths use key order."""
        now = self.now()
        problem = None
        with self.session.begin():
            records: list[tuple[RegistrationRateLimit, int, int]] = []
            for purpose, key, maximum, window in sorted(buckets):
                digest = hmac.digest(
                    self.settings.auth_rate_limit_secret.encode(),
                    ("registration:" + purpose + ":" + key).encode(),
                    "sha256",
                )
                self.session.execute(
                    insert(RegistrationRateLimit)
                    .values(
                        purpose=purpose,
                        key_digest=digest,
                        attempt_count=0,
                        expires_at=now + timedelta(seconds=window),
                    )
                    .on_conflict_do_nothing()
                )
                record = self.session.scalar(
                    select(RegistrationRateLimit)
                    .where(
                        RegistrationRateLimit.purpose == purpose,
                        RegistrationRateLimit.key_digest == digest,
                    )
                    .with_for_update()
                )
                assert record is not None
                if record.expires_at <= now:
                    record.attempt_count = 0
                    record.expires_at = now + timedelta(seconds=window)
                if record.attempt_count >= maximum:
                    problem = limited((record.expires_at - now).total_seconds())
                records.append((record, maximum, window))
            if problem is None:
                for record, _, _ in records:
                    record.attempt_count += 1
        if problem:
            raise problem

    def _send_limits(self, email: str, ip: str) -> None:
        self._reserve([("send_email", email, 5, 3600), ("send_ip", ip, 20, 3600)])

    def _deliver(
        self, pending_id: UUID, generation: int, recipient: str, token: str, expires_at: datetime
    ) -> None:
        url = str(self.settings.app_url).rstrip("/") + "/register/verify#token=" + token
        try:
            self.sender.send_verification(recipient, url, expires_at)
        except RegistrationMailUnavailable:
            # A late failure must not invalidate a newer resend. Never restore old tokens.
            with self.session.begin():
                self.session.execute(
                    update(PendingRegistration)
                    .where(
                        PendingRegistration.id == pending_id,
                        PendingRegistration.generation == generation,
                        PendingRegistration.consumed_at.is_(None),
                    )
                    .values(token_digest=None)
                )
            raise ApiProblem(
                status_code=503,
                code="registration_mail_unavailable",
                message="暂时无法发送验证邮件，请稍后重试。",
            ) from None

    def request(self, payload: RegistrationRequest, ip: str) -> RegistrationAccepted:
        self._enabled()
        email = normalize_email(str(payload.email))
        self._send_limits(email, ip)
        # Hash only after persistent abuse accounting, preserving the exact password.
        password_hash = hash_password(payload.password)
        receipt, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = self.now()
        pending = None
        with self.session.begin():
            if self.session.scalar(select(User.id).where(User.normalized_email == email)) is None:
                pending = PendingRegistration(
                    email=str(payload.email),
                    normalized_email=email,
                    display_name=payload.display_name,
                    password_hash=password_hash,
                    token_digest=digest_token(token),
                    receipt_digest=digest_token(receipt),
                    generation=1,
                    created_at=now,
                    expires_at=now + timedelta(minutes=30),
                    last_sent_at=now,
                )
                self.session.add(pending)
                self.session.flush()
        if pending is not None:
            self._deliver(pending.id, pending.generation, pending.email, token, pending.expires_at)
        return RegistrationAccepted(registration_receipt=receipt)

    def resend(self, payload: RegistrationResendRequest, ip: str) -> RegistrationAccepted:
        self._enabled()
        email = normalize_email(str(payload.email))
        self._send_limits(email, ip)
        now = self.now()
        token = secrets.token_urlsafe(32)
        delivery: tuple[UUID, int, str, str, datetime] | None = None
        receipt = secrets.token_urlsafe(32)
        problem = None
        with self.session.begin():
            pending = self.session.scalar(
                select(PendingRegistration)
                .where(
                    PendingRegistration.receipt_digest == digest_token(payload.registration_receipt)
                )
                .with_for_update()
            )
            usable = (
                pending is not None
                and pending.normalized_email == email
                and pending.expires_at > now
                and pending.consumed_at is None
            )
            correct_password = verify_password(
                payload.password,
                pending.password_hash if usable and pending else DUMMY_PASSWORD_HASH,
            )
            if (
                usable
                and correct_password
                and pending is not None
                and self.session.scalar(select(User.id).where(User.normalized_email == email))
                is None
            ):
                cooldown = 60 - (now - pending.last_sent_at).total_seconds()
                if cooldown > 0:
                    problem = limited(cooldown)
                else:
                    pending.generation += 1
                    pending.token_digest = digest_token(token)
                    pending.last_sent_at = now
                    receipt = payload.registration_receipt
                    delivery = (
                        pending.id,
                        pending.generation,
                        pending.email,
                        token,
                        pending.expires_at,
                    )
        if problem:
            raise problem
        if delivery:
            self._deliver(*delivery)
        return RegistrationAccepted(registration_receipt=receipt)

    def verify(
        self, token: str, password: str, ip: str, audit: RequestAuditContext
    ) -> RegistrationVerified:
        self._enabled()
        self._reserve([("verify_ip", ip, 20, 900)])
        now = self.now()
        problem: ApiProblem | None = None
        try:
            with self.session.begin():
                pending = self.session.scalar(
                    select(PendingRegistration)
                    .where(PendingRegistration.token_digest == digest_token(token))
                    .with_for_update()
                )
                if pending is None or pending.expires_at <= now or pending.consumed_at is not None:
                    verify_password(password, DUMMY_PASSWORD_HASH)
                    problem = invalid()
                else:
                    if (
                        pending.password_window_started_at is None
                        or pending.password_window_started_at + timedelta(minutes=15) <= now
                    ):
                        pending.failed_password_count = 0
                        pending.password_window_started_at = now
                    if pending.failed_password_count >= 5:
                        problem = limited(
                            (
                                pending.password_window_started_at + timedelta(minutes=15) - now
                            ).total_seconds()
                        )
                    elif not verify_password(password, pending.password_hash):
                        pending.failed_password_count += 1
                        problem = invalid()
                    else:
                        self.session.execute(
                            text("SELECT pg_advisory_xact_lock(hashtextextended(:email_key, 0))"),
                            {"email_key": "native-registration:" + pending.normalized_email},
                        )
                        if (
                            self.session.scalar(
                                select(User.id).where(
                                    User.normalized_email == pending.normalized_email
                                )
                            )
                            is not None
                        ):
                            pending.consumed_at = now
                            problem = invalid()
                        else:
                            self._provision(pending, audit, now)
        except IntegrityError as exc:
            # Only the authoritative user-email uniqueness race is a normal collision.
            if (
                getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                != "uq_users_normalized_email"
            ):
                raise
            with self.session.begin():
                self.session.execute(
                    update(PendingRegistration)
                    .where(PendingRegistration.token_digest == digest_token(token))
                    .values(consumed_at=now)
                )
            raise invalid() from None
        if problem:
            raise problem
        return RegistrationVerified()

    def _provision(
        self, pending: PendingRegistration, audit: RequestAuditContext, now: datetime
    ) -> None:
        user = User(
            email=pending.email,
            normalized_email=pending.normalized_email,
            display_name=pending.display_name,
            password_hash=pending.password_hash,
            email_verified_at=now,
        )
        organization = Organization(slug="personal-" + secrets.token_hex(12), name="个人空间")
        self.session.add_all((user, organization))
        self.session.flush()
        self.session.add(Membership(org_id=organization.id, user_id=user.id, role="owner"))
        self.session.flush()
        add_audit_log(
            self.session,
            org_id=organization.id,
            actor_type="user",
            actor_id=user.id,
            action="auth.registration_verified",
            resource_type="user",
            resource_id=user.id,
            trace_id=audit.trace_id,
            ip=audit.ip,
            user_agent=audit.user_agent,
        )
        pending.consumed_at = now
