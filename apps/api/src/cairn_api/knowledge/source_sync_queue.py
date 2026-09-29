"""Queue a source sync after the caller locks its project and source."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn_api.audit.repository import add_audit_log
from cairn_api.knowledge.models import IngestionJob, IngestionJobStatus, JobKind
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.projects.models import OutboxEvent


def queue_locked_source_sync(
    session: Session,
    *,
    source: KnowledgeSource,
    trigger: str,
    requested_by: UUID | None,
    trace_id: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[KnowledgeSourceSync, IngestionJob]:
    existing = session.execute(
        select(KnowledgeSourceSync, IngestionJob)
        .join(
            IngestionJob,
            (IngestionJob.org_id == KnowledgeSourceSync.org_id)
            & (IngestionJob.project_id == KnowledgeSourceSync.project_id)
            & (IngestionJob.target_id == KnowledgeSourceSync.id)
            & (IngestionJob.job_kind == JobKind.SYNC_FEISHU_SOURCE),
        )
        .where(
            KnowledgeSourceSync.org_id == source.org_id,
            KnowledgeSourceSync.project_id == source.project_id,
            KnowledgeSourceSync.source_id == source.id,
            KnowledgeSourceSync.source_generation == source.generation,
            IngestionJob.status.in_([IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING]),
        )
        .order_by(KnowledgeSourceSync.created_at.desc(), KnowledgeSourceSync.id.desc())
        .limit(1)
    ).one_or_none()
    if existing is not None:
        return existing[0], existing[1]
    sync = KnowledgeSourceSync(
        org_id=source.org_id,
        project_id=source.project_id,
        source_id=source.id,
        source_generation=source.generation,
        trigger=trigger,
        requested_by=requested_by,
    )
    session.add(sync)
    session.flush()
    job = IngestionJob(
        org_id=source.org_id,
        project_id=source.project_id,
        job_kind=JobKind.SYNC_FEISHU_SOURCE,
        target_id=sync.id,
        profile_version="feishu-sync-v1",
    )
    session.add(job)
    session.flush()
    details: dict[str, object] = {
        "projectId": str(source.project_id),
        "sourceId": str(source.id),
        "syncId": str(sync.id),
        "jobId": str(job.id),
        "trigger": trigger,
    }
    add_audit_log(
        session,
        org_id=source.org_id,
        actor_type="user" if requested_by is not None else "system",
        actor_id=requested_by,
        action="knowledge.source_sync_queued",
        resource_type="knowledge_source_sync",
        resource_id=sync.id,
        trace_id=trace_id,
        ip=ip,
        user_agent=user_agent,
        details=details,
    )
    session.add(
        OutboxEvent(
            org_id=source.org_id,
            event_type="knowledge.source_sync_queued",
            aggregate_type="project",
            aggregate_id=source.project_id,
            payload=details,
        )
    )
    return sync, job
