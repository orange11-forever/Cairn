"""Version project structure and scope milestone stages to their project."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_project_structure"
down_revision: str | None = "0013_task_editing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("projects", "project_stages", "milestones"):
        op.add_column(
            table, sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )
        op.create_check_constraint("positive_revision", table, "revision > 0")
    op.add_column("milestones", sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("milestones", sa.Column("acceptance_criteria", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_milestones_project_stage",
        "milestones",
        "project_stages",
        ["org_id", "project_id", "stage_id"],
        ["org_id", "project_id", "id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("LOCK TABLE projects, project_stages, milestones IN ACCESS EXCLUSIVE MODE")
    )
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM projects WHERE revision > 1) OR EXISTS (SELECT 1 FROM project_stages WHERE revision > 1) OR EXISTS (SELECT 1 FROM milestones WHERE revision > 1 OR stage_id IS NOT NULL OR acceptance_criteria IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade edited project structure")
    op.drop_constraint("fk_milestones_project_stage", "milestones", type_="foreignkey")
    op.drop_column("milestones", "acceptance_criteria")
    op.drop_column("milestones", "stage_id")
    for table in ("milestones", "project_stages", "projects"):
        op.drop_constraint(op.f(f"ck_{table}_positive_revision"), table, type_="check")
        op.drop_column(table, "revision")
