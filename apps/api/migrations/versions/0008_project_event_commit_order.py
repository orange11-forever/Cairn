"""Finalize project event cursor order at transaction commit."""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_project_event_commit_order"
down_revision: str | None = "0007_knowledge_source_syncs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION cairn_finalize_project_event_order() RETURNS trigger
        LANGUAGE plpgsql VOLATILE AS $$
        DECLARE
            next_time timestamptz;
            wall_time timestamptz;
        BEGIN
            -- Reserved global project-event stream lock. Deferred firing keeps it
            -- in the short commit tail, after normal application row locking.
            PERFORM pg_advisory_xact_lock(1128352082, 1163284052);
            wall_time := clock_timestamp();
            SELECT GREATEST(
                wall_time,
                COALESCE(MAX(occurred_at) + interval '1 microsecond', wall_time)
            ) INTO next_time
            FROM outbox_events
            WHERE org_id = NEW.org_id
              AND aggregate_type = 'project'
              AND aggregate_id = NEW.aggregate_id
              AND id <> NEW.id;

            UPDATE outbox_events SET occurred_at = next_time WHERE id = NEW.id;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER project_event_commit_order
        AFTER INSERT ON outbox_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        WHEN (NEW.aggregate_type = 'project')
        EXECUTE FUNCTION cairn_finalize_project_event_order()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER project_event_commit_order ON outbox_events")
    op.execute("DROP FUNCTION cairn_finalize_project_event_order()")
