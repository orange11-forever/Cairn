from datetime import UTC, datetime
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization import repository as authorization_repository
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.models import IngestionJob, IngestionJobStatus, JobKind
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.knowledge.source_schemas import (
    KnowledgeSourcePage,
    KnowledgeSourceResponse,
    KnowledgeSourceSyncResponse,
)
from cairn_api.pagination import page_by_timestamp
from cairn_api.projects.models import OutboxEvent


def _not_found() -> ApiProblem:
    return ApiProblem(status_code=404, code="not_found", message="资源不存在")


def _source_conflict() -> ApiProblem:
    return ApiProblem(status_code=409, code="source_conflict", message="知识来源已登记")


class KnowledgeSourceService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._policy = AuthorizationPolicy(session)

    def _require_administrator(
        self,
        identity: IdentityContextResponse,
        project_id: UUID,
        *,
        for_update: bool,
    ) -> None:
        if for_update:
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.MANAGE,
                for_update=True,
            )
            role = authorization_repository.get_current_membership_role(
                self._session,
                org_id=identity.organization.id,
                membership_id=identity.membership.id,
                user_id=identity.user.id,
                for_update=True,
            )
        else:
            role = authorization_repository.get_current_membership_role(
                self._session,
                org_id=identity.organization.id,
                membership_id=identity.membership.id,
                user_id=identity.user.id,
            )
            if role in {MembershipRole.OWNER, MembershipRole.ADMIN}:
                fresh_identity = identity.model_copy(
                    update={"membership": identity.membership.model_copy(update={"role": role})}
                )
                self._policy.require_project(
                    fresh_identity,
                    project_id,
                    ProjectPermission.MANAGE,
                )
        if role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
            raise _not_found()

    def create_feishu_source(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        name: str,
        document_id: str,
        credential_ref: str,
        access_policy: str,
        audit: RequestAuditContext,
    ) -> KnowledgeSourceResponse:
        source = KnowledgeSource(
            org_id=identity.organization.id,
            project_id=project_id,
            provider="feishu",
            name=name,
            external_id=document_id,
            credential_ref=credential_ref,
            access_policy=access_policy,
            status="configured",
        )
        try:
            with self._session.begin():
                self._require_administrator(identity, project_id, for_update=True)
                self._session.add(source)
                self._session.flush()
                self._record_change(identity, audit, source, "knowledge.source_created")
        except IntegrityError as exc:
            if (
                isinstance(exc.orig, UniqueViolation)
                and exc.orig.diag.constraint_name == "uq_knowledge_sources_registration"
            ):
                raise _source_conflict() from exc
            raise
        return KnowledgeSourceResponse.model_validate(source)

    def list_sources(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> KnowledgeSourcePage:
        self._require_administrator(identity, project_id, for_update=False)
        sources, next_cursor = page_by_timestamp(
            self._session,
            select(KnowledgeSource).where(
                KnowledgeSource.org_id == identity.organization.id,
                KnowledgeSource.project_id == project_id,
            ),
            timestamp_column=KnowledgeSource.created_at,
            id_column=KnowledgeSource.id,
            cursor=cursor,
            limit=limit,
        )
        return KnowledgeSourcePage(
            items=[KnowledgeSourceResponse.model_validate(source) for source in sources],
            next_cursor=next_cursor,
        )

    def get_source(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        source_id: UUID,
    ) -> KnowledgeSourceResponse:
        self._require_administrator(identity, project_id, for_update=False)
        source = self._find(identity, project_id, source_id)
        if source is None:
            raise _not_found()
        return KnowledgeSourceResponse.model_validate(source)

    def disable_source(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        source_id: UUID,
        audit: RequestAuditContext,
    ) -> None:
        with self._session.begin():
            self._require_administrator(identity, project_id, for_update=True)
            source = self._session.scalar(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.org_id == identity.organization.id,
                    KnowledgeSource.project_id == project_id,
                    KnowledgeSource.id == source_id,
                )
                .with_for_update()
            )
            if source is None:
                raise _not_found()
            if source.status == "disabled":
                return
            now = datetime.now(UTC)
            source.status = "disabled"
            source.disabled_at = now
            source.updated_at = now
            self._session.flush()
            self._record_change(identity, audit, source, "knowledge.source_disabled")

    def queue_sync(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        source_id: UUID,
        audit: RequestAuditContext,
    ) -> KnowledgeSourceSyncResponse:
        with self._session.begin():
            self._require_administrator(identity, project_id, for_update=True)
            source = self._session.scalar(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.org_id == identity.organization.id,
                    KnowledgeSource.project_id == project_id,
                    KnowledgeSource.id == source_id,
                )
                .with_for_update()
            )
            if source is None or source.status != "configured":
                raise _not_found()
            existing = self._session.execute(
                select(KnowledgeSourceSync, IngestionJob)
                .join(
                    IngestionJob,
                    (IngestionJob.org_id == KnowledgeSourceSync.org_id)
                    & (IngestionJob.project_id == KnowledgeSourceSync.project_id)
                    & (IngestionJob.target_id == KnowledgeSourceSync.id)
                    & (IngestionJob.job_kind == JobKind.SYNC_FEISHU_SOURCE),
                )
                .where(
                    KnowledgeSourceSync.org_id == identity.organization.id,
                    KnowledgeSourceSync.project_id == project_id,
                    KnowledgeSourceSync.source_id == source_id,
                    IngestionJob.status.in_([IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING]),
                )
                .order_by(KnowledgeSourceSync.created_at.desc(), KnowledgeSourceSync.id.desc())
                .limit(1)
            ).one_or_none()
            if existing is not None:
                return self._sync_response(*existing)
            sync = KnowledgeSourceSync(
                org_id=identity.organization.id,
                project_id=project_id,
                source_id=source_id,
                requested_by=identity.user.id,
            )
            self._session.add(sync)
            self._session.flush()
            job = IngestionJob(
                org_id=identity.organization.id,
                project_id=project_id,
                job_kind=JobKind.SYNC_FEISHU_SOURCE,
                target_id=sync.id,
                profile_version="feishu-sync-v1",
            )
            self._session.add(job)
            self._session.flush()
            details: dict[str, object] = {
                "projectId": str(project_id),
                "sourceId": str(source.id),
                "syncId": str(sync.id),
                "jobId": str(job.id),
            }
            add_audit_log(
                self._session,
                org_id=identity.organization.id,
                actor_type="user",
                actor_id=identity.user.id,
                action="knowledge.source_sync_queued",
                resource_type="knowledge_source_sync",
                resource_id=sync.id,
                trace_id=audit.trace_id,
                ip=audit.ip,
                user_agent=audit.user_agent,
                details=details,
            )
            self._session.add(
                OutboxEvent(
                    org_id=identity.organization.id,
                    event_type="knowledge.source_sync_queued",
                    aggregate_type="project",
                    aggregate_id=project_id,
                    payload=details,
                )
            )
            return self._sync_response(sync, job)

    def get_sync(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        source_id: UUID,
        sync_id: UUID,
    ) -> KnowledgeSourceSyncResponse:
        self._require_administrator(identity, project_id, for_update=False)
        row = self._session.execute(
            select(KnowledgeSourceSync, IngestionJob)
            .join(
                IngestionJob,
                (IngestionJob.org_id == KnowledgeSourceSync.org_id)
                & (IngestionJob.project_id == KnowledgeSourceSync.project_id)
                & (IngestionJob.target_id == KnowledgeSourceSync.id)
                & (IngestionJob.job_kind == JobKind.SYNC_FEISHU_SOURCE),
            )
            .where(
                KnowledgeSourceSync.org_id == identity.organization.id,
                KnowledgeSourceSync.project_id == project_id,
                KnowledgeSourceSync.source_id == source_id,
                KnowledgeSourceSync.id == sync_id,
            )
        ).one_or_none()
        if row is None:
            raise _not_found()
        return self._sync_response(*row)

    @staticmethod
    def _sync_response(sync: KnowledgeSourceSync, job: IngestionJob) -> KnowledgeSourceSyncResponse:
        return KnowledgeSourceSyncResponse.model_validate(
            {
                "id": sync.id,
                "project_id": sync.project_id,
                "source_id": sync.source_id,
                "status": job.status,
                "attempt": job.attempt,
                "created_at": sync.created_at,
                "completed_at": job.completed_at,
                "error_code": job.last_error_code,
                "resource_id": sync.resource_id,
                "resource_version_id": sync.resource_version_id,
            }
        )

    def _find(
        self, identity: IdentityContextResponse, project_id: UUID, source_id: UUID
    ) -> KnowledgeSource | None:
        return self._session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.org_id == identity.organization.id,
                KnowledgeSource.project_id == project_id,
                KnowledgeSource.id == source_id,
            )
        )

    def _record_change(
        self,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        source: KnowledgeSource,
        event_type: str,
    ) -> None:
        add_audit_log(
            self._session,
            org_id=identity.organization.id,
            actor_type="user",
            actor_id=identity.user.id,
            action=event_type,
            resource_type="knowledge_source",
            resource_id=source.id,
            trace_id=audit.trace_id,
            ip=audit.ip,
            user_agent=audit.user_agent,
        )
        self._session.add(
            OutboxEvent(
                org_id=identity.organization.id,
                event_type=event_type,
                aggregate_type="project",
                aggregate_id=source.project_id,
                payload={
                    "sourceId": str(source.id),
                    "projectId": str(source.project_id),
                    "provider": source.provider,
                    "status": source.status,
                    "accessPolicy": source.access_policy,
                },
            )
        )


__all__ = ["KnowledgeSourceService"]
