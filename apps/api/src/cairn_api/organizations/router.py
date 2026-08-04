from uuid import UUID

from fastapi import APIRouter

from cairn_api.auth.dependencies import CurrentIdentity
from cairn_api.errors import ApiProblem
from cairn_api.organizations.schemas import OrganizationResponse

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


@router.get("/{organization_id}", response_model=OrganizationResponse)
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
