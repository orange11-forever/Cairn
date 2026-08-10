"""Add normalized project ACL entries and backfill existing projects."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_rbac_project_acl"
down_revision: str | None = "0003_project_task_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_acl_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_type", sa.String(length=16), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("granted_by_type", sa.String(length=16), nullable=False),
        sa.Column("granted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_by_type", sa.String(length=16), nullable=True),
        sa.Column("revoked_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "resource_type IN ('project')",
            name=op.f("ck_resource_acl_entries_resource_type"),
        ),
        sa.CheckConstraint(
            "principal_type IN ('org','role','user','group')",
            name=op.f("ck_resource_acl_entries_principal_type"),
        ),
        sa.CheckConstraint(
            "permission IN ('read','write','manage')",
            name=op.f("ck_resource_acl_entries_permission"),
        ),
        sa.CheckConstraint(
            "length(principal_id) > 0",
            name=op.f("ck_resource_acl_entries_principal_id_nonempty"),
        ),
        sa.CheckConstraint(
            "(granted_by_type = 'user' AND granted_by_id IS NOT NULL) OR "
            "(granted_by_type = 'system' AND granted_by_id IS NULL)",
            name=op.f("ck_resource_acl_entries_granted_actor"),
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_type IS NULL "
            "AND revoked_by_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_type = 'user' "
            "AND revoked_by_id IS NOT NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_type = 'system' "
            "AND revoked_by_id IS NULL)",
            name=op.f("ck_resource_acl_entries_revoked_actor"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_resource_acl_entries_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_id"],
            ["users.id"],
            name=op.f("fk_resource_acl_entries_granted_by_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"],
            ["users.id"],
            name=op.f("fk_resource_acl_entries_revoked_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_acl_entries")),
    )
    op.create_index(
        "uq_resource_acl_entries_active_principal",
        "resource_acl_entries",
        ["org_id", "resource_type", "resource_id", "principal_type", "principal_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_resource_acl_entries_org_resource_active",
        "resource_acl_entries",
        ["org_id", "resource_type", "resource_id", "granted_at", "id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_resource_acl_entries_org_principal_active",
        "resource_acl_entries",
        ["org_id", "principal_type", "principal_id", "resource_type", "resource_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_resource_acl_entries_org_resource_granted",
        "resource_acl_entries",
        ["org_id", "resource_type", "resource_id", "granted_at", "id"],
    )

    op.execute(
        """
        INSERT INTO resource_acl_entries (
          id, org_id, resource_type, resource_id, principal_type, principal_id,
          permission, granted_by_type, granted_by_id
        )
        SELECT
          gen_random_uuid(), p.org_id, 'project', p.id, 'org', p.org_id::text,
          'read', 'system', NULL
        FROM projects AS p
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_resource_acl_entries_org_resource_granted",
        table_name="resource_acl_entries",
    )
    op.drop_index(
        "ix_resource_acl_entries_org_principal_active",
        table_name="resource_acl_entries",
    )
    op.drop_index(
        "ix_resource_acl_entries_org_resource_active",
        table_name="resource_acl_entries",
    )
    op.drop_index(
        "uq_resource_acl_entries_active_principal",
        table_name="resource_acl_entries",
    )
    op.drop_table("resource_acl_entries")
