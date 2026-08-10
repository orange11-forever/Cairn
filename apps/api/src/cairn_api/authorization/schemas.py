from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from cairn_api.authorization.types import (
    ActorType,
    PrincipalType,
    ProjectPermission,
    ResourceType,
)


class AclGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission: ProjectPermission


class AclEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    resource_type: ResourceType = Field(serialization_alias="resourceType")
    resource_id: UUID = Field(serialization_alias="resourceId")
    principal_type: PrincipalType = Field(serialization_alias="principalType")
    principal_id: str = Field(serialization_alias="principalId")
    permission: ProjectPermission
    granted_by_type: ActorType = Field(serialization_alias="grantedByType")
    granted_by_id: UUID | None = Field(serialization_alias="grantedById")
    granted_at: AwareDatetime = Field(serialization_alias="grantedAt")


class AclPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[AclEntryResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


__all__ = ["AclEntryResponse", "AclGrantRequest", "AclPage"]
