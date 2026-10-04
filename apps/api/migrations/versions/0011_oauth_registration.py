"""Permit passwordless OAuth users and short-lived pending registration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_oauth_registration"
down_revision: str | None = "0010_oauth_identities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "email", existing_type=sa.String(320), nullable=True)
    op.alter_column("users", "normalized_email", existing_type=sa.String(320), nullable=True)
    op.add_column("browser_login_claims", sa.Column("pending_provider", sa.String(16)))
    op.add_column("browser_login_claims", sa.Column("pending_client_id", sa.String(160)))
    op.add_column("browser_login_claims", sa.Column("pending_subject", sa.String(256)))
    op.add_column("browser_login_claims", sa.Column("pending_display_name", sa.String(120)))
    op.create_check_constraint(
        "pending_registration_complete",
        "browser_login_claims",
        "(pending_provider IS NULL AND pending_client_id IS NULL AND pending_subject IS NULL) "
        "OR (pending_provider IS NOT NULL AND pending_provider IN ('github', 'feishu') AND pending_client_id IS NOT NULL "
        "AND pending_subject IS NOT NULL AND pending_identity_id IS NULL)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM users WHERE email IS NULL OR normalized_email IS NULL)"
        )
    ):
        raise RuntimeError("cannot downgrade while OAuth users without email exist")
    op.drop_constraint("pending_registration_complete", "browser_login_claims", type_="check")
    for column in (
        "pending_display_name",
        "pending_subject",
        "pending_client_id",
        "pending_provider",
    ):
        op.drop_column("browser_login_claims", column)
    op.alter_column("users", "normalized_email", existing_type=sa.String(320), nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(320), nullable=False)
