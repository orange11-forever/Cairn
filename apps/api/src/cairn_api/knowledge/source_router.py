from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity, get_audit_context
from cairn_api.auth.service import RequestAuditContext
from cairn_api.db.session import get_db
from cairn_api.errors import ErrorBody
from cairn_api.knowledge.source_schemas import (
    FeishuSourceCreateRequest,
    KnowledgeSourcePage,
    KnowledgeSourceResponse,
    KnowledgeSourceSyncCreateRequest,
    KnowledgeSourceSyncResponse,
)
from cairn_api.knowledge.source_service import KnowledgeSourceService
from cairn_api.pagination import load_cursor_page

router = APIRouter(prefix="/api/v1", tags=["knowledge-sources"])
SessionDependency = Annotated[Session, Depends(get_db)]
AuditContext = Annotated[RequestAuditContext, Depends(get_audit_context)]
Cursor = Annotated[str | None, Query(max_length=2048)]
PageLimit = Annotated[int, Query(ge=1, le=100)]

RESPONSE_HEADERS = {
    "X-Request-ID": {"description": "请求追踪标识", "schema": {"type": "string"}},
    "Cache-Control": {
        "description": "防止受保护知识响应被浏览器或中间缓存保存",
        "schema": {"type": "string", "const": "private, no-store"},
    },
}


def _error(description: str) -> dict[str, Any]:
    return {"description": description, "model": ErrorBody, "headers": RESPONSE_HEADERS}


def _method_error() -> dict[str, Any]:
    error = _error("请求方法不被允许")
    error["headers"] = {
        **RESPONSE_HEADERS,
        "Allow": {"description": "该资源支持的 HTTP 方法", "schema": {"type": "string"}},
    }
    return error


READ_ERRORS: dict[int | str, dict[str, Any]] = {
    401: _error("会话无效"),
    404: _error("项目或知识来源不存在"),
    405: _method_error(),
    422: _error("请求参数无效"),
    500: _error("服务器内部错误"),
    503: _error("数据库暂时不可用"),
}
MUTATION_ERRORS: dict[int | str, dict[str, Any]] = {
    **READ_ERRORS,
    403: _error("请求来源或 CSRF 令牌无效"),
}


@router.post(
    "/projects/{project_id}/knowledge/sources/feishu",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "飞书知识来源已登记", "headers": RESPONSE_HEADERS},
        **MUTATION_ERRORS,
        409: _error("知识来源已登记"),
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def create_feishu_source(
    project_id: UUID,
    payload: FeishuSourceCreateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> KnowledgeSourceResponse:
    return KnowledgeSourceService(session).create_feishu_source(
        identity=identity,
        project_id=project_id,
        name=payload.name,
        document_id=payload.document_id,
        credential_ref=payload.credential_ref,
        access_policy=payload.access_policy,
        audit=audit,
    )


@router.get(
    "/projects/{project_id}/knowledge/sources",
    response_model=KnowledgeSourcePage,
    responses={200: {"description": "知识来源分页", "headers": RESPONSE_HEADERS}, **READ_ERRORS},
)
def list_sources(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> KnowledgeSourcePage:
    return load_cursor_page(
        lambda: KnowledgeSourceService(session).list_sources(
            identity=identity,
            project_id=project_id,
            cursor=cursor,
            limit=limit,
        )
    )


@router.get(
    "/projects/{project_id}/knowledge/sources/{source_id}",
    response_model=KnowledgeSourceResponse,
    responses={200: {"description": "知识来源详情", "headers": RESPONSE_HEADERS}, **READ_ERRORS},
)
def get_source(
    project_id: UUID,
    source_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
) -> KnowledgeSourceResponse:
    return KnowledgeSourceService(session).get_source(
        identity=identity,
        project_id=project_id,
        source_id=source_id,
    )


@router.delete(
    "/projects/{project_id}/knowledge/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={204: {"description": "知识来源已停用", "headers": RESPONSE_HEADERS}, **MUTATION_ERRORS},
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def disable_source(
    project_id: UUID,
    source_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> Response:
    KnowledgeSourceService(session).disable_source(
        identity=identity,
        project_id=project_id,
        source_id=source_id,
        audit=audit,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/knowledge/sources/{source_id}/syncs",
    response_model=KnowledgeSourceSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={202: {"description": "飞书来源同步已排队", "headers": RESPONSE_HEADERS}, **MUTATION_ERRORS},
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def queue_source_sync(
    project_id: UUID,
    source_id: UUID,
    payload: KnowledgeSourceSyncCreateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> KnowledgeSourceSyncResponse:
    del payload
    return KnowledgeSourceService(session).queue_sync(
        identity=identity,
        project_id=project_id,
        source_id=source_id,
        audit=audit,
    )


@router.get(
    "/projects/{project_id}/knowledge/sources/{source_id}/syncs/{sync_id}",
    response_model=KnowledgeSourceSyncResponse,
    responses={200: {"description": "飞书来源同步状态", "headers": RESPONSE_HEADERS}, **READ_ERRORS},
)
def get_source_sync(
    project_id: UUID,
    source_id: UUID,
    sync_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
) -> KnowledgeSourceSyncResponse:
    return KnowledgeSourceService(session).get_sync(
        identity=identity,
        project_id=project_id,
        source_id=source_id,
        sync_id=sync_id,
    )


__all__ = ["router"]
