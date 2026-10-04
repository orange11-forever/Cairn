"""Add short-lived, digest-only native email proof and separate abuse accounting."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_native_registration"
down_revision: str | None = "0011_oauth_registration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "pending_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(120)),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(32), unique=True),
        sa.Column("receipt_digest", sa.LargeBinary(32), unique=True, nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_password_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("password_window_started_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "token_digest IS NULL OR octet_length(token_digest) = 32", name="token_length"
        ),
        sa.CheckConstraint("octet_length(receipt_digest) = 32", name="receipt_length"),
        sa.CheckConstraint(
            "generation > 0 AND failed_password_count >= 0", name="positive_generation"
        ),
    )
    op.create_index("ix_pending_registrations_expires_at", "pending_registrations", ["expires_at"])
    op.create_table(
        "registration_rate_limits",
        sa.Column("purpose", sa.String(16), primary_key=True),
        sa.Column("key_digest", sa.LargeBinary(32), primary_key=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("purpose IN ('send_email', 'send_ip', 'verify_ip')", name="purpose"),
        sa.CheckConstraint(
            "octet_length(key_digest) = 32 AND attempt_count >= 0", name="valid_bucket"
        ),
    )
    op.create_index(
        "ix_registration_rate_limits_expires_at", "registration_rate_limits", ["expires_at"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pending_registrations WHERE consumed_at IS NULL AND expires_at > now())"
        )
    ):
        raise RuntimeError("cannot downgrade while live pending email proofs exist")
    op.drop_table("registration_rate_limits")
    op.drop_table("pending_registrations")
    op.drop_column("users", "email_verified_at")
