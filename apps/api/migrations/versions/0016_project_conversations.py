"""Persist private complete project conversation turns."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_project_conversations"
down_revision: str | None = "0015_structure_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_conversations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(60), nullable=False, server_default="新对话"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "owner_id"],
            ["memberships.org_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "project_id", "id"),
        sa.CheckConstraint("revision BETWEEN 1 AND 51", name="revision_range"),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 60", name="title_length"),
    )
    op.create_index(
        "ix_knowledge_conversations_owner_created",
        "knowledge_conversations",
        ["org_id", "project_id", "owner_id", "created_at", "id"],
    )
    op.create_table(
        "knowledge_conversation_turns",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("answer", postgresql.JSONB(), nullable=False),
        sa.Column("context_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "conversation_id"],
            [
                "knowledge_conversations.org_id",
                "knowledge_conversations.project_id",
                "knowledge_conversations.id",
            ],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("conversation_id", "sequence"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 50", name="sequence_range"),
        sa.CheckConstraint("char_length(question) BETWEEN 3 AND 500", name="question_length"),
        sa.CheckConstraint("jsonb_typeof(answer) = 'object'", name="answer_object"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE knowledge_conversations, knowledge_conversation_turns IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM knowledge_conversations) OR EXISTS (SELECT 1 FROM knowledge_conversation_turns)"
        )
    ):
        raise RuntimeError("Cannot downgrade populated project conversations")
    op.drop_table("knowledge_conversation_turns")
    op.drop_table("knowledge_conversations")
