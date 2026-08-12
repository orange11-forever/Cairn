"""Expire incomplete upload sessions and remove their unreferenced objects."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from cairn_api.db.session import Database
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    IngestionItem,
    KnowledgeResourceVersion,
    UploadSession,
)
from cairn_api.knowledge.object_store import (
    Boto3ObjectStore,
    ObjectNotFound,
    ObjectStore,
    ObjectStoreError,
)
from cairn_api.settings import Settings


@dataclass(frozen=True)
class CleanupResult:
    uploads_expired: int = 0
    objects_deleted: int = 0
    objects_missing: int = 0
    objects_preserved: int = 0


def claim_expired_uploads(
    session: Session,
    *,
    now: datetime,
    limit: int,
) -> list[tuple[UploadSession, IngestionItem]]:
    return [
        (upload, item)
        for upload, item in session.execute(
            select(UploadSession, IngestionItem)
            .join(
                IngestionItem,
                (IngestionItem.org_id == UploadSession.org_id)
                & (IngestionItem.project_id == UploadSession.project_id)
                & (IngestionItem.id == UploadSession.item_id),
            )
            .where(
                UploadSession.completed_at.is_(None),
                UploadSession.abandoned_at.is_(None),
                UploadSession.expires_at <= now,
            )
            .order_by(UploadSession.expires_at, UploadSession.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    ]


def mark_expired_upload(
    session: Session,
    *,
    upload: UploadSession,
    item: IngestionItem,
    failed_at: datetime,
) -> None:
    repository.mark_item_failed(
        session,
        org_id=upload.org_id,
        project_id=upload.project_id,
        upload=upload,
        item=item,
        error_code="upload_expired",
        failed_at=failed_at,
        abandon_upload=True,
    )


def refresh_expired_batch(
    session: Session,
    *,
    upload: UploadSession,
    now: datetime,
) -> None:
    repository.refresh_batch_summary(
        session,
        org_id=upload.org_id,
        project_id=upload.project_id,
        batch_id=upload.batch_id,
        now=now,
    )


def find_orphan_upload_objects(
    session: Session,
    *,
    limit: int,
) -> list[UploadSession]:
    return list(
        session.scalars(
            select(UploadSession)
            .where(
                UploadSession.abandoned_at.is_not(None),
                UploadSession.resource_version_id.is_(None),
            )
            .order_by(UploadSession.abandoned_at, UploadSession.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )


def object_key_is_referenced(
    session: Session,
    *,
    object_key: str,
) -> bool:
    return bool(
        session.scalar(select(exists().where(KnowledgeResourceVersion.object_key == object_key)))
    )


def run_upload_cleanup(
    *,
    database: Database,
    object_store: ObjectStore,
    now: Callable[[], datetime] | None = None,
    limit: int = 1000,
) -> CleanupResult:
    if limit <= 0:
        raise ValueError("limit must be positive")
    current_time = (now or (lambda: datetime.now(UTC)))()
    with database.session_factory() as session, session.begin():
        expired = claim_expired_uploads(session, now=current_time, limit=limit)
        for upload, item in expired:
            mark_expired_upload(session, upload=upload, item=item, failed_at=current_time)
            refresh_expired_batch(session, upload=upload, now=current_time)

    deleted = 0
    missing = 0
    preserved = 0
    with database.session_factory() as session, session.begin():
        candidates = find_orphan_upload_objects(session, limit=limit)
        for upload in candidates:
            if object_key_is_referenced(session, object_key=upload.object_key):
                preserved += 1
                session.delete(upload)
                continue
            try:
                object_store.delete_object(object_key=upload.object_key)
            except ObjectNotFound:
                missing += 1
            else:
                deleted += 1
            session.delete(upload)
    return CleanupResult(
        uploads_expired=len(expired),
        objects_deleted=deleted,
        objects_missing=missing,
        objects_preserved=preserved,
    )


def run_upload_cleanup_command() -> int:
    database: Database | None = None
    object_store: Boto3ObjectStore | None = None
    try:
        settings = Settings()
        database = Database(settings.database_url)
        object_store = Boto3ObjectStore.from_settings(settings)
        result = run_upload_cleanup(database=database, object_store=object_store)
    except (SQLAlchemyError, ObjectStoreError) as exc:
        print(f"upload-cleanup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            if object_store is not None:
                object_store.close()
        finally:
            if database is not None:
                database.dispose()
    print(
        "upload-cleanup complete: "
        f"uploads_expired={result.uploads_expired} "
        f"objects_deleted={result.objects_deleted} "
        f"objects_missing={result.objects_missing} "
        f"objects_preserved={result.objects_preserved}"
    )
    return 0


__all__ = [
    "CleanupResult",
    "claim_expired_uploads",
    "find_orphan_upload_objects",
    "mark_expired_upload",
    "object_key_is_referenced",
    "refresh_expired_batch",
    "run_upload_cleanup",
    "run_upload_cleanup_command",
]
