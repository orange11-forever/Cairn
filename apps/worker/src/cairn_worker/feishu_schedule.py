"""Bounded PostgreSQL due scan for Feishu sources."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from cairn_api.knowledge.source_models import KnowledgeSource
from cairn_api.knowledge.source_sync_queue import queue_locked_source_sync
from cairn_api.projects.models import Project
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def schedule_due_sources(
    session_factory: Callable[[], Session], now: datetime, limit: int = 20,
) -> int:
    if limit < 1 or limit > 20:
        raise ValueError("due scan limit must be between 1 and 20")
    # Reservation is its own short transaction. It holds only source locks and
    # commits before the project→source queue transaction begins.
    with session_factory() as session, session.begin():
        sources = list(session.scalars(
            select(KnowledgeSource)
            .where(KnowledgeSource.status == "configured", KnowledgeSource.sync_interval_seconds.is_not(None),
                   KnowledgeSource.next_sync_at <= now)
            .order_by(KnowledgeSource.last_schedule_attempt_at.asc().nulls_first(),
                      KnowledgeSource.next_sync_at, KnowledgeSource.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ))
        attempted_at = session.scalar(select(func.clock_timestamp()))
        assert attempted_at is not None
        due = [(source.id, source.org_id, source.project_id) for source in sources]
        if due:
            # Avoid ORM updated_at onupdate: a scheduling attempt is not a
            # user-visible source configuration change.
            session.execute(
                text("UPDATE knowledge_sources SET last_schedule_attempt_at = :attempted_at WHERE id = ANY(:source_ids)"),
                {"attempted_at": attempted_at, "source_ids": [source.id for source in sources]},
            )
    queued = 0
    for source_id, org_id, project_id in due:
        try:
            with session_factory() as session, session.begin():
                project = session.scalar(select(Project).where(
                    Project.id == project_id, Project.org_id == org_id,
                ).with_for_update())
                if project is None:
                    continue
                source = session.scalar(select(KnowledgeSource).where(
                    KnowledgeSource.id == source_id,
                    KnowledgeSource.org_id == org_id,
                    KnowledgeSource.project_id == project_id,
                ).with_for_update())
                if (source is None or source.status != "configured" or
                    source.sync_interval_seconds is None or source.next_sync_at is None or
                    source.next_sync_at > now):
                    continue
                source.next_sync_at = now + timedelta(seconds=source.sync_interval_seconds)
                queue_locked_source_sync(
                    session, source=source, trigger="scheduled", requested_by=None,
                    trace_id=f"scheduler:{source_id}",
                )
                queued += 1
        except Exception:  # noqa: BLE001 -- a broken source rolls back and cannot stop other sources
            logger.warning("Feishu schedule transaction failed for source_id=%s", source_id)
            continue
    return queued
