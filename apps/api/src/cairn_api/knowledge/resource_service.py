from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    IngestionBatchStatus,
    IngestionItem,
    IngestionItemStatus,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
)
from cairn_api.knowledge.object_store import ObjectStore, ObjectStoreUnavailable
from cairn_api.knowledge.schemas import (
    BatchDetailResponse,
    ChunkContextResponse,
    ChunkResponse,
    IngestionItemResponse,
    KnowledgeCapabilities,
    KnowledgeResourcePage,
    KnowledgeResourceResponse,
    KnowledgeVersionResponse,
)

RETRYABLE_VERSION_ERRORS = frozenset(
    {
        "database_unavailable",
        "embedding_unavailable",
        "ingestion_retry_exhausted",
        "lease_lost",
        "object_store_unavailable",
    }
)


def _not_found() -> ApiProblem:
    return ApiProblem(status_code=404, code="not_found", message="资源不存在")


def _object_store_unavailable() -> ApiProblem:
    return ApiProblem(
        status_code=503,
        code="object_store_unavailable",
        message="对象存储暂时不可用",
    )


def _version_response(
    version: KnowledgeResourceVersion | None,
) -> KnowledgeVersionResponse | None:
    if version is None:
        return None
    return KnowledgeVersionResponse(
        id=version.id,
        source_type=version.source_type,
        media_type=version.media_type,
        size_bytes=version.size_bytes,
        sha256=version.sha256,
        status=ResourceVersionStatus(version.status),
        error_code=version.error_code,
        retryable=(
            version.status == ResourceVersionStatus.FAILED
            and version.error_code in RETRYABLE_VERSION_ERRORS
        ),
        created_at=version.created_at,
        processing_started_at=version.processing_started_at,
        ready_at=version.ready_at,
    )


def _resource_response(
    resource: KnowledgeResource,
    version: KnowledgeResourceVersion | None,
) -> KnowledgeResourceResponse:
    return KnowledgeResourceResponse(
        id=resource.id,
        title=resource.title,
        source_type=resource.source_type,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
        latest_version=_version_response(version),
    )


def _item_response(item: IngestionItem) -> IngestionItemResponse:
    return IngestionItemResponse(
        id=item.id,
        parent_item_id=item.parent_item_id,
        normalized_path=item.normalized_path,
        media_type=item.media_type,
        size_bytes=item.size_bytes,
        status=IngestionItemStatus(item.status),
        error_code=item.error_code,
        error_detail=item.error_detail,
        resource_id=item.resource_id,
        resource_version_id=item.resource_version_id,
        created_at=item.created_at,
        completed_at=item.completed_at,
    )


def _chunk_response(chunk: KnowledgeChunk) -> ChunkResponse:
    return ChunkResponse.model_validate(
        {
            "id": chunk.id,
            "ordinal": chunk.ordinal,
            "text": chunk.text,
            "locator": chunk.locator,
        }
    )


class KnowledgeResourceService:
    def __init__(
        self,
        session: Session,
        object_store: ObjectStore,
        *,
        policy: AuthorizationPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._object_store = object_store
        self._policy = policy or AuthorizationPolicy(session)
        self._now = now or (lambda: datetime.now(UTC))

    def get_batch(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        batch_id: UUID,
    ) -> BatchDetailResponse:
        self._policy.require_project(identity, project_id, ProjectPermission.READ)
        result = repository.get_batch_detail(
            self._session,
            org_id=identity.organization.id,
            project_id=project_id,
            batch_id=batch_id,
        )
        if result is None:
            raise _not_found()
        batch, items = result
        return BatchDetailResponse(
            id=batch.id,
            status=IngestionBatchStatus(batch.status),
            item_count=batch.item_count,
            ready_count=batch.ready_count,
            failed_count=batch.failed_count,
            created_at=batch.created_at,
            completed_at=batch.completed_at,
            items=[_item_response(item) for item in items],
        )

    def list_resources(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> KnowledgeResourcePage:
        if not 1 <= limit <= 100:
            raise ApiProblem(status_code=422, code="invalid_page_limit", message="分页大小无效")
        if self._policy.find_project(identity, project_id, ProjectPermission.READ) is None:
            raise _not_found()
        access_filter = self._policy.project_filter(
            identity,
            ProjectPermission.READ,
            cast(ColumnElement[UUID], KnowledgeResource.project_id),
        )
        resources, next_cursor = repository.list_resources(
            self._session,
            org_id=identity.organization.id,
            project_id=project_id,
            access_filter=access_filter,
            cursor=cursor,
            limit=limit,
        )
        can_write = (
            self._policy.find_project(identity, project_id, ProjectPermission.WRITE) is not None
        )
        return KnowledgeResourcePage(
            items=[_resource_response(resource, version) for resource, version in resources],
            next_cursor=next_cursor,
            capabilities=KnowledgeCapabilities(can_write=can_write),
        )

    def get_resource(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        resource_id: UUID,
    ) -> KnowledgeResourceResponse:
        self._policy.require_project(identity, project_id, ProjectPermission.READ)
        result = repository.get_resource_observation(
            self._session,
            org_id=identity.organization.id,
            project_id=project_id,
            resource_id=resource_id,
        )
        if result is None:
            raise _not_found()
        return _resource_response(*result)

    def retry_version(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        resource_id: UUID,
        version_id: UUID,
        audit: RequestAuditContext,
    ) -> KnowledgeResourceResponse:
        with self._session.begin():
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.WRITE,
                for_update=True,
            )
            result = repository.get_resource_version_job_for_update(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                resource_id=resource_id,
                version_id=version_id,
            )
            if result is None:
                raise _not_found()
            resource, version, job = result
            if (
                version.status != ResourceVersionStatus.FAILED
                or version.error_code not in RETRYABLE_VERSION_ERRORS
            ):
                raise ApiProblem(
                    status_code=409,
                    code="version_not_retryable",
                    message="该版本不可重试",
                )
            repository.queue_manual_retry(
                self._session,
                job=job,
                version=version,
                queued_at=self._now(),
            )
            self._audit(
                identity=identity,
                audit=audit,
                action="knowledge.version_retried",
                resource_type="knowledge_resource_version",
                resource_id=version.id,
                details={
                    "projectId": str(project_id),
                    "resourceId": str(resource.id),
                    "versionId": str(version.id),
                    "jobId": str(job.id),
                },
            )
            repository.add_project_outbox_event(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                event_type="knowledge.version_retried",
                payload={
                    "projectId": str(project_id),
                    "resourceId": str(resource.id),
                    "versionId": str(version.id),
                    "status": ResourceVersionStatus.QUEUED.value,
                },
            )
        return _resource_response(resource, version)

    def delete_resource(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        resource_id: UUID,
        audit: RequestAuditContext,
    ) -> None:
        with self._session.begin():
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.WRITE,
                for_update=True,
            )
            result = repository.soft_delete_resource(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                resource_id=resource_id,
                deleted_by=identity.user.id,
                deleted_at=self._now(),
            )
            if result is None:
                raise _not_found()
            resource, changed = result
            if not changed:
                return
            self._audit(
                identity=identity,
                audit=audit,
                action="knowledge.resource_deleted",
                resource_type="knowledge_resource",
                resource_id=resource.id,
                details={"projectId": str(project_id)},
            )
            repository.add_project_outbox_event(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                event_type="knowledge.resource_deleted",
                payload={"projectId": str(project_id), "resourceId": str(resource.id)},
            )

    def create_download(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        resource_id: UUID,
        audit: RequestAuditContext,
    ) -> str:
        try:
            with self._session.begin():
                self._policy.require_project(identity, project_id, ProjectPermission.READ)
                result = repository.get_active_resource(
                    self._session,
                    org_id=identity.organization.id,
                    project_id=project_id,
                    resource_id=resource_id,
                )
                if result is None:
                    raise _not_found()
                resource, version = result
                if version is None:
                    raise _not_found()
                url = self._object_store.presign_get(
                    object_key=version.object_key,
                    download_name=resource.title,
                    expires_in=timedelta(minutes=5),
                )
                self._audit(
                    identity=identity,
                    audit=audit,
                    action="knowledge.downloaded",
                    resource_type="knowledge_resource",
                    resource_id=resource.id,
                    details={
                        "projectId": str(project_id),
                        "versionId": str(version.id),
                    },
                )
        except ObjectStoreUnavailable:
            raise _object_store_unavailable() from None
        return url

    def get_chunk_context(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        resource_id: UUID,
        chunk_id: UUID,
    ) -> ChunkContextResponse:
        self._policy.require_project(identity, project_id, ProjectPermission.READ)
        result = repository.get_chunk_context(
            self._session,
            org_id=identity.organization.id,
            project_id=project_id,
            resource_id=resource_id,
            chunk_id=chunk_id,
        )
        if result is None:
            raise _not_found()
        version, hit, before, after = result
        return ChunkContextResponse(
            resource_id=resource_id,
            resource_version_id=version.id,
            hit=_chunk_response(hit),
            before=_chunk_response(before) if before is not None else None,
            after=_chunk_response(after) if after is not None else None,
        )

    def _audit(
        self,
        *,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        action: str,
        resource_type: str,
        resource_id: UUID,
        details: dict[str, object],
    ) -> None:
        add_audit_log(
            self._session,
            org_id=identity.organization.id,
            actor_type="user",
            actor_id=identity.user.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=audit.trace_id,
            ip=audit.ip,
            user_agent=audit.user_agent,
            details=details,
        )


__all__ = ["RETRYABLE_VERSION_ERRORS", "KnowledgeResourceService"]
