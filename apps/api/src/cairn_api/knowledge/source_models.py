from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_knowledge_sources_org_project_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "org_id",
            "project_id",
            "provider",
            "credential_ref",
            "external_id",
            name="uq_knowledge_sources_registration",
        ),
        UniqueConstraint("org_id", "project_id", "id"),
        CheckConstraint("provider IN ('feishu')", name="provider_values"),
        CheckConstraint("access_policy IN ('project_members')", name="access_policy_values"),
        CheckConstraint("status IN ('configured','disabled')", name="status_values"),
        CheckConstraint("access_state IN ('available','unverified','access_denied','not_found')", name="access_state_values"),
        CheckConstraint("generation > 0", name="generation_positive"),
        CheckConstraint("sync_interval_seconds IS NULL OR sync_interval_seconds BETWEEN 300 AND 604800", name="sync_interval_range"),
        CheckConstraint("(sync_interval_seconds IS NOT NULL AND status = 'configured') OR next_sync_at IS NULL", name="next_sync_enabled"),
        CheckConstraint(
            "(status = 'configured' AND disabled_at IS NULL) OR "
            "(status = 'disabled' AND disabled_at IS NOT NULL)",
            name="status_disabled_at",
        ),
        Index(
            "ix_knowledge_sources_org_project_created",
            "org_id",
            "project_id",
            "created_at",
            "id",
        ),
        Index("ix_knowledge_sources_due", "next_sync_at", "id", postgresql_where=text("status = 'configured' AND next_sync_at IS NOT NULL")),
        Index("ix_knowledge_sources_due_attempt", "last_schedule_attempt_at", "next_sync_at", "id", postgresql_where=text("status = 'configured' AND next_sync_at IS NOT NULL")),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(32), default="feishu", server_default="feishu")
    name: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str] = mapped_column(String(128))
    credential_ref: Mapped[str] = mapped_column(String(64))
    access_policy: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="configured", server_default="configured")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_interval_seconds: Mapped[int | None] = mapped_column(nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_schedule_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    access_state: Mapped[str] = mapped_column(String(32), default="unverified", server_default="unverified")
    generation: Mapped[int] = mapped_column(default=1, server_default="1")


class KnowledgeSourceSync(Base):
    __tablename__ = "knowledge_source_syncs"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        CheckConstraint("source_generation > 0", name="source_generation_positive"),
        CheckConstraint("trigger IN ('manual','scheduled')", name="trigger_values"),
        CheckConstraint(
            "(resource_id IS NULL AND resource_version_id IS NULL) OR "
            "(resource_id IS NOT NULL AND resource_version_id IS NOT NULL)",
            name="result_pair",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "source_id"],
            ["knowledge_sources.org_id", "knowledge_sources.project_id", "knowledge_sources.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id"],
            ["knowledge_resources.org_id", "knowledge_resources.project_id", "knowledge_resources.id"],
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id", "resource_version_id"],
            [
                "knowledge_resource_versions.org_id",
                "knowledge_resource_versions.project_id",
                "knowledge_resource_versions.resource_id",
                "knowledge_resource_versions.id",
            ],
        ),
        Index("ix_knowledge_source_syncs_source_created", "org_id", "project_id", "source_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    source_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    requested_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resource_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    resource_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_generation: Mapped[int] = mapped_column(default=1, server_default="1")
    trigger: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


__all__ = ["KnowledgeSource", "KnowledgeSourceSync"]
