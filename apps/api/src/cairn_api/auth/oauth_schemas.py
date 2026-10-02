from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["github", "feishu"]


class OAuthStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    intent: Literal["login", "link"]
    return_to: Literal["/projects", "/account/identities"] = Field(
        default="/projects", alias="returnTo"
    )


class OAuthStartResponse(BaseModel):
    authorization_url: str = Field(serialization_alias="authorizationUrl")


class OAuthProviderResponse(BaseModel):
    provider: ProviderName
    enabled: bool


class LinkedIdentityResponse(BaseModel):
    id: UUID
    provider: ProviderName
    display_name: str | None = Field(serialization_alias="displayName")
    created_at: datetime = Field(serialization_alias="createdAt")


class LinkedIdentitiesResponse(BaseModel):
    identities: list[LinkedIdentityResponse]
    password_available: bool = Field(serialization_alias="passwordAvailable")
