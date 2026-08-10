from uuid import UUID

from pydantic import BaseModel

from cairn_api.authorization.types import MembershipRole


class OrganizationResponse(BaseModel):
    id: UUID
    slug: str
    name: str


class MembershipResponse(BaseModel):
    id: UUID
    role: MembershipRole
