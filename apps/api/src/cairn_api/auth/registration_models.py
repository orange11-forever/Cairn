"""Short-lived email proofs; none of these rows grant account access."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class PendingRegistration(Base):
    __tablename__ = "pending_registrations"
    __table_args__ = (
        CheckConstraint(
            "token_digest IS NULL OR octet_length(token_digest) = 32", name="token_length"
        ),
        CheckConstraint("octet_length(receipt_digest) = 32", name="receipt_length"),
        CheckConstraint(
            "generation > 0 AND failed_password_count >= 0", name="positive_generation"
        ),
        Index("ix_pending_registrations_expires_at", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320))
    normalized_email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    token_digest: Mapped[bytes | None] = mapped_column(LargeBinary(32), unique=True, nullable=True)
    receipt_digest: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    generation: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_password_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    password_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RegistrationRateLimit(Base):
    __tablename__ = "registration_rate_limits"
    __table_args__ = (
        CheckConstraint("purpose IN ('send_email', 'send_ip', 'verify_ip')", name="purpose"),
        CheckConstraint(
            "octet_length(key_digest) = 32 AND attempt_count >= 0", name="valid_bucket"
        ),
        Index("ix_registration_rate_limits_expires_at", "expires_at"),
    )
    purpose: Mapped[str] = mapped_column(String(16), primary_key=True)
    key_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    attempt_count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
