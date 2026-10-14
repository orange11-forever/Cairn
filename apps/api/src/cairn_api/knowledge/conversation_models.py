from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class KnowledgeConversation(Base):
    __tablename__ = "knowledge_conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["org_id", "owner_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("org_id", "project_id", "id"),
        CheckConstraint("revision BETWEEN 1 AND 51", name="revision_range"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 60", name="title_length"),
        Index(
            "ix_knowledge_conversations_owner_created",
            "org_id",
            "project_id",
            "owner_id",
            "created_at",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(60), default="新对话", server_default="新对话")
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeConversationTurn(Base):
    __tablename__ = "knowledge_conversation_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "project_id", "conversation_id"],
            [
                "knowledge_conversations.org_id",
                "knowledge_conversations.project_id",
                "knowledge_conversations.id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint("conversation_id", "sequence"),
        CheckConstraint("sequence BETWEEN 1 AND 50", name="sequence_range"),
        CheckConstraint("assistant_revision >= 0", name="assistant_revision_nonnegative"),
        CheckConstraint("char_length(question) BETWEEN 3 AND 500", name="question_length"),
        CheckConstraint("jsonb_typeof(answer) = 'object'", name="answer_object"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    conversation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    assistant_name: Mapped[str] = mapped_column(String(60), default="岑宁", server_default="岑宁")
    assistant_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    assistant_revision: Mapped[int] = mapped_column(default=0, server_default="0")
    skill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    sequence: Mapped[int] = mapped_column()
    question: Mapped[str] = mapped_column(String(500))
    answer: Mapped[dict[str, object]] = mapped_column(JSONB)
    context_truncated: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
