from datetime import timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import (
    CurrentIdentity,
    get_audit_context,
    get_request_settings,
)
from cairn_api.auth.service import RequestAuditContext
from cairn_api.db.session import get_db
from cairn_api.errors import ErrorBody
from cairn_api.knowledge.dependencies import get_object_store
from cairn_api.knowledge.object_store import ObjectStore
from cairn_api.knowledge.schemas import (
    UploadBatchCreateRequest,
    UploadBatchCreateResponse,
    UploadCompleteResponse,
)
from cairn_api.knowledge.upload_service import KnowledgeUploadService
from cairn_api.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["knowledge"])
SessionDependency = Annotated[Session, Depends(get_db)]
ObjectStoreDependency = Annotated[ObjectStore, Depends(get_object_store)]
AuditContext = Annotated[RequestAuditContext, Depends(get_audit_context)]
SettingsDependency = Annotated[Settings, Depends(get_request_settings)]

REQUEST_ID_HEADER = {
    "X-Request-ID": {
        "description": "请求追踪标识",
        "schema": {"type": "string"},
    }
}


def _error(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "model": ErrorBody,
        "headers": REQUEST_ID_HEADER,
    }


UPLOAD_ERRORS: dict[int | str, dict[str, Any]] = {
    401: _error("会话无效"),
    403: _error("请求来源或 CSRF 令牌无效"),
    404: _error("项目或上传会话不存在"),
    409: _error("上传对象缺失或与声明不一致"),
    410: _error("上传会话已过期"),
    422: _error("请求参数或文件意图无效"),
    500: _error("服务器内部错误"),
    503: _error("数据库或对象存储暂时不可用"),
}


@router.post(
    "/projects/{project_id}/knowledge/uploads",
    response_model=UploadBatchCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "上传会话已创建", "headers": REQUEST_ID_HEADER},
        **UPLOAD_ERRORS,
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def create_upload_batch(
    project_id: UUID,
    payload: UploadBatchCreateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
    audit: AuditContext,
    settings: SettingsDependency,
) -> UploadBatchCreateResponse:
    return KnowledgeUploadService(
        session,
        object_store,
        upload_ttl=timedelta(seconds=settings.upload_session_ttl_seconds),
    ).create_batch(
        identity=identity,
        project_id=project_id,
        files=payload.files,
        audit=audit,
    )


@router.post(
    "/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
    response_model=UploadCompleteResponse,
    responses={
        200: {"description": "上传已确认", "headers": REQUEST_ID_HEADER},
        **UPLOAD_ERRORS,
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def complete_upload(
    project_id: UUID,
    upload_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
    audit: AuditContext,
) -> UploadCompleteResponse:
    return KnowledgeUploadService(session, object_store).complete_upload(
        identity=identity,
        project_id=project_id,
        upload_id=upload_id,
        audit=audit,
    )


__all__ = ["router"]
