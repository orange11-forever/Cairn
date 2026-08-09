"""Add the tenant-scoped project and task graph."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_project_task_graph"
down_revision: str | None = "0002_auth_rate_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name="fk_projects_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.UniqueConstraint("org_id", "id", name="uq_projects_org_id_id"),
    )
    op.create_index(
        "ix_projects_org_id_created_at_id",
        "projects",
        ["org_id", "created_at", "id"],
    )

    op.create_table(
        "project_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_project_stages_org_id_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_stages"),
        sa.UniqueConstraint(
            "org_id",
            "project_id",
            "id",
            name="uq_project_stages_org_id_project_id_id",
        ),
    )
    op.create_index(
        "ix_project_stages_org_id_project_id_position_id",
        "project_stages",
        ["org_id", "project_id", "position", "id"],
    )

    op.create_table(
        "milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_milestones_org_id_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_milestones"),
        sa.UniqueConstraint(
            "org_id",
            "project_id",
            "id",
            name="uq_milestones_org_id_project_id_id",
        ),
    )
    op.create_index(
        "ix_milestones_org_id_project_id_due_at_id",
        "milestones",
        ["org_id", "project_id", "due_at", "id"],
    )

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("acceptance_criteria", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'backlog'"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.String(length=16),
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('backlog', 'todo', 'in_progress', 'blocked', 'done', 'cancelled')",
            name=op.f("ck_tasks_status_values"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_tasks_priority_values"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "milestone_id"],
            ["milestones.org_id", "milestones.project_id", "milestones.id"],
            name="fk_tasks_org_id_project_id_milestone_id_milestones",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "parent_task_id"],
            ["tasks.org_id", "tasks.project_id", "tasks.id"],
            name="fk_tasks_org_id_project_id_parent_task_id_tasks",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_tasks_org_id_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "stage_id"],
            ["project_stages.org_id", "project_stages.project_id", "project_stages.id"],
            name="fk_tasks_org_id_project_id_stage_id_project_stages",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
        sa.UniqueConstraint(
            "org_id",
            "project_id",
            "id",
            name="uq_tasks_org_id_project_id_id",
        ),
    )
    op.create_index(
        "ix_tasks_org_id_parent_task_id",
        "tasks",
        ["org_id", "parent_task_id"],
    )
    op.create_index(
        "ix_tasks_org_id_project_id_status_priority_id",
        "tasks",
        ["org_id", "project_id", "status", "priority", "id"],
    )
    op.create_index(
        "ix_tasks_org_id_project_id_created_at_id",
        "tasks",
        ["org_id", "project_id", "created_at", "id"],
    )

    op.create_table(
        "task_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("predecessor_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("successor_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "predecessor_task_id <> successor_task_id",
            name=op.f("ck_task_dependencies_different_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "predecessor_task_id"],
            ["tasks.org_id", "tasks.project_id", "tasks.id"],
            name="fk_task_dependencies_project_predecessor_tasks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "successor_task_id"],
            ["tasks.org_id", "tasks.project_id", "tasks.id"],
            name="fk_task_dependencies_project_successor_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_dependencies"),
        sa.UniqueConstraint(
            "org_id",
            "predecessor_task_id",
            "successor_task_id",
            name="uq_task_dependencies_edge",
        ),
    )
    op.create_index(
        "ix_task_dependencies_org_successor",
        "task_dependencies",
        ["org_id", "successor_task_id", "predecessor_task_id"],
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name="fk_outbox_events_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    op.create_index(
        "ix_outbox_events_org_aggregate_reads",
        "outbox_events",
        ["org_id", "aggregate_type", "aggregate_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_events_org_aggregate_reads",
        table_name="outbox_events",
    )
    op.drop_table("outbox_events")
    op.drop_index(
        "ix_task_dependencies_org_successor",
        table_name="task_dependencies",
    )
    op.drop_table("task_dependencies")
    op.drop_index("ix_tasks_org_id_project_id_created_at_id", table_name="tasks")
    op.drop_index("ix_tasks_org_id_project_id_status_priority_id", table_name="tasks")
    op.drop_index("ix_tasks_org_id_parent_task_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_milestones_org_id_project_id_due_at_id", table_name="milestones")
    op.drop_table("milestones")
    op.drop_index(
        "ix_project_stages_org_id_project_id_position_id",
        table_name="project_stages",
    )
    op.drop_table("project_stages")
    op.drop_index("ix_projects_org_id_created_at_id", table_name="projects")
    op.drop_table("projects")
