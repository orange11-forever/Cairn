"""Provider identities and short-lived, single-use authorization attempts."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "client_id", "subject"),
        UniqueConstraint("user_id", "provider", "client_id"),
        CheckConstraint("provider IN ('github', 'feishu')", name="provider"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    client_id: Mapped[str] = mapped_column(String(160))
    subject: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BrowserLoginClaim(Base):
    __tablename__ = "browser_login_claims"
    __table_args__ = (Index("ix_browser_login_claims_expires_at", "expires_at"),)

    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    claimed_session_digest: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    pending_identity_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthAttempt(Base):
    __tablename__ = "oauth_attempts"
    __table_args__ = (
        CheckConstraint("provider IN ('github', 'feishu')", name="provider"),
        CheckConstraint("intent IN ('login', 'link')", name="intent"),
        CheckConstraint("(intent = 'link') = (session_id IS NOT NULL)", name="link_session"),
        CheckConstraint(
            "(intent = 'login') = (login_claim_digest IS NOT NULL)", name="login_claim"
        ),
        CheckConstraint("return_to IN ('/projects', '/account/identities')", name="return_to"),
        Index("ix_oauth_attempts_expires_at", "expires_at"),
    )

    state_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    browser_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    provider: Mapped[str] = mapped_column(String(16))
    client_id: Mapped[str] = mapped_column(String(160))
    intent: Mapped[str] = mapped_column(String(8))
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=True
    )
    login_claim_digest: Mapped[bytes | None] = mapped_column(
        ForeignKey("browser_login_claims.token_digest", ondelete="CASCADE"), nullable=True
    )
    verifier: Mapped[str] = mapped_column(String(128))
    return_to: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
