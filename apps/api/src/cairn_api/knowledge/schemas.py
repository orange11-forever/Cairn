from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, StrictStr

from cairn_api.knowledge.models import IngestionItemStatus


class UploadFileIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: StrictStr = Field(alias="fileName", min_length=1, max_length=255)
    media_type: StrictStr = Field(alias="mediaType", min_length=1, max_length=127)
    size_bytes: StrictInt = Field(alias="sizeBytes", gt=0)
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class UploadBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[UploadFileIntent] = Field(min_length=1, max_length=20)


class UploadInstruction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    upload_id: UUID = Field(serialization_alias="uploadId")
    item_id: UUID = Field(serialization_alias="itemId")
    method: Literal["PUT"] = "PUT"
    url: str
    headers: dict[str, str]
    expires_at: AwareDatetime = Field(serialization_alias="expiresAt")


class UploadBatchCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    batch_id: UUID = Field(serialization_alias="batchId")
    uploads: list[UploadInstruction]


class UploadCompleteResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    upload_id: UUID = Field(serialization_alias="uploadId")
    batch_id: UUID = Field(serialization_alias="batchId")
    item_id: UUID = Field(serialization_alias="itemId")
    resource_id: UUID | None = Field(serialization_alias="resourceId")
    resource_version_id: UUID | None = Field(serialization_alias="resourceVersionId")
    status: IngestionItemStatus


__all__ = [
    "UploadBatchCreateRequest",
    "UploadBatchCreateResponse",
    "UploadCompleteResponse",
    "UploadFileIntent",
    "UploadInstruction",
]
