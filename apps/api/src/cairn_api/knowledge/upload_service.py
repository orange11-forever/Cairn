import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import repository
from cairn_api.knowledge.media import MediaDescriptor, MediaValidationError, validate_upload_intent
from cairn_api.knowledge.models import IngestionItemStatus, JobKind
from cairn_api.knowledge.object_store import (
    ObjectNotFound,
    ObjectStat,
    ObjectStore,
    ObjectStoreUnavailable,
    PresignedPut,
)
from cairn_api.knowledge.schemas import (
    UploadBatchCreateResponse,
    UploadCompleteResponse,
    UploadFileIntent,
    UploadInstruction,
)


def _not_found() -> ApiProblem:
    return ApiProblem(status_code=404, code="not_found", message="资源不存在")


def _object_store_unavailable() -> ApiProblem:
    return ApiProblem(
        status_code=503,
        code="object_store_unavailable",
        message="对象存储暂时不可用",
    )


def _media_problem(error: MediaValidationError) -> ApiProblem:
    messages = {
        "unsupported_media_type": "文件类型不受支持",
        "upload_media_type_mismatch": "文件类型声明不匹配",
        "file_too_large": "文件大小超出限制",
    }
    return ApiProblem(
        status_code=422,
        code=error.code,
        message=messages.get(error.code, "上传文件无效"),
    )


def _completion_problem(code: str) -> ApiProblem:
    if code == "upload_expired":
        return ApiProblem(status_code=410, code=code, message="上传会话已过期")
    messages = {
        "upload_object_missing": "上传对象不存在",
        "upload_size_mismatch": "上传对象大小不匹配",
        "upload_checksum_mismatch": "上传对象校验和不匹配",
        "upload_media_type_mismatch": "上传对象媒体类型不匹配",
    }
    return ApiProblem(
        status_code=409,
        code=code,
        message=messages.get(code, "上传对象校验失败"),
    )


def _normalized_name(file_name: str) -> str:
    return unicodedata.normalize("NFC", file_name)


def _duplicate_key(file_name: str) -> str:
    return _normalized_name(file_name).casefold()


@dataclass(frozen=True)
class _PreparedUpload:
    intent: UploadFileIntent
    descriptor: MediaDescriptor
    normalized_path: str
    object_key: str
    signed: PresignedPut


class KnowledgeUploadService:
    def __init__(
        self,
        session: Session,
        object_store: ObjectStore,
        *,
        policy: AuthorizationPolicy | None = None,
        now: Callable[[], datetime] | None = None,
        upload_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        if upload_ttl <= timedelta(0):
            raise ValueError("upload_ttl must be positive")
        self._session = session
        self._object_store = object_store
        self._policy = policy or AuthorizationPolicy(session)
        self._now = now or (lambda: datetime.now(UTC))
        self._upload_ttl = upload_ttl

    def create_batch(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        files: Sequence[UploadFileIntent],
        audit: RequestAuditContext,
    ) -> UploadBatchCreateResponse:
        org_id = identity.organization.id
        instructions: list[UploadInstruction] = []
        try:
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.WRITE,
            )
            validated = self._validate_files(files)
            prepared = [
                self._prepare_upload(
                    org_id=org_id,
                    project_id=project_id,
                    intent=intent,
                    descriptor=descriptor,
                    normalized_path=normalized_path,
                )
                for intent, descriptor, normalized_path in validated
            ]
        except ObjectStoreUnavailable:
            raise _object_store_unavailable() from None
        finally:
            # Authorization reads auto-begin a SQLAlchemy transaction. End that
            # read boundary before acquiring mutation locks and writing rows.
            self._session.rollback()

        with self._session.begin():
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.WRITE,
                for_update=True,
            )
            batch = repository.create_batch(
                self._session,
                org_id=org_id,
                project_id=project_id,
                created_by=identity.user.id,
                item_count=len(prepared),
            )
            for prepared_upload in prepared:
                record = repository.create_upload_session(
                    self._session,
                    org_id=org_id,
                    project_id=project_id,
                    batch_id=batch.id,
                    file_name=prepared_upload.intent.file_name,
                    normalized_path=prepared_upload.normalized_path,
                    media_type=prepared_upload.descriptor.media_type,
                    size_bytes=prepared_upload.intent.size_bytes,
                    sha256=prepared_upload.intent.sha256,
                    object_key=prepared_upload.object_key,
                    expires_at=prepared_upload.signed.expires_at,
                )
                instructions.append(
                    UploadInstruction(
                        upload_id=record.upload.id,
                        item_id=record.item.id,
                        url=prepared_upload.signed.url,
                        headers=prepared_upload.signed.headers,
                        expires_at=prepared_upload.signed.expires_at,
                    )
                )
            self._audit(
                identity=identity,
                audit=audit,
                action="knowledge.upload_batch_created",
                resource_type="ingestion_batch",
                resource_id=batch.id,
                details={"projectId": str(project_id), "itemCount": len(prepared)},
            )
            repository.add_project_outbox_event(
                self._session,
                org_id=org_id,
                project_id=project_id,
                event_type="knowledge.upload_batch_created",
                payload={
                    "projectId": str(project_id),
                    "batchId": str(batch.id),
                    "itemCount": len(prepared),
                },
            )
        return UploadBatchCreateResponse(batch_id=batch.id, uploads=instructions)

    def _prepare_upload(
        self,
        *,
        org_id: UUID,
        project_id: UUID,
        intent: UploadFileIntent,
        descriptor: MediaDescriptor,
        normalized_path: str,
    ) -> _PreparedUpload:
        object_key = f"orgs/{org_id}/projects/{project_id}/uploads/{uuid4().hex}"
        signed = self._object_store.presign_put(
            object_key=object_key,
            content_type=descriptor.media_type,
            checksum_sha256=intent.sha256,
            expires_in=self._upload_ttl,
        )
        return _PreparedUpload(
            intent=intent,
            descriptor=descriptor,
            normalized_path=normalized_path,
            object_key=object_key,
            signed=signed,
        )

    def complete_upload(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        upload_id: UUID,
        audit: RequestAuditContext,
    ) -> UploadCompleteResponse:
        org_id = identity.organization.id
        problem: ApiProblem | None = None
        response: UploadCompleteResponse | None = None
        with self._session.begin():
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.WRITE,
                for_update=True,
            )
            record = repository.get_upload_for_update(
                self._session,
                org_id=org_id,
                project_id=project_id,
                upload_id=upload_id,
            )
            if record is None:
                raise _not_found()
            upload = record.upload
            item = record.item
            if upload.completed_at is not None:
                return self._completion_response(record)
            if upload.abandoned_at is not None:
                raise _completion_problem(item.error_code or "upload_expired")

            now = self._now()
            if now >= upload.expires_at:
                problem = _completion_problem("upload_expired")
            else:
                try:
                    object_stat = self._object_store.stat(object_key=upload.object_key)
                except ObjectNotFound:
                    problem = _completion_problem("upload_object_missing")
                except ObjectStoreUnavailable:
                    raise _object_store_unavailable() from None
                else:
                    mismatch = self._object_mismatch(record, object_stat)
                    if mismatch is not None:
                        problem = _completion_problem(mismatch)

            if problem is not None:
                self._record_failure(
                    identity=identity,
                    audit=audit,
                    record=record,
                    error_code=problem.code,
                    failed_at=now,
                )
            else:
                response = self._record_completion(
                    identity=identity,
                    audit=audit,
                    record=record,
                    completed_at=now,
                )
        if problem is not None:
            raise problem
        if response is None:
            raise RuntimeError("upload completion produced no result")
        return response

    def _validate_files(
        self,
        files: Sequence[UploadFileIntent],
    ) -> list[tuple[UploadFileIntent, MediaDescriptor, str]]:
        if not 1 <= len(files) <= 20:
            raise ApiProblem(
                status_code=422,
                code="invalid_upload_count",
                message="一次必须上传 1 至 20 个文件",
            )
        validated: list[tuple[UploadFileIntent, MediaDescriptor, str]] = []
        seen_names: set[str] = set()
        for intent in files:
            normalized_path = _normalized_name(intent.file_name)
            duplicate_key = _duplicate_key(intent.file_name)
            if duplicate_key in seen_names:
                raise ApiProblem(
                    status_code=422,
                    code="duplicate_file_name",
                    message="同一批次包含重复文件名",
                )
            seen_names.add(duplicate_key)
            try:
                descriptor = validate_upload_intent(
                    file_name=normalized_path,
                    declared_media_type=intent.media_type,
                    size_bytes=intent.size_bytes,
                )
            except MediaValidationError as error:
                raise _media_problem(error) from None
            validated.append((intent, descriptor, normalized_path))
        return validated

    @staticmethod
    def _object_mismatch(
        record: repository.UploadRecord,
        object_stat: ObjectStat,
    ) -> str | None:
        upload = record.upload
        if object_stat.size_bytes != upload.size_bytes:
            return "upload_size_mismatch"
        if object_stat.checksum_sha256 != upload.sha256:
            return "upload_checksum_mismatch"
        content_type = (
            object_stat.content_type.partition(";")[0].strip().lower()
            if object_stat.content_type is not None
            else None
        )
        if content_type != upload.declared_media_type:
            return "upload_media_type_mismatch"
        return None

    def _record_completion(
        self,
        *,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        record: repository.UploadRecord,
        completed_at: datetime,
    ) -> UploadCompleteResponse:
        upload = record.upload
        item = record.item
        org_id = identity.organization.id
        descriptor = validate_upload_intent(
            file_name=upload.original_file_name,
            declared_media_type=upload.declared_media_type,
            size_bytes=upload.size_bytes,
        )
        resource = None
        version = None
        if descriptor.is_archive:
            job_kind = JobKind.EXPAND_ARCHIVE
            target_id = item.id
        else:
            resource, version = repository.create_resource_with_version(
                self._session,
                org_id=org_id,
                project_id=upload.project_id,
                upload=upload,
                item=item,
                created_by=identity.user.id,
            )
            job_kind = JobKind.INDEX_RESOURCE_VERSION
            target_id = version.id
        repository.create_ingestion_job(
            self._session,
            org_id=org_id,
            project_id=upload.project_id,
            job_kind=job_kind,
            target_id=target_id,
            next_attempt_at=completed_at,
        )
        repository.mark_upload_complete(
            self._session,
            org_id=org_id,
            project_id=upload.project_id,
            upload=upload,
            item=item,
            completed_at=completed_at,
            resource=resource,
            version=version,
        )
        repository.refresh_batch_summary(
            self._session,
            org_id=org_id,
            project_id=upload.project_id,
            batch_id=upload.batch_id,
            now=completed_at,
        )
        self._audit(
            identity=identity,
            audit=audit,
            action="knowledge.upload_completed",
            resource_type="upload_session",
            resource_id=upload.id,
            details={
                "projectId": str(upload.project_id),
                "batchId": str(upload.batch_id),
                "itemId": str(item.id),
                "jobKind": job_kind.value,
            },
        )
        repository.add_project_outbox_event(
            self._session,
            org_id=org_id,
            project_id=upload.project_id,
            event_type="knowledge.upload_completed",
            payload={
                "projectId": str(upload.project_id),
                "batchId": str(upload.batch_id),
                "uploadId": str(upload.id),
                "itemId": str(item.id),
                "resourceId": str(resource.id) if resource is not None else None,
                "resourceVersionId": str(version.id) if version is not None else None,
                "status": IngestionItemStatus.QUEUED.value,
            },
        )
        return self._completion_response(record)

    def _record_failure(
        self,
        *,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        record: repository.UploadRecord,
        error_code: str,
        failed_at: datetime,
    ) -> None:
        upload = record.upload
        item = record.item
        org_id = identity.organization.id
        repository.mark_item_failed(
            self._session,
            org_id=org_id,
            project_id=upload.project_id,
            upload=upload,
            item=item,
            error_code=error_code,
            failed_at=failed_at,
            abandon_upload=True,
        )
        repository.refresh_batch_summary(
            self._session,
            org_id=org_id,
            project_id=upload.project_id,
            batch_id=upload.batch_id,
            now=failed_at,
        )
        self._audit(
            identity=identity,
            audit=audit,
            action="knowledge.upload_failed",
            resource_type="upload_session",
            resource_id=upload.id,
            details={
                "projectId": str(upload.project_id),
                "batchId": str(upload.batch_id),
                "itemId": str(item.id),
                "errorCode": error_code,
            },
        )
        repository.add_project_outbox_event(
            self._session,
            org_id=org_id,
            project_id=upload.project_id,
            event_type="knowledge.upload_failed",
            payload={
                "projectId": str(upload.project_id),
                "batchId": str(upload.batch_id),
                "uploadId": str(upload.id),
                "itemId": str(item.id),
                "status": IngestionItemStatus.FAILED.value,
                "errorCode": error_code,
            },
        )

    @staticmethod
    def _completion_response(record: repository.UploadRecord) -> UploadCompleteResponse:
        return UploadCompleteResponse(
            upload_id=record.upload.id,
            batch_id=record.upload.batch_id,
            item_id=record.item.id,
            resource_id=record.item.resource_id,
            resource_version_id=record.item.resource_version_id,
            status=IngestionItemStatus(record.item.status),
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


__all__ = ["KnowledgeUploadService"]
