"""Private assistant configuration and immutable imported read-only skills."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0017_assistant_skills"
down_revision: str | None = "0016_project_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("knowledge_assistant_settings", "knowledge_imported_skills"):
        extra = (
            [
                sa.Column("name", sa.String(60), nullable=False),
                sa.Column("instructions", sa.String(2000), nullable=False),
                sa.Column("enabled_skill_ids", JSONB(), nullable=False),
                sa.Column("revision", sa.Integer(), nullable=False),
                sa.UniqueConstraint("org_id", "project_id", "owner_id"),
                sa.CheckConstraint("revision > 0", name="revision_positive"),
                sa.CheckConstraint("char_length(name) BETWEEN 1 AND 60", name="name_length"),
                sa.CheckConstraint("char_length(instructions) <= 2000", name="instructions_length"),
                sa.CheckConstraint(
                    "jsonb_typeof(enabled_skill_ids) = 'array' AND jsonb_array_length(enabled_skill_ids) <= 22",
                    name="skills_array",
                ),
            ]
            if table == "knowledge_assistant_settings"
            else [
                sa.Column("request_fingerprint", sa.String(64), nullable=False),
                sa.Column("preview", JSONB(), nullable=False),
                sa.CheckConstraint("jsonb_typeof(preview) = 'object'", name="preview_object"),
            ]
        )
        op.create_table(
            table,
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("org_id", sa.UUID(), nullable=False),
            sa.Column("project_id", sa.UUID(), nullable=False),
            sa.Column("owner_id", sa.UUID(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["org_id", "owner_id"],
                ["memberships.org_id", "memberships.user_id"],
                ondelete="CASCADE",
            ),
            *extra,
        )
    op.add_column(
        "knowledge_conversation_turns",
        sa.Column("assistant_name", sa.String(60), nullable=False, server_default="岑宁"),
    )
    op.add_column(
        "knowledge_conversation_turns",
        sa.Column("assistant_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_conversation_turns", sa.Column("skill_id", sa.String(64), nullable=True)
    )
    op.create_check_constraint(
        "assistant_revision_nonnegative", "knowledge_conversation_turns", "assistant_revision >= 0"
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE knowledge_assistant_settings, knowledge_imported_skills, knowledge_conversation_turns IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM knowledge_assistant_settings) OR EXISTS(SELECT 1 FROM knowledge_imported_skills) OR EXISTS(SELECT 1 FROM knowledge_conversation_turns WHERE assistant_name <> '岑宁' OR assistant_revision <> 0 OR skill_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade populated assistant skills")
    op.drop_constraint(
        op.f("ck_knowledge_conversation_turns_assistant_revision_nonnegative"),
        "knowledge_conversation_turns",
        type_="check",
    )
    for column in ("skill_id", "assistant_revision", "assistant_name"):
        op.drop_column("knowledge_conversation_turns", column)
    op.drop_table("knowledge_imported_skills")
    op.drop_table("knowledge_assistant_settings")
