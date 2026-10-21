from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cairn_api.knowledge.answer_models import AnswerModelOption
from cairn_api.knowledge.answer_schemas import KnowledgeAnswerCitation, KnowledgeAnswerParagraph
from cairn_api.knowledge.plan_schemas import ProjectPlanDraft
from cairn_api.projects.schemas import (
    DependencyResponse,
    MilestoneResponse,
    ProjectResponse,
    StageResponse,
    TaskResponse,
)


class ProjectAnalysisSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectResponse
    stages: list[StageResponse] = Field(max_length=50)
    milestones: list[MilestoneResponse] = Field(max_length=50)
    tasks: list[TaskResponse] = Field(max_length=100)
    dependencies: list[DependencyResponse] = Field(max_length=300)


class ProjectAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: UUID = Field(alias="projectId")
    generated_at: AwareDatetime = Field(alias="generatedAt")
    assistant_name: str = Field(alias="assistantName")
    model: AnswerModelOption
    snapshot: ProjectAnalysisSnapshot
    status: Literal["answered", "insufficient_evidence"]
    retrieval_mode: Literal["hybrid", "keyword_fallback"] = Field(alias="retrievalMode")
    paragraphs: list[KnowledgeAnswerParagraph] = Field(max_length=8)
    citations: list[KnowledgeAnswerCitation] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_evidence(self) -> "ProjectAnalysisResponse":
        # S1 is always the complete project snapshot; knowledge uses S2–S6.
        ids = [citation.id for citation in self.citations]
        if "S1" in ids or len(ids) != len(set(ids)):
            raise ValueError("analysis evidence IDs must be unique")
        if self.status == "insufficient_evidence":
            if self.paragraphs:
                raise ValueError("insufficient evidence cannot include analysis")
        elif not self.paragraphs:
            raise ValueError("answered analysis requires paragraphs")
        known = {"S1", *ids}
        for paragraph in self.paragraphs:
            if not set(paragraph.citation_ids) <= known:
                raise ValueError("analysis references unknown evidence")
        return self


class ProjectPlanPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: UUID = Field(alias="projectId")
    generated_at: AwareDatetime = Field(alias="generatedAt")
    assistant_name: str = Field(alias="assistantName")
    model: AnswerModelOption
    snapshot: ProjectAnalysisSnapshot
    retrieval_mode: Literal["hybrid", "keyword_fallback"] = Field(alias="retrievalMode")
    citations: list[KnowledgeAnswerCitation] = Field(max_length=5)
    plan: ProjectPlanDraft

    @model_validator(mode="after")
    def validate_plan_evidence(self) -> "ProjectPlanPreviewResponse":
        ids = [citation.id for citation in self.citations]
        if "S1" in ids or len(ids) != len(set(ids)):
            raise ValueError("plan evidence IDs must be unique")
        known = {"S1", *ids}
        references = [
            self.plan.citation_ids,
            *[
                item.citation_ids
                for item in [*self.plan.stages, *self.plan.milestones, *self.plan.tasks]
            ],
        ]
        if any(
            not set(citations) <= known or len(citations) != len(set(citations))
            for citations in references
        ):
            raise ValueError("plan references unknown or duplicate evidence")
        return self
