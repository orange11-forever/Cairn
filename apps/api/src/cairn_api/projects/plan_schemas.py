from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cairn_api.knowledge.plan_schemas import ProjectPlanDraft
from cairn_api.projects.analysis_schemas import ProjectPlanPreviewResponse


class ProjectPlanApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operation_id: UUID = Field(alias="operationId")
    preview: ProjectPlanPreviewResponse

    @model_validator(mode="after")
    def require_plan(self) -> "ProjectPlanApplyRequest":
        if self.preview.plan.status != "planned":
            raise ValueError("only a nonempty plan can be applied")
        return self


class PlanSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    resource_id: UUID = Field(alias="resourceId")
    resource_version_id: UUID = Field(alias="resourceVersionId")
    chunk_id: UUID = Field(alias="chunkId")


class ProjectPlanApplicationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operation_id: UUID = Field(alias="operationId")
    project_id: UUID = Field(alias="projectId")
    generated_at: AwareDatetime = Field(alias="generatedAt")
    applied_at: AwareDatetime = Field(alias="appliedAt")
    plan: ProjectPlanDraft
    sources: list[PlanSourceReference]
    stage_ids: dict[str, UUID] = Field(alias="stageIds")
    milestone_ids: dict[str, UUID] = Field(alias="milestoneIds")
    task_ids: dict[str, UUID] = Field(alias="taskIds")


class ProjectPlanApplicationPage(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    items: list[ProjectPlanApplicationResponse]
    next_cursor: str | None = Field(alias="nextCursor")
