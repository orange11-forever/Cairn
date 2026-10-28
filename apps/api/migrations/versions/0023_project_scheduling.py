"""Keep task effort and a project-wide capacity calendar."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0023_project_scheduling"
down_revision: str | None = "0022_project_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("estimated_effort_minutes", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("remaining_effort_minutes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "nonnegative_estimated_effort", "tasks", "estimated_effort_minutes >= 0"
    )
    op.create_check_constraint(
        "nonnegative_remaining_effort", "tasks", "remaining_effort_minutes >= 0"
    )
    op.add_column("projects", sa.Column("daily_capacity_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "working_weekdays",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[1,2,3,4,5]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "nonnegative_daily_capacity", "projects", "daily_capacity_minutes >= 0"
    )
    op.create_check_constraint(
        "working_weekdays_values",
        "projects",
        "jsonb_typeof(working_weekdays) = 'array' AND jsonb_array_length(working_weekdays) BETWEEN 1 AND 7 AND working_weekdays <@ '[1,2,3,4,5,6,7]'::jsonb",
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE projects, tasks IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM tasks WHERE estimated_effort_minutes IS NOT NULL OR remaining_effort_minutes IS NOT NULL) OR EXISTS(SELECT 1 FROM projects WHERE daily_capacity_minutes IS NOT NULL OR working_weekdays <> '[1,2,3,4,5]'::jsonb)"
        )
    ):
        raise RuntimeError("Cannot downgrade recorded scheduling inputs")
    op.drop_constraint(op.f("ck_projects_working_weekdays_values"), "projects", type_="check")
    op.drop_constraint(op.f("ck_projects_nonnegative_daily_capacity"), "projects", type_="check")
    op.drop_column("projects", "working_weekdays")
    op.drop_column("projects", "daily_capacity_minutes")
    op.drop_constraint(op.f("ck_tasks_nonnegative_remaining_effort"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_tasks_nonnegative_estimated_effort"), "tasks", type_="check")
    op.drop_column("tasks", "remaining_effort_minutes")
    op.drop_column("tasks", "estimated_effort_minutes")
