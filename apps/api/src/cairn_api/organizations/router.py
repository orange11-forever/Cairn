from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity, get_audit_context
from cairn_api.auth.service import RequestAuditContext
from cairn_api.db.session import get_db
from cairn_api.errors import ApiProblem, ErrorBody
from cairn_api.organizations.schemas import (
    MembershipDetailResponse,
    MembershipPage,
    MembershipRoleUpdateRequest,
    OrganizationResponse,
)
from cairn_api.organizations.service import OrganizationService
from cairn_api.pagination import load_cursor_page

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])
SessionDependency = Annotated[Session, Depends(get_db)]
AuditContext = Annotated[RequestAuditContext, Depends(get_audit_context)]
Cursor = Annotated[str | None, Query(max_length=2048)]
PageLimit = Annotated[int, Query(ge=1, le=100)]

IDENTITY_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "会话无效", "model": ErrorBody},
    422: {"description": "请求参数无效", "model": ErrorBody},
    503: {"description": "数据库暂时不可用", "model": ErrorBody},
}
AUTHENTICATED_ERRORS: dict[int | str, dict[str, Any]] = {
    **IDENTITY_ERRORS,
    403: {"description": "没有执行该操作的权限", "model": ErrorBody},
}
MUTATION_ERRORS: dict[int | str, dict[str, Any]] = {
    **AUTHENTICATED_ERRORS,
    404: {"description": "成员或组织不存在", "model": ErrorBody},
    409: {"description": "组织必须保留至少一名所有者", "model": ErrorBody},
}


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    responses={
        **IDENTITY_ERRORS,
        404: {"description": "组织不存在", "model": ErrorBody},
    },
)
def get_organization(
    organization_id: UUID,
    identity: CurrentIdentity,
) -> OrganizationResponse:
    if organization_id != identity.organization.id:
        raise ApiProblem(
            status_code=404,
            code="not_found",
            message="请求的资源不存在",
        )
    return identity.organization


@router.get(
    "/{organization_id}/memberships",
    response_model=MembershipPage,
    responses={
        **AUTHENTICATED_ERRORS,
        404: {"description": "组织不存在", "model": ErrorBody},
    },
)
def list_memberships(
    organization_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> MembershipPage:
    return load_cursor_page(
        lambda: OrganizationService(session).list_memberships(
            identity=identity,
            organization_id=organization_id,
            cursor=cursor,
            limit=limit,
        )
    )


@router.patch(
    "/{organization_id}/memberships/{membership_id}",
    response_model=MembershipDetailResponse,
    responses=MUTATION_ERRORS,
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def update_membership_role(
    organization_id: UUID,
    membership_id: UUID,
    payload: MembershipRoleUpdateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> MembershipDetailResponse:
    return OrganizationService(session).update_membership_role(
        identity=identity,
        organization_id=organization_id,
        membership_id=membership_id,
        requested_role=payload.role,
        audit=audit,
    )
