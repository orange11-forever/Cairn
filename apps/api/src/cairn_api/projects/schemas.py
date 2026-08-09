from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    title: str = Field(min_length=1, max_length=240)
    stage_id: UUID | None = Field(default=None, alias="stageId")
    parent_task_id: UUID | None = Field(default=None, alias="parentTaskId")
    priority: TaskPriority = TaskPriority.MEDIUM
    due_at: AwareDatetime | None = Field(default=None, alias="dueAt")
    acceptance_criteria: str | None = Field(
        default=None,
        alias="acceptanceCriteria",
        max_length=10_000,
    )


class TaskStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus


class TaskDependencyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    predecessor_task_id: UUID = Field(
        alias="predecessorTaskId",
        description=(
            "The predecessor task. The task identified by the route is the successor, "
            "forming predecessor -> successor."
        ),
    )


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(max_length=4000)
    created_at: AwareDatetime = Field(serialization_alias="createdAt")
    updated_at: AwareDatetime = Field(serialization_alias="updatedAt")


class ProjectPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[ProjectResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID = Field(serialization_alias="projectId")
    title: str = Field(min_length=1, max_length=240)
    stage_id: UUID | None = Field(serialization_alias="stageId")
    parent_task_id: UUID | None = Field(serialization_alias="parentTaskId")
    status: TaskStatus
    priority: TaskPriority
    due_at: AwareDatetime | None = Field(serialization_alias="dueAt")
    acceptance_criteria: str | None = Field(
        serialization_alias="acceptanceCriteria",
        max_length=10_000,
    )
    created_at: AwareDatetime = Field(serialization_alias="createdAt")
    updated_at: AwareDatetime = Field(serialization_alias="updatedAt")


class TaskPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[TaskResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class DependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    predecessor_task_id: UUID = Field(serialization_alias="predecessorTaskId")
    successor_task_id: UUID = Field(serialization_alias="successorTaskId")
    created_at: AwareDatetime = Field(serialization_alias="createdAt")


__all__ = [
    "DependencyResponse",
    "ProjectCreateRequest",
    "ProjectPage",
    "ProjectResponse",
    "TaskCreateRequest",
    "TaskDependencyCreateRequest",
    "TaskPage",
    "TaskPriority",
    "TaskResponse",
    "TaskStatus",
    "TaskStatusUpdateRequest",
]
