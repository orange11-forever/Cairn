from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field

from cairn_api.authorization.types import MembershipRole


class OrganizationResponse(BaseModel):
    id: UUID
    slug: str
    name: str


class MembershipResponse(BaseModel):
    id: UUID
    role: MembershipRole


class MembershipDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    user_id: UUID = Field(serialization_alias="userId")
    email: EmailStr
    display_name: str = Field(serialization_alias="displayName")
    role: MembershipRole
    created_at: AwareDatetime = Field(serialization_alias="createdAt")


class MembershipPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[MembershipDetailResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class MembershipRoleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: MembershipRole
