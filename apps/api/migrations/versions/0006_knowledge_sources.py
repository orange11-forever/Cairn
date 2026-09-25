"""Add persistent project knowledge source registrations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_knowledge_sources"
down_revision: str | None = "0005_enterprise_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="feishu", nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        sa.Column("access_policy", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="configured", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider IN ('feishu')", name=op.f("ck_knowledge_sources_provider_values")),
        sa.CheckConstraint(
            "access_policy IN ('project_members')",
            name=op.f("ck_knowledge_sources_access_policy_values"),
        ),
        sa.CheckConstraint(
            "status IN ('configured','disabled')",
            name=op.f("ck_knowledge_sources_status_values"),
        ),
        sa.CheckConstraint(
            "(status = 'configured' AND disabled_at IS NULL) OR "
            "(status = 'disabled' AND disabled_at IS NOT NULL)",
            name=op.f("ck_knowledge_sources_status_disabled_at"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_knowledge_sources_org_project_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_sources")),
        sa.UniqueConstraint(
            "org_id",
            "project_id",
            "provider",
            "credential_ref",
            "external_id",
            name="uq_knowledge_sources_registration",
        ),
    )
    op.create_index(
        "ix_knowledge_sources_org_project_created",
        "knowledge_sources",
        ["org_id", "project_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_sources_org_project_created", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
