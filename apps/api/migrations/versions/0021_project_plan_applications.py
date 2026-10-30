"""Persist confirmed project plans and their created entity mappings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0021_project_plan_applications"
down_revision: str | None = "0020_password_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_plan_applications",
        sa.Column("org_id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), primary_key=True),
        sa.Column(
            "owner_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("request_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("plan", JSONB(), nullable=False),
        sa.Column("sources", JSONB(), nullable=False),
        sa.Column("entity_ids", JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_project_plan_applications_scope_created",
        "project_plan_applications",
        ["org_id", "project_id", "owner_id", "created_at", "id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE project_plan_applications IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM project_plan_applications)")):
        raise RuntimeError("Cannot downgrade populated project plan applications")
    op.drop_table("project_plan_applications")
