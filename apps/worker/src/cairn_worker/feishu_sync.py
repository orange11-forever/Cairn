import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

from cairn_api.audit.repository import add_audit_log
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobAttemptStatus,
    IngestionJobStatus,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceSourceType,
    ResourceVersionStatus,
)
from cairn_api.knowledge.object_store import ObjectStoreUnavailable
from cairn_api.knowledge.source_access import is_canonical_feishu_revision
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.projects.models import Project
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn_worker.errors import WorkerFailure
from cairn_worker.feishu import FeishuFailure
from cairn_worker.feishu_credentials import FeishuCredentialFailure, FeishuCredentialResolver
from cairn_worker.feishu_outcomes import FeishuSyncFailure
from cairn_worker.leases import ClaimedJob, finish_job

Now = Callable[[], datetime]


def _failure(*, retryable: bool = False, retry_after: int | None = None) -> WorkerFailure:
    bounded_retry_after = (
        min(3600, max(0, retry_after)) if isinstance(retry_after, int) else None
    )
    return WorkerFailure(
        "parser_failed",
        "",
        retryable=retryable,
        retry_after=(
            timedelta(seconds=bounded_retry_after)
            if bounded_retry_after is not None
            else None
        ),
    )


def _active_profile(session: Session, org_id: UUID) -> EmbeddingProfile | None:
    profile = session.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.org_id == org_id,
            EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE,
        )
    )
    if profile is not None:
        return profile
    return session.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.org_id.is_(None),
            EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE,
        )
    )


def _trusted_target(
    session: Session, claim: ClaimedJob, now: datetime
) -> tuple[KnowledgeSourceSync, KnowledgeSource]:
    job = session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == claim.job_id,
            IngestionJob.org_id == claim.org_id,
            IngestionJob.project_id == claim.project_id,
            IngestionJob.job_kind == JobKind.SYNC_FEISHU_SOURCE,
            IngestionJob.target_id == claim.target_id,
            IngestionJob.profile_version == "feishu-sync-v1",
            IngestionJob.status == IngestionJobStatus.RUNNING,
            IngestionJob.lease_owner == claim.lease_owner,
            IngestionJob.lease_expires_at > now,
        )
    )
    attempt = session.scalar(
        select(IngestionJobAttempt).where(
            IngestionJobAttempt.id == claim.attempt_id,
            IngestionJobAttempt.job_id == claim.job_id,
            IngestionJobAttempt.status == IngestionJobAttemptStatus.RUNNING,
        )
    )
    if job is None or attempt is None:
        raise WorkerFailure("lease_lost", "", retryable=True)
    sync = session.scalar(
        select(KnowledgeSourceSync).where(
            KnowledgeSourceSync.id == claim.target_id,
            KnowledgeSourceSync.org_id == claim.org_id,
            KnowledgeSourceSync.project_id == claim.project_id,
        )
    )
    if sync is None:
        raise _failure()
    source = session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == sync.source_id,
            KnowledgeSource.org_id == claim.org_id,
            KnowledgeSource.project_id == claim.project_id,
            KnowledgeSource.provider == "feishu",
            KnowledgeSource.access_policy == "project_members",
            KnowledgeSource.status == "configured",
        )
    )
    if source is None:
        raise _failure()
    if source.generation != sync.source_generation:
        raise _failure()
    return sync, source


def handle_feishu_source_sync(
    session: Any,
    claim: ClaimedJob,
    heartbeat: Any,
    *,
    object_store: Any,
    resolver: FeishuCredentialResolver | None,
    now: Now,
) -> None:
    if claim.job_kind != JobKind.SYNC_FEISHU_SOURCE:
        raise _failure()
    database = cast(Session, session)
    read_started_at = now()
    sync, observed_source = _trusted_target(database, claim, read_started_at)
    credential_ref = observed_source.credential_ref
    external_id = observed_source.external_id
    generation = observed_source.generation
    try:
        active_resolver = resolver or FeishuCredentialResolver.from_environment()
        client = active_resolver.create_client(
            org_id=claim.org_id, credential_ref=credential_ref
        )
        snapshot = client.read_document(external_id)
    except FeishuCredentialFailure as exc:
        raise FeishuSyncFailure(
            code=exc.code, source_id=observed_source.id, generation=generation,
            retryable=exc.retryable, checked=False,
        ) from None
    except FeishuFailure as exc:
        raise FeishuSyncFailure(
            code=exc.code, source_id=observed_source.id, generation=generation,
            retryable=exc.retryable, checked=exc.code != "feishu_auth_failed",
            retry_after=(timedelta(seconds=min(3600, max(0, exc.retry_after_seconds)))
                         if exc.retry_after_seconds is not None else None),
        ) from None
    if (
        snapshot.document_id != external_id
        or type(snapshot.content) is not str
        or type(snapshot.title) is not str
        or type(snapshot.revision_id) is not int
        or snapshot.revision_id < 0
        or snapshot.revision_id >= 10**255
    ):
        raise _failure()
    try:
        content = snapshot.content.encode("utf-8")
        snapshot.title.encode("utf-8")
    except UnicodeError:
        raise _failure() from None
    if not content or not snapshot.content.strip():
        raise WorkerFailure("no_extractable_text", "", retryable=False)
    if hashlib.sha256(content).hexdigest() != snapshot.content_sha256:
        raise _failure()
    heartbeat.ensure_owned()

    job = database.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.id == claim.job_id,
            IngestionJob.org_id == claim.org_id,
            IngestionJob.project_id == claim.project_id,
            IngestionJob.job_kind == JobKind.SYNC_FEISHU_SOURCE,
            IngestionJob.target_id == claim.target_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    attempt = database.scalar(
        select(IngestionJobAttempt)
        .where(
            IngestionJobAttempt.id == claim.attempt_id,
            IngestionJobAttempt.job_id == claim.job_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        job is None
        or attempt is None
        or job.status != IngestionJobStatus.RUNNING
        or attempt.status != IngestionJobAttemptStatus.RUNNING
        or job.lease_owner != claim.lease_owner
        or job.profile_version != "feishu-sync-v1"
        or job.lease_expires_at is None
        or job.lease_expires_at <= now()
    ):
        raise WorkerFailure("lease_lost", "", retryable=True)

    project = database.scalar(
        select(Project)
        .where(Project.id == claim.project_id, Project.org_id == claim.org_id)
        .with_for_update()
    )
    if project is None:
        raise _failure()
    resource = database.scalar(
        select(KnowledgeResource)
        .where(
            KnowledgeResource.org_id == claim.org_id,
            KnowledgeResource.project_id == claim.project_id,
            KnowledgeResource.source_type == ResourceSourceType.FEISHU,
            KnowledgeResource.source_id == str(sync.source_id),
            KnowledgeResource.external_id == external_id,
        )
        .with_for_update()
    )
    source = database.scalar(
        select(KnowledgeSource)
        .where(
            KnowledgeSource.id == sync.source_id,
            KnowledgeSource.org_id == claim.org_id,
            KnowledgeSource.project_id == claim.project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    sync = database.scalar(
        select(KnowledgeSourceSync)
        .where(
            KnowledgeSourceSync.id == claim.target_id,
            KnowledgeSourceSync.org_id == claim.org_id,
            KnowledgeSourceSync.project_id == claim.project_id,
            KnowledgeSourceSync.source_id == observed_source.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        source is None
        or sync is None
        or source.status != "configured"
        or source.provider != "feishu"
        or source.access_policy != "project_members"
        or source.credential_ref != credential_ref
        or source.generation != generation
        or source.external_id != external_id
    ):
        raise _failure()
    if resource is not None and resource.deleted_at is not None:
        raise FeishuSyncFailure(
            code="feishu_resource_deleted", source_id=source.id,
            generation=generation, retryable=False, checked=True,
        )
    profile = _active_profile(database, claim.org_id)
    if profile is None:
        raise _failure()

    revision = str(snapshot.revision_id)
    versions = [] if resource is None else list(
        database.scalars(
            select(KnowledgeResourceVersion).where(
                KnowledgeResourceVersion.org_id == claim.org_id,
                KnowledgeResourceVersion.project_id == claim.project_id,
                KnowledgeResourceVersion.resource_id == resource.id,
            )
        )
    )
    same = next((version for version in versions if version.source_version == revision), None)
    if same is not None:
        if same.sha256 != snapshot.content_sha256:
            raise _failure(retryable=True)
        sync.resource_id = same.resource_id
        sync.resource_version_id = same.id
        source.access_state = "available"
        source.last_checked_at = now()
        source.last_success_at = source.last_checked_at
        source.last_error_code = None
        sync.failure_code = None
        _record_completion(database, claim=claim, sync=sync, source=source)
        finish_job(database, claim=claim, now=now())
        return
    newer = [
        version
        for version in versions
        if is_canonical_feishu_revision(version.source_version)
        and int(version.source_version) > snapshot.revision_id
    ]
    if newer:
        raise _failure()

    if resource is None:
        title = snapshot.title.strip()[:512] or source.name.strip()[:512]
        resource = KnowledgeResource(
            org_id=claim.org_id,
            project_id=claim.project_id,
            title=title,
            source_type=ResourceSourceType.FEISHU,
            source_id=str(source.id),
            external_id=source.external_id,
            created_by=sync.requested_by,
        )
        database.add(resource)
        database.flush()
    else:
        resource.title = snapshot.title.strip()[:512] or source.name.strip()[:512]
    version_id = uuid4()
    object_key = f"orgs/{claim.org_id}/projects/{claim.project_id}/sources/{source.id}/versions/{version_id}.txt"
    database.info.setdefault("cairn_rollback_cleanup", []).append(
        lambda: object_store.delete_object(object_key=object_key)
    )
    try:
        object_store.put_object(
            object_key=object_key,
            source=BytesIO(content),
            size_bytes=len(content),
            content_type="text/plain; charset=utf-8",
            checksum_sha256=snapshot.content_sha256,
        )
    except ObjectStoreUnavailable:
        raise WorkerFailure.for_code("object_store_unavailable", "") from None
    version = KnowledgeResourceVersion(
        id=version_id,
        org_id=claim.org_id,
        project_id=claim.project_id,
        resource_id=resource.id,
        source_type=ResourceSourceType.FEISHU,
        source_id=str(source.id),
        external_id=source.external_id,
        source_version=revision,
        object_key=object_key,
        media_type="text/plain",
        size_bytes=len(content),
        sha256=snapshot.content_sha256,
        parser_profile=repository.PARSER_PROFILE,
        chunking_profile=profile.version,
        status=ResourceVersionStatus.QUEUED,
    )
    database.add(version)
    database.flush()
    database.add(
        IngestionJob(
            org_id=claim.org_id,
            project_id=claim.project_id,
            job_kind=JobKind.INDEX_RESOURCE_VERSION,
            target_id=version.id,
            profile_version=profile.version,
            next_attempt_at=now(),
        )
    )
    sync.resource_id = resource.id
    sync.resource_version_id = version.id
    source.access_state = "available"
    source.last_checked_at = now()
    source.last_success_at = source.last_checked_at
    source.last_error_code = None
    sync.failure_code = None
    _record_completion(database, claim=claim, sync=sync, source=source)
    finish_job(database, claim=claim, now=now())


def _record_completion(
    database: Session,
    *,
    claim: ClaimedJob,
    sync: KnowledgeSourceSync,
    source: KnowledgeSource,
) -> None:
    details: dict[str, object] = {
        "projectId": str(claim.project_id),
        "sourceId": str(source.id),
        "syncId": str(sync.id),
        "resourceId": str(sync.resource_id),
        "versionId": str(sync.resource_version_id),
    }
    add_audit_log(
        database,
        org_id=claim.org_id,
        actor_type="system",
        actor_id=None,
        action="knowledge.source_synced",
        resource_type="knowledge_source_sync",
        resource_id=sync.id,
        trace_id=f"worker:{claim.attempt_id}",
        ip=None,
        user_agent=None,
        details=details,
    )
    repository.add_project_outbox_event(
        database,
        org_id=claim.org_id,
        project_id=claim.project_id,
        event_type="knowledge.source_synced",
        payload=details,
    )


def build_feishu_sync_handler(
    *,
    object_store: Any,
    resolver: FeishuCredentialResolver | None = None,
    now: Now | None = None,
) -> Callable[[Any, ClaimedJob, Any], None]:
    current_time = now or (lambda: datetime.now(UTC))

    def handler(session: Any, claim: ClaimedJob, heartbeat: Any) -> None:
        handle_feishu_source_sync(
            session,
            claim,
            heartbeat,
            object_store=object_store,
            resolver=resolver,
            now=current_time,
        )

    return handler


__all__ = ["build_feishu_sync_handler", "handle_feishu_source_sync"]
