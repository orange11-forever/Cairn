from copy import deepcopy
from datetime import datetime
from typing import Any, Literal
from unicodedata import category
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class FeishuSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr = Field(min_length=1, max_length=200)
    document_id: StrictStr = Field(alias="documentId", pattern=r"^[A-Za-z0-9]{1,128}$")
    credential_ref: StrictStr = Field(
        alias="credentialRef",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$",
    )
    access_policy: Literal["project_members"] = Field(alias="accessPolicy")
    sync_interval_seconds: StrictInt | None = Field(default=None, alias="syncIntervalSeconds", ge=300, le=604800)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if any(category(character) in {"Cc", "Cs"} for character in value):
            raise ValueError("name must not contain control characters")
        return value.strip()


def _patch_request_json_schema(schema: dict[str, Any]) -> None:
    properties = schema["properties"]

    def branch(*, sharing: bool, required_field: str) -> dict[str, Any]:
        allowed = ["name", "status", "syncIntervalSeconds"]
        if sharing:
            allowed += ["credentialRef", "accessPolicy"]
        fields = {key: deepcopy(properties[key]) for key in allowed}
        for key in ("name", "credentialRef", "status", "accessPolicy"):
            if key not in fields:
                continue
            nullable = fields[key]
            if "anyOf" in nullable:
                fields[key] = next(part for part in nullable["anyOf"] if part.get("type") != "null")
        if not sharing:
            fields["status"] = {"const": "disabled", "type": "string"}
            fields["credentialRef"] = False
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": fields,
            "required": ["accessPolicy", required_field] if sharing else [required_field],
        }

    schema.clear()
    schema.update({
        "title": "FeishuSourcePatchRequest",
        "oneOf": [
            {"anyOf": [branch(sharing=False, required_field=key) for key in ("name", "status", "syncIntervalSeconds")]},
            {"anyOf": [branch(sharing=True, required_field=key) for key in ("name", "credentialRef", "status", "syncIntervalSeconds")]},
        ],
    })


class FeishuSourcePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra=_patch_request_json_schema)

    name: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="The API trims surrounding whitespace and rejects control characters.",
    )
    credential_ref: StrictStr | None = Field(default=None, alias="credentialRef", pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    sync_interval_seconds: StrictInt | None = Field(default=None, alias="syncIntervalSeconds", ge=300, le=604800)
    status: Literal["configured", "disabled"] | None = None
    access_policy: Literal["project_members"] | None = Field(default=None, alias="accessPolicy")

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return FeishuSourceCreateRequest.trim_name(value)

    @model_validator(mode="after")
    def check_fields(self) -> "FeishuSourcePatchRequest":
        provided = self.model_fields_set
        if not provided.intersection({"name", "credential_ref", "sync_interval_seconds", "status"}) or any(getattr(self, key) is None for key in provided if key != "sync_interval_seconds"):
            raise ValueError("at least one non-null update is required")
        if ("credential_ref" in provided or self.status == "configured") and self.access_policy != "project_members":
            raise ValueError("explicit project member sharing is required")
        return self


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
    trigger: Literal["manual", "scheduled"]
    failure_code: str | None = Field(serialization_alias="failureCode")
    next_attempt_at: datetime | None = Field(serialization_alias="nextAttemptAt")
    resource_status: Literal["queued", "processing", "ready", "failed"] | None = Field(serialization_alias="resourceStatus")


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
    sync_interval_seconds: int | None = Field(serialization_alias="syncIntervalSeconds")
    next_sync_at: datetime | None = Field(serialization_alias="nextSyncAt")
    last_checked_at: datetime | None = Field(serialization_alias="lastCheckedAt")
    last_success_at: datetime | None = Field(serialization_alias="lastSuccessAt")
    last_error_code: str | None = Field(serialization_alias="lastErrorCode")
    access_state: Literal["available", "unverified", "access_denied", "not_found"] = Field(serialization_alias="accessState")


class KnowledgeSourcePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[KnowledgeSourceResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class KnowledgeSourceSyncPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[KnowledgeSourceSyncResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


__all__ = [
    "FeishuSourceCreateRequest",
    "FeishuSourcePatchRequest",
    "KnowledgeSourcePage",
    "KnowledgeSourceResponse",
    "KnowledgeSourceSyncCreateRequest",
    "KnowledgeSourceSyncPage",
    "KnowledgeSourceSyncResponse",
]
