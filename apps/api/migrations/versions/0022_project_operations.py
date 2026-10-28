"""Persist confirmed assistant project operations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0022_project_operations"
down_revision: str | None = "0021_project_plan_applications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_operations",
        sa.Column("org_id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), primary_key=True),
        sa.Column(
            "owner_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("request_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("details", JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_project_operations_scope_created",
        "project_operations",
        ["org_id", "project_id", "owner_id", "created_at", "id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE project_operations IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM project_operations)")):
        raise RuntimeError("Cannot downgrade populated project operations")
    op.drop_table("project_operations")
