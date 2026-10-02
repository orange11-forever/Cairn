"""Add explicitly linked OAuth identities and single-use authorization state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_oauth_identities"
down_revision: str | None = "0009_feishu_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(512), nullable=True)
    op.create_table(
        "external_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("client_id", sa.String(160), nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "client_id", "subject"),
        sa.UniqueConstraint("user_id", "provider", "client_id"),
        sa.CheckConstraint("provider IN ('github', 'feishu')", name="provider"),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])
    op.create_table(
        "browser_login_claims",
        sa.Column("token_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("claimed_session_digest", sa.LargeBinary(32), nullable=True),
        sa.Column("pending_identity_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_digest"),
    )
    op.create_index("ix_browser_login_claims_expires_at", "browser_login_claims", ["expires_at"])
    op.create_table(
        "oauth_attempts",
        sa.Column("state_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("browser_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("client_id", sa.String(160), nullable=False),
        sa.Column("intent", sa.String(8), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("login_claim_digest", sa.LargeBinary(32), nullable=True),
        sa.Column("verifier", sa.String(128), nullable=False),
        sa.Column("return_to", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("state_digest"),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["login_claim_digest"], ["browser_login_claims.token_digest"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("provider IN ('github', 'feishu')", name="provider"),
        sa.CheckConstraint("intent IN ('login', 'link')", name="intent"),
        sa.CheckConstraint("(intent = 'link') = (session_id IS NOT NULL)", name="link_session"),
        sa.CheckConstraint(
            "(intent = 'login') = (login_claim_digest IS NOT NULL)", name="login_claim"
        ),
        sa.CheckConstraint("return_to IN ('/projects', '/account/identities')", name="return_to"),
    )
    op.create_index("ix_oauth_attempts_expires_at", "oauth_attempts", ["expires_at"])


def downgrade() -> None:
    # Follow the project's existing rule: never erase established identity facts.
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM external_identities) OR "
            "EXISTS (SELECT 1 FROM users WHERE password_hash IS NULL)"
        )
    ):
        raise RuntimeError("cannot downgrade while OAuth identities or passwordless users exist")
    op.drop_table("oauth_attempts")
    op.drop_table("browser_login_claims")
    op.drop_table("external_identities")
    op.alter_column("users", "password_hash", existing_type=sa.String(512), nullable=False)
