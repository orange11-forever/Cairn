from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, StrictStr

from cairn_api.knowledge.models import (
    IngestionBatchStatus,
    IngestionItemStatus,
    ResourceVersionStatus,
)


class PdfLocator(BaseModel):
    type: Literal["pdf"] = "pdf"
    page: int = Field(ge=1)


class DocxLocator(BaseModel):
    type: Literal["docx"] = "docx"
    heading_path: list[str] = Field(alias="headingPath")
    paragraph: int | None = Field(default=None, ge=1)
    table: int | None = Field(default=None, ge=1)


class PptxLocator(BaseModel):
    type: Literal["pptx"] = "pptx"
    slide: int = Field(ge=1)
    area: Literal["body", "notes"]


class XlsxLocator(BaseModel):
    type: Literal["xlsx"] = "xlsx"
    sheet: str
    cell_range: str = Field(alias="cellRange")


class CsvLocator(BaseModel):
    type: Literal["csv"] = "csv"
    row_start: int = Field(alias="rowStart", ge=1)
    row_end: int = Field(alias="rowEnd", ge=1)


class HtmlLocator(BaseModel):
    type: Literal["html"] = "html"
    heading_path: list[str] = Field(alias="headingPath")
    block: int = Field(ge=1)


class TextLocator(BaseModel):
    type: Literal["text", "markdown"]
    heading_path: list[str] = Field(default_factory=list, alias="headingPath")
    line_start: int = Field(alias="lineStart", ge=1)
    line_end: int = Field(alias="lineEnd", ge=1)


KnowledgeLocator = Annotated[
    PdfLocator | DocxLocator | PptxLocator | XlsxLocator | CsvLocator | HtmlLocator | TextLocator,
    Field(discriminator="type"),
]


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


class IngestionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    parent_item_id: UUID | None = Field(serialization_alias="parentItemId")
    normalized_path: str = Field(serialization_alias="normalizedPath")
    media_type: str = Field(serialization_alias="mediaType")
    size_bytes: int = Field(serialization_alias="sizeBytes")
    status: IngestionItemStatus
    error_code: str | None = Field(serialization_alias="errorCode")
    error_detail: str | None = Field(serialization_alias="errorDetail")
    resource_id: UUID | None = Field(serialization_alias="resourceId")
    resource_version_id: UUID | None = Field(serialization_alias="resourceVersionId")
    created_at: AwareDatetime = Field(serialization_alias="createdAt")
    completed_at: AwareDatetime | None = Field(serialization_alias="completedAt")


class BatchDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    status: IngestionBatchStatus
    item_count: int = Field(serialization_alias="itemCount")
    ready_count: int = Field(serialization_alias="readyCount")
    failed_count: int = Field(serialization_alias="failedCount")
    created_at: AwareDatetime = Field(serialization_alias="createdAt")
    completed_at: AwareDatetime | None = Field(serialization_alias="completedAt")
    items: list[IngestionItemResponse]


class KnowledgeVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    source_type: str = Field(serialization_alias="sourceType")
    media_type: str = Field(serialization_alias="mediaType")
    size_bytes: int = Field(serialization_alias="sizeBytes")
    sha256: str
    status: ResourceVersionStatus
    error_code: str | None = Field(serialization_alias="errorCode")
    retryable: bool = False
    created_at: AwareDatetime = Field(serialization_alias="createdAt")
    processing_started_at: AwareDatetime | None = Field(serialization_alias="processingStartedAt")
    ready_at: AwareDatetime | None = Field(serialization_alias="readyAt")


class KnowledgeResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    title: str
    source_type: str = Field(serialization_alias="sourceType")
    created_at: AwareDatetime = Field(serialization_alias="createdAt")
    updated_at: AwareDatetime = Field(serialization_alias="updatedAt")
    latest_version: KnowledgeVersionResponse | None = Field(serialization_alias="latestVersion")


class KnowledgeCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    can_write: bool = Field(serialization_alias="canWrite")


class KnowledgeResourcePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[KnowledgeResourceResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")
    capabilities: KnowledgeCapabilities


class ChunkResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    ordinal: int
    text: str
    locator: KnowledgeLocator


class ChunkContextResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    resource_id: UUID = Field(serialization_alias="resourceId")
    resource_version_id: UUID = Field(serialization_alias="resourceVersionId")
    hit: ChunkResponse
    before: ChunkResponse | None
    after: ChunkResponse | None


__all__ = [
    "BatchDetailResponse",
    "ChunkContextResponse",
    "ChunkResponse",
    "CsvLocator",
    "DocxLocator",
    "HtmlLocator",
    "IngestionItemResponse",
    "KnowledgeCapabilities",
    "KnowledgeLocator",
    "KnowledgeResourcePage",
    "KnowledgeResourceResponse",
    "KnowledgeVersionResponse",
    "PdfLocator",
    "PptxLocator",
    "TextLocator",
    "UploadBatchCreateRequest",
    "UploadBatchCreateResponse",
    "UploadCompleteResponse",
    "UploadFileIntent",
    "UploadInstruction",
    "XlsxLocator",
]
