from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeContentHighlight(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    chunk_id: UUID = Field(serialization_alias="chunkId")
    line_start: int = Field(ge=1, serialization_alias="lineStart")
    line_end: int = Field(ge=1, serialization_alias="lineEnd")
    text: str
    match_type: Literal["exact", "range"] = Field(serialization_alias="matchType")


class KnowledgeContent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resource_id: UUID = Field(serialization_alias="resourceId")
    resource_version_id: UUID = Field(serialization_alias="resourceVersionId")
    title: str
    media_type: str = Field(serialization_alias="mediaType")
    format: Literal["markdown", "text"]
    content: str
    line_count: int = Field(ge=1, le=20_000, serialization_alias="lineCount")
    highlight: KnowledgeContentHighlight | None
