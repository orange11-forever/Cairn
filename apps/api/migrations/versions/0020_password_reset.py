"""Add one active password-reset proof per user and separate abuse buckets."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_password_reset"
down_revision: str | None = "0019_multiple_assistants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_registration_rate_limits_purpose"), "registration_rate_limits", type_="check"
    )
    op.create_check_constraint(
        "purpose",
        "registration_rate_limits",
        "purpose IN ('send_email', 'send_ip', 'verify_ip', 'reset_email', 'reset_ip', 'reset_confirm_ip')",
    )
    op.create_table(
        "password_resets",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("token_digest", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("octet_length(token_digest) = 32", name="token_length"),
    )
    op.create_index("ix_password_resets_expires_at", "password_resets", ["expires_at"])


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM password_resets WHERE expires_at > now())")
    ):
        raise RuntimeError("cannot downgrade while live password reset proofs exist")
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM registration_rate_limits WHERE purpose LIKE 'reset_%' AND expires_at > now())"
        )
    ):
        raise RuntimeError("cannot downgrade while live password reset rate limits exist")
    op.drop_table("password_resets")
    op.execute("DELETE FROM registration_rate_limits WHERE purpose LIKE 'reset_%'")
    op.drop_constraint(
        op.f("ck_registration_rate_limits_purpose"), "registration_rate_limits", type_="check"
    )
    op.create_check_constraint(
        "purpose", "registration_rate_limits", "purpose IN ('send_email', 'send_ip', 'verify_ip')"
    )
