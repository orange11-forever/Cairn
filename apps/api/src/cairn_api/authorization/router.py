from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.orm import Session

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity, get_audit_context
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.schemas import AclEntryResponse, AclGrantRequest, AclPage
from cairn_api.authorization.service import ProjectAclService
from cairn_api.db.session import get_db
from cairn_api.errors import ErrorBody
from cairn_api.pagination import load_cursor_page

router = APIRouter(prefix="/api/v1", tags=["authorization"])
SessionDependency = Annotated[Session, Depends(get_db)]
AuditContext = Annotated[RequestAuditContext, Depends(get_audit_context)]
Cursor = Annotated[str | None, Query(max_length=2048)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PrincipalTypePath = Annotated[str, Path(min_length=1, max_length=16)]
PrincipalIdPath = Annotated[str, Path(min_length=1, max_length=64)]

AUTHENTICATED_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "会话无效", "model": ErrorBody},
    422: {"description": "请求参数无效", "model": ErrorBody},
    503: {"description": "数据库暂时不可用", "model": ErrorBody},
}
MUTATION_ERRORS: dict[int | str, dict[str, Any]] = {
    **AUTHENTICATED_ERRORS,
    403: {"description": "请求来源或 CSRF 令牌无效", "model": ErrorBody},
}


@router.get(
    "/projects/{project_id}/acl",
    response_model=AclPage,
    responses={
        **AUTHENTICATED_ERRORS,
        404: {"description": "项目不存在", "model": ErrorBody},
    },
)
def list_project_acl(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> AclPage:
    return load_cursor_page(
        lambda: ProjectAclService(session).list_acl(
            identity=identity,
            project_id=project_id,
            cursor=cursor,
            limit=limit,
        )
    )


@router.put(
    "/projects/{project_id}/acl/{principal_type}/{principal_id}",
    response_model=AclEntryResponse,
    responses={
        **MUTATION_ERRORS,
        404: {"description": "项目不存在", "model": ErrorBody},
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def set_project_acl(
    project_id: UUID,
    principal_type: PrincipalTypePath,
    principal_id: PrincipalIdPath,
    payload: AclGrantRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> AclEntryResponse:
    return ProjectAclService(session).set_acl(
        identity=identity,
        project_id=project_id,
        principal_type=principal_type,
        principal_id=principal_id,
        permission=payload.permission,
        audit=audit,
    )


@router.delete(
    "/projects/{project_id}/acl/{principal_type}/{principal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **MUTATION_ERRORS,
        404: {"description": "项目不存在", "model": ErrorBody},
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def revoke_project_acl(
    project_id: UUID,
    principal_type: PrincipalTypePath,
    principal_id: PrincipalIdPath,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> Response:
    ProjectAclService(session).revoke_acl(
        identity=identity,
        project_id=project_id,
        principal_type=principal_type,
        principal_id=principal_id,
        audit=audit,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
