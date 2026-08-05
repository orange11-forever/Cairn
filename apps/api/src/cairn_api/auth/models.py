from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    email: Mapped[str] = mapped_column(String(320))
    normalized_email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        Index("ix_auth_sessions_org_id_user_id", "org_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    csrf_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        CheckConstraint("bucket_type IN ('email', 'ip')", name="bucket_type"),
        CheckConstraint("octet_length(key_digest) = 32", name="key_digest_length"),
        CheckConstraint("count > 0", name="positive_count"),
        CheckConstraint(
            "blocked_until IS NULL OR blocked_until >= window_started_at",
            name="block_after_window",
        ),
        Index(
            "ix_auth_rate_limits_window_started_at_unblocked",
            "window_started_at",
            postgresql_where=text("blocked_until IS NULL"),
        ),
        Index(
            "ix_auth_rate_limits_blocked_until",
            "blocked_until",
            postgresql_where=text("blocked_until IS NOT NULL"),
        ),
    )

    bucket_type: Mapped[str] = mapped_column(String(5), primary_key=True)
    key_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
