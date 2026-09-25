from datetime import datetime
from typing import Literal
from unicodedata import category
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class FeishuSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr = Field(min_length=1, max_length=200)
    document_id: StrictStr = Field(alias="documentId", pattern=r"^[A-Za-z0-9]{1,128}$")
    credential_ref: StrictStr = Field(
        alias="credentialRef",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$",
    )
    access_policy: Literal["project_members"] = Field(alias="accessPolicy")

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if any(category(character) in {"Cc", "Cs"} for character in value):
            raise ValueError("name must not contain control characters")
        return value.strip()


class KnowledgeSourceSyncCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeSourceSyncResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    project_id: UUID = Field(serialization_alias="projectId")
    source_id: UUID = Field(serialization_alias="sourceId")
    status: Literal["queued", "running", "completed", "failed"]
    attempt: int
    created_at: datetime = Field(serialization_alias="createdAt")
    completed_at: datetime | None = Field(serialization_alias="completedAt")
    error_code: str | None = Field(serialization_alias="errorCode")
    resource_id: UUID | None = Field(serialization_alias="resourceId")
    resource_version_id: UUID | None = Field(serialization_alias="resourceVersionId")


class KnowledgeSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID = Field(serialization_alias="projectId")
    provider: Literal["feishu"]
    name: str
    document_id: str = Field(validation_alias="external_id", serialization_alias="documentId")
    credential_ref: str = Field(serialization_alias="credentialRef")
    access_policy: Literal["project_members"] = Field(serialization_alias="accessPolicy")
    status: Literal["configured", "disabled"]
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    disabled_at: datetime | None = Field(serialization_alias="disabledAt")


class KnowledgeSourcePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[KnowledgeSourceResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


__all__ = [
    "FeishuSourceCreateRequest",
    "KnowledgeSourcePage",
    "KnowledgeSourceResponse",
    "KnowledgeSourceSyncCreateRequest",
    "KnowledgeSourceSyncResponse",
]
