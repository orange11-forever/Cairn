"""Add durable authentication rate-limit buckets."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_auth_rate_limits"
down_revision: str | None = "0001_identity_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limits",
        sa.Column("bucket_type", sa.String(length=5), nullable=False),
        sa.Column("key_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "bucket_type IN ('email', 'ip')",
            name="bucket_type",
        ),
        sa.CheckConstraint(
            "octet_length(key_digest) = 32",
            name="key_digest_length",
        ),
        sa.CheckConstraint(
            "failure_count > 0",
            name="positive_count",
        ),
        sa.CheckConstraint(
            "blocked_until IS NULL OR blocked_until >= window_started_at",
            name="block_after_window",
        ),
        sa.PrimaryKeyConstraint("bucket_type", "key_digest", name="pk_auth_rate_limits"),
    )
    op.create_index(
        "ix_auth_rate_limits_window_started_at_unblocked",
        "auth_rate_limits",
        ["window_started_at"],
        postgresql_using="btree",
        postgresql_where=sa.text("blocked_until IS NULL"),
    )
    op.create_index(
        "ix_auth_rate_limits_blocked_until",
        "auth_rate_limits",
        ["blocked_until"],
        postgresql_using="btree",
        postgresql_where=sa.text("blocked_until IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limits_blocked_until", table_name="auth_rate_limits")
    op.drop_index(
        "ix_auth_rate_limits_window_started_at_unblocked",
        table_name="auth_rate_limits",
    )
    op.drop_table("auth_rate_limits")
