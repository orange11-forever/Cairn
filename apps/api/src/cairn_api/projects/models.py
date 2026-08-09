from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        Index("ix_projects_org_id_created_at_id", "org_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProjectStage(Base):
    __tablename__ = "project_stages"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_project_stages_org_id_project_id_position_id",
            "org_id",
            "project_id",
            "position",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_milestones_org_id_project_id_due_at_id",
            "org_id",
            "project_id",
            "due_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        CheckConstraint(
            "status IN ('backlog', 'todo', 'in_progress', 'blocked', 'done', 'cancelled')",
            name="status_values",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="priority_values",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "stage_id"],
            ["project_stages.org_id", "project_stages.project_id", "project_stages.id"],
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "milestone_id"],
            ["milestones.org_id", "milestones.project_id", "milestones.id"],
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "parent_task_id"],
            ["tasks.org_id", "tasks.project_id", "tasks.id"],
        ),
        Index(
            "ix_tasks_org_id_project_id_status_priority_id",
            "org_id",
            "project_id",
            "status",
            "priority",
            "id",
        ),
        Index(
            "ix_tasks_org_id_project_id_created_at_id",
            "org_id",
            "project_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_tasks_org_id_parent_task_id",
            "org_id",
            "parent_task_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    stage_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    milestone_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    parent_task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="backlog", server_default="backlog")
    priority: Mapped[str] = mapped_column(
        String(16),
        default="medium",
        server_default="medium",
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        CheckConstraint(
            "predecessor_task_id <> successor_task_id",
            name="different_tasks",
        ),
        UniqueConstraint(
            "org_id",
            "predecessor_task_id",
            "successor_task_id",
            name="uq_task_dependencies_edge",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "predecessor_task_id"],
            ["tasks.org_id", "tasks.project_id", "tasks.id"],
            name="fk_task_dependencies_project_predecessor_tasks",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "successor_task_id"],
            ["tasks.org_id", "tasks.project_id", "tasks.id"],
            name="fk_task_dependencies_project_successor_tasks",
            ondelete="CASCADE",
        ),
        Index(
            "ix_task_dependencies_org_successor",
            "org_id",
            "successor_task_id",
            "predecessor_task_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    predecessor_task_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    successor_task_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_org_aggregate_reads",
            "org_id",
            "aggregate_type",
            "aggregate_id",
            "occurred_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
    )
    event_type: Mapped[str] = mapped_column(String(128))
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


__all__ = [
    "Milestone",
    "OutboxEvent",
    "Project",
    "ProjectStage",
    "Task",
    "TaskDependency",
]
