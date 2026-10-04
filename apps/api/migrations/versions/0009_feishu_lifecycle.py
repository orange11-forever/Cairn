"""Add Feishu source lifecycle, schedule, and sync outcome facts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_feishu_lifecycle"
down_revision: str | None = "0008_project_event_commit_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_sources", sa.Column("sync_interval_seconds", sa.Integer(), nullable=True))
    op.add_column("knowledge_sources", sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_sources", sa.Column("last_schedule_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_sources", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_sources", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_sources", sa.Column("last_error_code", sa.String(length=64), nullable=True))
    op.add_column("knowledge_sources", sa.Column("access_state", sa.String(length=32), server_default="unverified", nullable=False))
    op.add_column("knowledge_sources", sa.Column("generation", sa.Integer(), server_default="1", nullable=False))
    op.execute("UPDATE knowledge_sources SET access_state = 'available' WHERE status = 'configured' AND access_policy = 'project_members'")
    op.create_check_constraint("access_state_values", "knowledge_sources", "access_state IN ('available','unverified','access_denied','not_found')")
    op.create_check_constraint("generation_positive", "knowledge_sources", "generation > 0")
    op.create_check_constraint("sync_interval_range", "knowledge_sources", "sync_interval_seconds IS NULL OR sync_interval_seconds BETWEEN 300 AND 604800")
    op.create_check_constraint("next_sync_enabled", "knowledge_sources", "(sync_interval_seconds IS NOT NULL AND status = 'configured') OR next_sync_at IS NULL")
    op.create_index("ix_knowledge_sources_due", "knowledge_sources", ["next_sync_at", "id"], postgresql_where=sa.text("status = 'configured' AND next_sync_at IS NOT NULL"))
    op.create_index("ix_knowledge_sources_due_attempt", "knowledge_sources", ["last_schedule_attempt_at", "next_sync_at", "id"], postgresql_where=sa.text("status = 'configured' AND next_sync_at IS NOT NULL"))
    op.alter_column("knowledge_source_syncs", "requested_by", nullable=True)
    op.add_column("knowledge_source_syncs", sa.Column("source_generation", sa.Integer(), server_default="1", nullable=False))
    op.add_column("knowledge_source_syncs", sa.Column("trigger", sa.String(length=16), server_default="manual", nullable=False))
    op.add_column("knowledge_source_syncs", sa.Column("failure_code", sa.String(length=64), nullable=True))
    op.create_check_constraint("source_generation_positive", "knowledge_source_syncs", "source_generation > 0")
    op.create_check_constraint("trigger_values", "knowledge_source_syncs", "trigger IN ('manual','scheduled')")


def downgrade() -> None:
    connection = op.get_bind()
    populated = connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM knowledge_sources WHERE sync_interval_seconds IS NOT NULL OR next_sync_at IS NOT NULL OR last_schedule_attempt_at IS NOT NULL OR last_checked_at IS NOT NULL OR last_success_at IS NOT NULL OR last_error_code IS NOT NULL OR generation <> 1 OR (status = 'configured' AND access_state <> 'available') OR (status = 'disabled' AND access_state <> 'unverified'))"))
    sync_facts = connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM knowledge_source_syncs WHERE source_generation <> 1 OR trigger <> 'manual' OR failure_code IS NOT NULL OR requested_by IS NULL)"))
    if populated or sync_facts:
        raise RuntimeError("cannot downgrade while Feishu lifecycle facts exist")
    op.drop_constraint(op.f("ck_knowledge_source_syncs_trigger_values"), "knowledge_source_syncs", type_="check")
    op.drop_constraint(op.f("ck_knowledge_source_syncs_source_generation_positive"), "knowledge_source_syncs", type_="check")
    op.drop_column("knowledge_source_syncs", "failure_code")
    op.drop_column("knowledge_source_syncs", "trigger")
    op.drop_column("knowledge_source_syncs", "source_generation")
    op.alter_column("knowledge_source_syncs", "requested_by", nullable=False)
    op.drop_index("ix_knowledge_sources_due", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_due_attempt", table_name="knowledge_sources")
    for constraint in ("next_sync_enabled", "sync_interval_range", "generation_positive", "access_state_values"):
        op.drop_constraint(op.f(f"ck_knowledge_sources_{constraint}"), "knowledge_sources", type_="check")
    for column in ("generation", "access_state", "last_error_code", "last_success_at", "last_checked_at", "last_schedule_attempt_at", "next_sync_at", "sync_interval_seconds"):
        op.drop_column("knowledge_sources", column)
