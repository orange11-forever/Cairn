from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class KnowledgeAssistantSettings(Base):
    __tablename__ = "knowledge_assistant_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["org_id", "owner_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        Index(
            "uq_knowledge_assistant_active_scope",
            "org_id",
            "project_id",
            "owner_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 60", name="name_length"),
        CheckConstraint("char_length(instructions) <= 2000", name="instructions_length"),
        CheckConstraint(
            "jsonb_typeof(enabled_skill_ids) = 'array' AND jsonb_array_length(enabled_skill_ids) <= 22",
            name="skills_array",
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(60))
    instructions: Mapped[str] = mapped_column(String(2000))
    enabled_skill_ids: Mapped[list[str]] = mapped_column(JSONB)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision: Mapped[int] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeImportedSkill(Base):
    __tablename__ = "knowledge_imported_skills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["org_id", "owner_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("jsonb_typeof(preview) = 'object'", name="preview_object"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    preview: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
