"""Store each private assistant's small custom avatar without changing existing profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_assistant_avatar"
down_revision: str | None = "0023_project_scheduling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_assistant_settings", sa.Column("avatar_data_url", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_knowledge_assistant_settings_avatar_length"),
        "knowledge_assistant_settings",
        "avatar_data_url IS NULL OR char_length(avatar_data_url) <= 90000",
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE knowledge_assistant_settings IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM knowledge_assistant_settings WHERE avatar_data_url IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade populated assistant avatars")
    op.drop_constraint(
        op.f("ck_knowledge_assistant_settings_avatar_length"),
        "knowledge_assistant_settings",
        type_="check",
    )
    op.drop_column("knowledge_assistant_settings", "avatar_data_url")
