"""Add durable Feishu source sync requests."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_knowledge_source_syncs"
down_revision: str | None = "0006_knowledge_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_knowledge_sources_org_id_project_id_id",
        "knowledge_sources",
        ["org_id", "project_id", "id"],
    )
    op.execute(
        "ALTER TABLE ingestion_jobs DROP CONSTRAINT ck_ingestion_jobs_kind_values"
    )
    op.execute(
        "ALTER TABLE ingestion_jobs ADD CONSTRAINT ck_ingestion_jobs_kind_values "
        "CHECK (job_kind IN ('expand_archive','index_resource_version','sync_feishu_source'))"
    )
    op.create_table(
        "knowledge_source_syncs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_source_syncs"),
        sa.CheckConstraint(
            "(resource_id IS NULL AND resource_version_id IS NULL) OR "
            "(resource_id IS NOT NULL AND resource_version_id IS NOT NULL)",
            name="result_pair",
        ),
        sa.UniqueConstraint("org_id", "project_id", "id", name="uq_knowledge_source_syncs_org_id_project_id_id"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name="fk_knowledge_source_syncs_requested_by_users"),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_knowledge_source_syncs_org_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "source_id"],
            ["knowledge_sources.org_id", "knowledge_sources.project_id", "knowledge_sources.id"],
            name="fk_knowledge_source_syncs_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id"],
            ["knowledge_resources.org_id", "knowledge_resources.project_id", "knowledge_resources.id"],
            name="fk_knowledge_source_syncs_resource",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id", "resource_version_id"],
            ["knowledge_resource_versions.org_id", "knowledge_resource_versions.project_id", "knowledge_resource_versions.resource_id", "knowledge_resource_versions.id"],
            name="fk_knowledge_source_syncs_version",
        ),
    )
    op.create_index(
        "ix_knowledge_source_syncs_source_created",
        "knowledge_source_syncs",
        ["org_id", "project_id", "source_id", "created_at", "id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM knowledge_source_syncs)")):
        raise RuntimeError("cannot downgrade while source sync facts exist")
    if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM ingestion_jobs WHERE job_kind = 'sync_feishu_source')")):
        raise RuntimeError("cannot downgrade while source sync jobs exist")
    op.drop_table("knowledge_source_syncs")
    op.execute(
        "ALTER TABLE ingestion_jobs DROP CONSTRAINT ck_ingestion_jobs_kind_values"
    )
    op.execute(
        "ALTER TABLE ingestion_jobs ADD CONSTRAINT ck_ingestion_jobs_kind_values "
        "CHECK (job_kind IN ('expand_archive','index_resource_version'))"
    )
    op.drop_constraint(
        "uq_knowledge_sources_org_id_project_id_id", "knowledge_sources", type_="unique"
    )
