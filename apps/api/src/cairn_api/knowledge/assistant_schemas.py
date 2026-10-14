from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AssistantSettingsResponse(StrictSchema):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=60)
    instructions: str = Field(max_length=2000)
    enabled_skill_ids: list[str] = Field(alias="enabledSkillIds", max_length=22)
    revision: int = Field(ge=0)
    model_id: str | None = Field(default=None, alias="modelId", max_length=64)


class AssistantSettingsRequest(StrictSchema):
    expected_revision: int = Field(alias="expectedRevision", strict=True, ge=0)
    name: str = Field(min_length=1, max_length=60)
    instructions: str = Field(max_length=2000)
    enabled_skill_ids: list[str] = Field(alias="enabledSkillIds", max_length=22)
    model_id: str | None = Field(default=None, alias="modelId", pattern=r"^[a-z][a-z0-9_-]{0,63}$")

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("name", "instructions")
    @classmethod
    def valid_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("invalid text")
        value.encode("utf-8")
        return value

    @field_validator("enabled_skill_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate skills")
        return value


class AssistantSelectionRequest(StrictSchema):
    expected_revision: int = Field(alias="expectedRevision", strict=True, ge=0)


class AssistantProfileSummary(StrictSchema):
    id: UUID
    name: str = Field(min_length=1, max_length=60)
    model_id: str | None = Field(alias="modelId")


class AssistantCatalogResponse(StrictSchema):
    items: list[AssistantProfileSummary] = Field(max_length=20)


class MarkdownSkillSource(StrictSchema):
    type: Literal["markdown"]
    file_name: str = Field(alias="fileName", min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=65536)


class ZipSkillSource(StrictSchema):
    type: Literal["zip"]
    file_name: str = Field(alias="fileName", min_length=1, max_length=120)
    content_base64: str = Field(alias="contentBase64", min_length=1, max_length=349528)


class GithubSkillSource(StrictSchema):
    type: Literal["github"]
    url: str = Field(min_length=1, max_length=1024)
    path: str | None = Field(default=None, max_length=500)
    ref: str | None = Field(default=None, min_length=1, max_length=128)


SkillImportSource = Annotated[
    MarkdownSkillSource | ZipSkillSource | GithubSkillSource, Field(discriminator="type")
]


class SkillPreviewRequest(StrictSchema):
    source: SkillImportSource


class SkillImportRequest(SkillPreviewRequest):
    id: UUID
    expected_digest: str = Field(alias="expectedDigest", pattern="^[0-9a-f]{64}$")


class SkillResource(StrictSchema):
    path: str
    content: str


class KnowledgeSkillItem(StrictSchema):
    id: str
    name: str
    description: str
    default_question: str = Field(alias="defaultQuestion")
    version: Literal["v1"] = "v1"
    capabilities: list[Literal["knowledge.read"]]
    source_type: Literal["builtin", "markdown", "zip", "github"] = Field(alias="sourceType")
    runnable: bool
    warnings: list[str]


class KnowledgeSkillCatalogResponse(StrictSchema):
    items: list[KnowledgeSkillItem]


class KnowledgeSkillPreview(StrictSchema):
    name: str
    description: str
    default_question: str = Field(alias="defaultQuestion")
    version: Literal["v1"] = "v1"
    capabilities: list[Literal["knowledge.read"]]
    source_type: Literal["markdown", "zip", "github"] = Field(alias="sourceType")
    source_metadata: dict[str, str] = Field(alias="sourceMetadata")
    runnable: bool
    warnings: list[str]
    body: str
    resources: list[SkillResource]
    digest: str


class KnowledgeSkillImportResponse(KnowledgeSkillPreview):
    id: UUID
