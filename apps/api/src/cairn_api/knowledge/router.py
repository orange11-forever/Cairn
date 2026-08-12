from datetime import timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse, Response

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
from cairn_api.knowledge.resource_service import KnowledgeResourceService
from cairn_api.knowledge.schemas import (
    BatchDetailResponse,
    ChunkContextResponse,
    KnowledgeResourcePage,
    KnowledgeResourceResponse,
    UploadBatchCreateRequest,
    UploadBatchCreateResponse,
    UploadCompleteResponse,
)
from cairn_api.knowledge.upload_service import KnowledgeUploadService
from cairn_api.pagination import load_cursor_page
from cairn_api.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["knowledge"])
SessionDependency = Annotated[Session, Depends(get_db)]
ObjectStoreDependency = Annotated[ObjectStore, Depends(get_object_store)]
AuditContext = Annotated[RequestAuditContext, Depends(get_audit_context)]
SettingsDependency = Annotated[Settings, Depends(get_request_settings)]
Cursor = Annotated[str | None, Query(max_length=2048)]
PageLimit = Annotated[int, Query(ge=1, le=100)]

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

RESOURCE_READ_ERRORS: dict[int | str, dict[str, Any]] = {
    401: _error("会话无效"),
    404: _error("项目或知识资源不存在"),
    422: _error("请求参数无效"),
    500: _error("服务器内部错误"),
    503: _error("数据库或对象存储暂时不可用"),
}
RESOURCE_MUTATION_ERRORS: dict[int | str, dict[str, Any]] = {
    **RESOURCE_READ_ERRORS,
    403: _error("请求来源或 CSRF 令牌无效"),
}
RESOURCE_RETRY_ERRORS: dict[int | str, dict[str, Any]] = {
    **RESOURCE_MUTATION_ERRORS,
    409: _error("知识资源状态不允许该操作"),
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


@router.get(
    "/projects/{project_id}/knowledge/batches/{batch_id}",
    response_model=BatchDetailResponse,
    responses={
        200: {"description": "知识导入批次详情", "headers": REQUEST_ID_HEADER},
        **RESOURCE_READ_ERRORS,
    },
)
def get_knowledge_batch(
    project_id: UUID,
    batch_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
) -> BatchDetailResponse:
    return KnowledgeResourceService(session, object_store).get_batch(
        identity=identity,
        project_id=project_id,
        batch_id=batch_id,
    )


@router.get(
    "/projects/{project_id}/knowledge/resources",
    response_model=KnowledgeResourcePage,
    responses={
        200: {"description": "知识资源分页", "headers": REQUEST_ID_HEADER},
        **RESOURCE_READ_ERRORS,
    },
)
def list_knowledge_resources(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> KnowledgeResourcePage:
    return load_cursor_page(
        lambda: KnowledgeResourceService(session, object_store).list_resources(
            identity=identity,
            project_id=project_id,
            cursor=cursor,
            limit=limit,
        )
    )


@router.get(
    "/projects/{project_id}/knowledge/resources/{resource_id}",
    response_model=KnowledgeResourceResponse,
    responses={
        200: {"description": "知识资源详情", "headers": REQUEST_ID_HEADER},
        **RESOURCE_READ_ERRORS,
    },
)
def get_knowledge_resource(
    project_id: UUID,
    resource_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
) -> KnowledgeResourceResponse:
    return KnowledgeResourceService(session, object_store).get_resource(
        identity=identity,
        project_id=project_id,
        resource_id=resource_id,
    )


@router.post(
    "/projects/{project_id}/knowledge/resources/{resource_id}/versions/{version_id}/retry",
    response_model=KnowledgeResourceResponse,
    responses={
        200: {"description": "知识资源版本已重新排队", "headers": REQUEST_ID_HEADER},
        **RESOURCE_RETRY_ERRORS,
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def retry_knowledge_resource_version(
    project_id: UUID,
    resource_id: UUID,
    version_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
    audit: AuditContext,
) -> KnowledgeResourceResponse:
    return KnowledgeResourceService(session, object_store).retry_version(
        identity=identity,
        project_id=project_id,
        resource_id=resource_id,
        version_id=version_id,
        audit=audit,
    )


@router.delete(
    "/projects/{project_id}/knowledge/resources/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "知识资源已删除", "headers": REQUEST_ID_HEADER},
        **RESOURCE_MUTATION_ERRORS,
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def delete_knowledge_resource(
    project_id: UUID,
    resource_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
    audit: AuditContext,
) -> Response:
    KnowledgeResourceService(session, object_store).delete_resource(
        identity=identity,
        project_id=project_id,
        resource_id=resource_id,
        audit=audit,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/knowledge/resources/{resource_id}/download",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    response_class=RedirectResponse,
    responses={
        307: {
            "description": "重定向到短期附件下载地址",
            "headers": {
                **REQUEST_ID_HEADER,
                "Location": {
                    "description": "五分钟有效的附件下载地址",
                    "schema": {"type": "string", "format": "uri"},
                },
            },
        },
        **RESOURCE_READ_ERRORS,
    },
)
def download_knowledge_resource(
    project_id: UUID,
    resource_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
    audit: AuditContext,
) -> RedirectResponse:
    url = KnowledgeResourceService(session, object_store).create_download(
        identity=identity,
        project_id=project_id,
        resource_id=resource_id,
        audit=audit,
    )
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get(
    "/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}",
    response_model=ChunkContextResponse,
    responses={
        200: {"description": "知识片段引用上下文", "headers": REQUEST_ID_HEADER},
        **RESOURCE_READ_ERRORS,
    },
)
def get_knowledge_chunk_context(
    project_id: UUID,
    resource_id: UUID,
    chunk_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    object_store: ObjectStoreDependency,
) -> ChunkContextResponse:
    return KnowledgeResourceService(session, object_store).get_chunk_context(
        identity=identity,
        project_id=project_id,
        resource_id=resource_id,
        chunk_id=chunk_id,
    )


__all__ = ["router"]
