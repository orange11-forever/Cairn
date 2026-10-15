"""Preserve stage and milestone history with explicit archive state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_structure_lifecycle"
down_revision: str | None = "0014_project_structure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("project_stages", "milestones"):
        op.add_column(
            table, sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE project_stages, milestones IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM project_stages WHERE archived) OR EXISTS (SELECT 1 FROM milestones WHERE archived)"
        )
    ):
        raise RuntimeError("Cannot downgrade archived project structure")
    for table in ("milestones", "project_stages"):
        op.drop_column(table, "archived")
