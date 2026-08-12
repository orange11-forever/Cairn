from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cairn_api.knowledge.models import (
    IngestionBatch,
    IngestionBatchStatus,
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceSourceType,
    ResourceVersionStatus,
    UploadSession,
)
from cairn_api.projects.models import OutboxEvent

PARSER_PROFILE = "default-v1"
CHUNKING_PROFILE = "default-v1"
INGESTION_PROFILE_VERSION = "default-v1"


@dataclass(frozen=True)
class UploadRecord:
    upload: UploadSession
    item: IngestionItem


def create_batch(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    created_by: UUID,
    item_count: int,
) -> IngestionBatch:
    batch = IngestionBatch(
        org_id=org_id,
        project_id=project_id,
        created_by=created_by,
        status=IngestionBatchStatus.PENDING,
        item_count=item_count,
    )
    session.add(batch)
    session.flush()
    return batch


def create_upload_session(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    batch_id: UUID,
    file_name: str,
    normalized_path: str,
    media_type: str,
    size_bytes: int,
    sha256: str,
    object_key: str,
    expires_at: datetime,
) -> UploadRecord:
    item = IngestionItem(
        org_id=org_id,
        project_id=project_id,
        batch_id=batch_id,
        normalized_path=normalized_path,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        status=IngestionItemStatus.AWAITING_UPLOAD,
    )
    session.add(item)
    session.flush()
    upload = UploadSession(
        org_id=org_id,
        project_id=project_id,
        batch_id=batch_id,
        item_id=item.id,
        original_file_name=file_name,
        declared_media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        object_key=object_key,
        expires_at=expires_at,
    )
    session.add(upload)
    session.flush()
    return UploadRecord(upload=upload, item=item)


def get_upload_for_update(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    upload_id: UUID,
) -> UploadRecord | None:
    statement = (
        select(UploadSession, IngestionItem)
        .join(
            IngestionItem,
            (IngestionItem.org_id == UploadSession.org_id)
            & (IngestionItem.project_id == UploadSession.project_id)
            & (IngestionItem.id == UploadSession.item_id),
        )
        .where(
            UploadSession.org_id == org_id,
            UploadSession.project_id == project_id,
            UploadSession.id == upload_id,
        )
        .with_for_update()
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        return None
    upload, item = row
    return UploadRecord(upload=upload, item=item)


def create_resource_with_version(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    upload: UploadSession,
    item: IngestionItem,
    created_by: UUID,
) -> tuple[KnowledgeResource, KnowledgeResourceVersion]:
    resource = KnowledgeResource(
        org_id=org_id,
        project_id=project_id,
        title=upload.original_file_name,
        source_type=ResourceSourceType.UPLOAD,
        source_id=str(upload.id),
        external_id=item.normalized_path,
        created_by=created_by,
    )
    session.add(resource)
    session.flush()
    version = KnowledgeResourceVersion(
        org_id=org_id,
        project_id=project_id,
        resource_id=resource.id,
        source_type=ResourceSourceType.UPLOAD,
        source_id=str(upload.id),
        external_id=item.normalized_path,
        source_version=upload.sha256,
        object_key=upload.object_key,
        media_type=upload.declared_media_type,
        size_bytes=upload.size_bytes,
        sha256=upload.sha256,
        parser_profile=PARSER_PROFILE,
        chunking_profile=CHUNKING_PROFILE,
        status=ResourceVersionStatus.QUEUED,
    )
    session.add(version)
    session.flush()
    return resource, version


def create_ingestion_job(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    job_kind: JobKind,
    target_id: UUID,
    next_attempt_at: datetime,
) -> IngestionJob:
    job = IngestionJob(
        org_id=org_id,
        project_id=project_id,
        job_kind=job_kind,
        target_id=target_id,
        profile_version=INGESTION_PROFILE_VERSION,
        next_attempt_at=next_attempt_at,
    )
    session.add(job)
    session.flush()
    return job


def mark_upload_complete(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    upload: UploadSession,
    item: IngestionItem,
    completed_at: datetime,
    resource: KnowledgeResource | None,
    version: KnowledgeResourceVersion | None,
) -> None:
    if upload.org_id != org_id or upload.project_id != project_id:
        raise ValueError("upload tenant boundary mismatch")
    if item.org_id != org_id or item.project_id != project_id:
        raise ValueError("item tenant boundary mismatch")
    upload.completed_at = completed_at
    upload.resource_version_id = version.id if version is not None else None
    item.resource_id = resource.id if resource is not None else None
    item.resource_version_id = version.id if version is not None else None
    item.status = IngestionItemStatus.QUEUED
    session.flush()


def mark_item_failed(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    upload: UploadSession,
    item: IngestionItem,
    error_code: str,
    failed_at: datetime,
    abandon_upload: bool,
) -> None:
    if upload.org_id != org_id or upload.project_id != project_id:
        raise ValueError("upload tenant boundary mismatch")
    if item.org_id != org_id or item.project_id != project_id:
        raise ValueError("item tenant boundary mismatch")
    if abandon_upload:
        upload.abandoned_at = failed_at
    item.status = IngestionItemStatus.FAILED
    item.error_code = error_code
    item.error_detail = None
    item.completed_at = failed_at
    session.flush()


def refresh_batch_summary(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    batch_id: UUID,
    now: datetime,
) -> IngestionBatch:
    batch = session.scalar(
        select(IngestionBatch)
        .where(
            IngestionBatch.org_id == org_id,
            IngestionBatch.project_id == project_id,
            IngestionBatch.id == batch_id,
        )
        .with_for_update()
    )
    if batch is None:
        raise LookupError("ingestion batch is unavailable")
    item_count, ready_count, failed_count, active_count = session.execute(
        select(
            func.count(IngestionItem.id),
            func.count(IngestionItem.id).filter(IngestionItem.status == IngestionItemStatus.READY),
            func.count(IngestionItem.id).filter(IngestionItem.status == IngestionItemStatus.FAILED),
            func.count(IngestionItem.id).filter(
                IngestionItem.status.in_(
                    [IngestionItemStatus.QUEUED, IngestionItemStatus.PROCESSING]
                )
            ),
        ).where(
            IngestionItem.org_id == org_id,
            IngestionItem.project_id == project_id,
            IngestionItem.batch_id == batch_id,
        )
    ).one()
    batch.item_count = int(item_count)
    batch.ready_count = int(ready_count)
    batch.failed_count = int(failed_count)
    terminal_count = batch.ready_count + batch.failed_count
    if batch.item_count > 0 and terminal_count == batch.item_count:
        if batch.failed_count == 0:
            batch.status = IngestionBatchStatus.COMPLETED
        elif batch.ready_count == 0:
            batch.status = IngestionBatchStatus.FAILED
        else:
            batch.status = IngestionBatchStatus.COMPLETED_WITH_ERRORS
        batch.completed_at = now
    elif int(active_count) > 0 or terminal_count > 0:
        batch.status = IngestionBatchStatus.PROCESSING
        batch.completed_at = None
    else:
        batch.status = IngestionBatchStatus.PENDING
        batch.completed_at = None
    session.flush()
    return batch


def add_project_outbox_event(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    event_type: str,
    payload: dict[str, object],
) -> OutboxEvent:
    event = OutboxEvent(
        org_id=org_id,
        event_type=event_type,
        aggregate_type="project",
        aggregate_id=project_id,
        payload=payload,
    )
    session.add(event)
    session.flush()
    return event


__all__ = [
    "UploadRecord",
    "add_project_outbox_event",
    "create_batch",
    "create_ingestion_job",
    "create_resource_with_version",
    "create_upload_session",
    "get_upload_for_update",
    "mark_item_failed",
    "mark_upload_complete",
    "refresh_batch_summary",
]
