from uuid import UUID

from pydantic import BaseModel


class OrganizationResponse(BaseModel):
    id: UUID
    slug: str
    name: str


class MembershipResponse(BaseModel):
    id: UUID
    role: str
