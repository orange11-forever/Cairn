from datetime import UTC, datetime, timedelta
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
from cairn_api.knowledge.models import IngestionJob, JobKind, KnowledgeResourceVersion
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.knowledge.source_schemas import (
    FeishuSourcePatchRequest,
    KnowledgeSourcePage,
    KnowledgeSourceResponse,
    KnowledgeSourceSyncPage,
    KnowledgeSourceSyncResponse,
)
from cairn_api.knowledge.source_sync_queue import queue_locked_source_sync
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
        sync_interval_seconds: int | None,
        audit: RequestAuditContext,
    ) -> KnowledgeSourceResponse:
        now = datetime.now(UTC)
        source = KnowledgeSource(
            org_id=identity.organization.id,
            project_id=project_id,
            provider="feishu",
            name=name,
            external_id=document_id,
            credential_ref=credential_ref,
            access_policy=access_policy,
            status="configured",
            access_state="unverified",
            sync_interval_seconds=sync_interval_seconds,
            next_sync_at=now + timedelta(seconds=sync_interval_seconds) if sync_interval_seconds is not None else None,
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
            source.next_sync_at = None
            source.generation += 1
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
            sync, job = queue_locked_source_sync(
                self._session, source=source, trigger="manual", requested_by=identity.user.id,
                trace_id=audit.trace_id, ip=audit.ip, user_agent=audit.user_agent,
            )
            return self._sync_response(sync, job)

    def patch_source(
        self, *, identity: IdentityContextResponse, project_id: UUID, source_id: UUID,
        payload: FeishuSourcePatchRequest, audit: RequestAuditContext,
    ) -> KnowledgeSourceResponse:
        try:
            with self._session.begin():
                self._require_administrator(identity, project_id, for_update=True)
                source = self._session.scalar(
                    select(KnowledgeSource).where(
                        KnowledgeSource.org_id == identity.organization.id,
                        KnowledgeSource.project_id == project_id,
                        KnowledgeSource.id == source_id,
                    ).with_for_update()
                )
                if source is None:
                    raise _not_found()
                fields = payload.model_fields_set
                now = datetime.now(UTC)
                changed = False
                lifecycle = False
                if "name" in fields and source.name != payload.name:
                    source.name = payload.name or source.name
                    changed = True
                if "credential_ref" in fields and source.credential_ref != payload.credential_ref:
                    if payload.access_policy != "project_members":
                        raise ApiProblem(status_code=422, code="validation_error", message="必须确认项目成员共享")
                    source.credential_ref = payload.credential_ref or source.credential_ref
                    lifecycle = changed = True
                if "status" in fields and source.status != payload.status:
                    if payload.status == "configured" and payload.access_policy != "project_members":
                        raise ApiProblem(status_code=422, code="validation_error", message="必须确认项目成员共享")
                    source.status = payload.status or source.status
                    source.disabled_at = now if source.status == "disabled" else None
                    lifecycle = changed = True
                if "sync_interval_seconds" in fields and source.sync_interval_seconds != payload.sync_interval_seconds:
                    source.sync_interval_seconds = payload.sync_interval_seconds
                    changed = True
                if lifecycle:
                    source.generation += 1
                    source.access_state = "unverified"
                    source.last_error_code = None
                if changed:
                    source.next_sync_at = (
                        now + timedelta(seconds=source.sync_interval_seconds)
                        if source.status == "configured" and source.sync_interval_seconds is not None
                        else None
                    )
                    source.updated_at = now
                    self._session.flush()
                    self._record_change(identity, audit, source, "knowledge.source_updated")
            return KnowledgeSourceResponse.model_validate(source)
        except IntegrityError as exc:
            if isinstance(exc.orig, UniqueViolation) and exc.orig.diag.constraint_name == "uq_knowledge_sources_registration":
                raise _source_conflict() from exc
            raise

    def list_syncs(
        self, *, identity: IdentityContextResponse, project_id: UUID, source_id: UUID,
        cursor: str | None, limit: int,
    ) -> KnowledgeSourceSyncPage:
        self._require_administrator(identity, project_id, for_update=False)
        if self._find(identity, project_id, source_id) is None:
            raise _not_found()
        syncs, next_cursor = page_by_timestamp(
            self._session,
            select(KnowledgeSourceSync).where(
                KnowledgeSourceSync.org_id == identity.organization.id,
                KnowledgeSourceSync.project_id == project_id,
                KnowledgeSourceSync.source_id == source_id,
            ),
            timestamp_column=KnowledgeSourceSync.created_at,
            id_column=KnowledgeSourceSync.id,
            cursor=cursor, limit=limit, descending=True,
        )
        if not syncs:
            return KnowledgeSourceSyncPage(items=[], next_cursor=next_cursor)
        jobs = {
            job.target_id: job for job in self._session.scalars(
                select(IngestionJob).where(IngestionJob.org_id == identity.organization.id,
                    IngestionJob.project_id == project_id, IngestionJob.job_kind == JobKind.SYNC_FEISHU_SOURCE,
                    IngestionJob.target_id.in_([sync.id for sync in syncs]))
            )
        }
        return KnowledgeSourceSyncPage(items=[self._sync_response(sync, jobs[sync.id]) for sync in syncs], next_cursor=next_cursor)

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

    def _sync_response(self, sync: KnowledgeSourceSync, job: IngestionJob) -> KnowledgeSourceSyncResponse:
        version = self._session.get(KnowledgeResourceVersion, sync.resource_version_id) if sync.resource_version_id is not None else None
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
                "trigger": sync.trigger,
                "failure_code": sync.failure_code,
                "next_attempt_at": job.next_attempt_at if job.status == "queued" and job.attempt > 0 else None,
                "resource_status": version.status if version is not None else None,
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
