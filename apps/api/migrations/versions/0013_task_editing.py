"""Add task assignment and optimistic revisions without discarding edited data."""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_task_editing"
down_revision: str | None = "0012_native_registration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column(
        "tasks", sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_check_constraint("positive_revision", "tasks", "revision > 0")
    op.create_foreign_key(
        "fk_tasks_org_id_assignee_user_id_memberships",
        "tasks",
        "memberships",
        ["org_id", "assignee_user_id"],
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    # Lock the table so a concurrent task write cannot pass the loss check.
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE tasks IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM tasks WHERE revision > 1 OR assignee_user_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade edited or assigned tasks")
    op.drop_constraint("fk_tasks_org_id_assignee_user_id_memberships", "tasks", type_="foreignkey")
    op.drop_constraint(op.f("ck_tasks_positive_revision"), "tasks", type_="check")
    op.drop_column("tasks", "assignee_user_id")
    op.drop_column("tasks", "revision")
