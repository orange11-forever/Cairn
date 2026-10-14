"""Preserve private assistant profiles with one active profile per scope."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_multiple_assistants"
down_revision: str | None = "0018_answer_model_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_assistant_settings",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.drop_constraint(
        op.f("uq_knowledge_assistant_settings_org_id_project_id_owner_id"),
        "knowledge_assistant_settings",
        type_="unique",
    )
    op.create_index(
        "uq_knowledge_assistant_active_scope",
        "knowledge_assistant_settings",
        ["org_id", "project_id", "owner_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.add_column(
        "knowledge_conversation_turns", sa.Column("assistant_id", sa.UUID(), nullable=True)
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE knowledge_assistant_settings, knowledge_conversation_turns IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM knowledge_assistant_settings WHERE NOT is_active) "
            "OR EXISTS(SELECT 1 FROM knowledge_assistant_settings GROUP BY org_id,project_id,owner_id HAVING count(*) > 1) "
            "OR EXISTS(SELECT 1 FROM knowledge_conversation_turns WHERE assistant_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade populated multiple assistants")
    op.drop_column("knowledge_conversation_turns", "assistant_id")
    op.drop_index("uq_knowledge_assistant_active_scope", table_name="knowledge_assistant_settings")
    op.create_unique_constraint(
        op.f("uq_knowledge_assistant_settings_org_id_project_id_owner_id"),
        "knowledge_assistant_settings",
        ["org_id", "project_id", "owner_id"],
    )
    op.drop_column("knowledge_assistant_settings", "is_active")
