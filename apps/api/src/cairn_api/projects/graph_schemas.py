from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cairn_api.projects.schemas import DependencyResponse, ProjectResponse, TaskStatus


class GraphTask(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID = Field(alias="projectId")
    revision: int = Field(ge=1)
    title: str
    status: TaskStatus
    stage_id: UUID | None = Field(alias="stageId")
    milestone_id: UUID | None = Field(alias="milestoneId")


class GraphStage(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    position: int
    archived: bool


class GraphMilestone(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    stage_id: UUID | None = Field(alias="stageId")
    archived: bool


class ProjectTaskGraphResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project: ProjectResponse
    read_at: datetime = Field(alias="readAt")
    tasks: list[GraphTask]
    dependencies: list[DependencyResponse]
    stages: list[GraphStage]
    milestones: list[GraphMilestone]
