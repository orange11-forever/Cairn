"""Persist private model choices and immutable per-turn model metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0018_answer_model_selection"
down_revision: str | None = "0017_assistant_skills"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_assistant_settings", sa.Column("model_id", sa.String(64), nullable=True)
    )
    op.add_column(
        "knowledge_conversation_turns", sa.Column("model_snapshot", JSONB(), nullable=True)
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
            "SELECT EXISTS(SELECT 1 FROM knowledge_assistant_settings WHERE model_id IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM knowledge_conversation_turns WHERE model_snapshot IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade populated answer model selections")
    op.drop_column("knowledge_conversation_turns", "model_snapshot")
    op.drop_column("knowledge_assistant_settings", "model_id")
