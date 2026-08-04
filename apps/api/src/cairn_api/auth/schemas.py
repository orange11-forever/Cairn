from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    email: str
    display_name: str | None = Field(serialization_alias="displayName")


class IdentityContextResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user: UserResponse
    organization: OrganizationResponse
    membership: MembershipResponse
    csrf_token: str = Field(serialization_alias="csrfToken")
