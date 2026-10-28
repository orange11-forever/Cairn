from copy import deepcopy
from enum import StrEnum
from typing import Annotated, Any, cast
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

EffortMinutes = Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)]


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
    description: str | None = Field(default=None, max_length=10_000)
    estimated_effort_minutes: EffortMinutes | None = Field(
        default=None, alias="estimatedEffortMinutes"
    )
    remaining_effort_minutes: EffortMinutes | None = Field(
        default=None, alias="remainingEffortMinutes"
    )
    assignee_user_id: UUID | None = Field(default=None, alias="assigneeUserId")
    stage_id: UUID | None = Field(default=None, alias="stageId")
    milestone_id: UUID | None = Field(default=None, alias="milestoneId")
    expected_project_revision: int | None = Field(
        default=None, alias="expectedProjectRevision", ge=1
    )
    parent_task_id: UUID | None = Field(default=None, alias="parentTaskId")
    priority: TaskPriority = TaskPriority.MEDIUM
    due_at: AwareDatetime | None = Field(default=None, alias="dueAt")
    acceptance_criteria: str | None = Field(
        default=None,
        alias="acceptanceCriteria",
        max_length=10_000,
    )


class TaskStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: TaskStatus
    expected_revision: int | None = Field(default=None, alias="expectedRevision", ge=1)


class TaskDependencyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_revision: int | None = Field(default=None, alias="expectedRevision", ge=1)
    predecessor_task_id: UUID = Field(
        alias="predecessorTaskId",
        description=(
            "The predecessor task. The task identified by the route is the successor, "
            "forming predecessor -> successor."
        ),
    )


def _patch_json_schema(schema: dict[str, Any]) -> None:
    properties = schema["properties"]
    revisions = [
        name
        for name in properties
        if name
        in (
            "expectedRevision",
            "expectedProjectRevision",
            "expected_revision",
            "expected_project_revision",
        )
    ]
    required = schema.get("required", [])
    title = schema["title"]
    for property_schema in properties.values():
        property_schema.pop("default", None)
    branches: list[dict[str, Any]] = []
    for name in properties:
        if name in revisions:
            continue
        branch_required = [*required, name]
        branch_properties = deepcopy(properties)
        grouping = ("stageId", "milestoneId", "stage_id", "milestone_id")
        if title in ("StageUpdateRequest", "MilestoneUpdateRequest"):
            for field in branch_properties:
                if field not in revisions and (field == "archived") != (name == "archived"):
                    branch_properties[field] = False
        # Ordinary edit branches cannot admit grouping through a different
        # editable field. Grouping branches always require the project revision.
        if title == "TaskUpdateRequest" and name not in grouping:
            for field in grouping:
                if field in branch_properties:
                    branch_properties[field] = False
        if title == "TaskUpdateRequest" and name in (
            "stageId",
            "milestoneId",
            "stage_id",
            "milestone_id",
        ):
            project_revision = (
                "expectedProjectRevision"
                if "expectedProjectRevision" in properties
                else "expected_project_revision"
            )
            branch_required.append(project_revision)
            branch_properties[project_revision] = {"type": "integer", "minimum": 1}
        branches.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": branch_properties,
                "required": branch_required,
            }
        )
    schema.clear()
    schema.update({"title": title, "anyOf": branches})


class TaskUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra=_patch_json_schema,
    )

    expected_revision: int = Field(alias="expectedRevision", ge=1)
    expected_project_revision: int | None = Field(
        default=None, alias="expectedProjectRevision", ge=1
    )
    stage_id: UUID | None = Field(default=None, alias="stageId")
    milestone_id: UUID | None = Field(default=None, alias="milestoneId")
    title: str = Field(default_factory=lambda: cast(str, None), min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    estimated_effort_minutes: EffortMinutes | None = Field(
        default=None, alias="estimatedEffortMinutes"
    )
    remaining_effort_minutes: EffortMinutes | None = Field(
        default=None, alias="remainingEffortMinutes"
    )
    assignee_user_id: UUID | None = Field(default=None, alias="assigneeUserId")
    priority: TaskPriority = Field(default_factory=lambda: cast(TaskPriority, None))
    due_at: AwareDatetime | None = Field(default=None, alias="dueAt")
    acceptance_criteria: str | None = Field(
        default=None, alias="acceptanceCriteria", max_length=10_000
    )

    @model_validator(mode="after")
    def validate_patch(self) -> "TaskUpdateRequest":
        if not self.model_fields_set - {"expected_revision", "expected_project_revision"}:
            raise ValueError("At least one editable field is required")
        if (
            self.model_fields_set & {"stage_id", "milestone_id"}
            and self.expected_project_revision is None
        ):
            raise ValueError("Grouping edits require expectedProjectRevision")
        for name in ("title", "priority"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class AssigneeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    user_id: UUID = Field(serialization_alias="userId")
    display_name: str | None = Field(serialization_alias="displayName")
    role: str


class AssigneePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    items: list[AssigneeResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    revision: int | None = Field(default=None, ge=1)
    daily_capacity_minutes: EffortMinutes | None = Field(default=None, alias="dailyCapacityMinutes")
    working_weekdays: list[Annotated[int, Field(strict=True, ge=1, le=7)]] = Field(
        default_factory=lambda: [1, 2, 3, 4, 5], alias="workingWeekdays", min_length=1, max_length=7
    )
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(max_length=4000)
    created_at: AwareDatetime = Field(alias="createdAt")
    updated_at: AwareDatetime = Field(alias="updatedAt")


class ProjectPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[ProjectResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID = Field(alias="projectId")
    revision: int = Field(ge=1)
    description: str | None = Field(max_length=10_000)
    estimated_effort_minutes: EffortMinutes | None = Field(
        default=None, alias="estimatedEffortMinutes"
    )
    remaining_effort_minutes: EffortMinutes | None = Field(
        default=None, alias="remainingEffortMinutes"
    )
    assignee_user_id: UUID | None = Field(alias="assigneeUserId")
    title: str = Field(min_length=1, max_length=240)
    stage_id: UUID | None = Field(alias="stageId")
    milestone_id: UUID | None = Field(alias="milestoneId")
    parent_task_id: UUID | None = Field(alias="parentTaskId")
    status: TaskStatus
    priority: TaskPriority
    due_at: AwareDatetime | None = Field(alias="dueAt")
    acceptance_criteria: str | None = Field(
        alias="acceptanceCriteria",
        max_length=10_000,
    )
    created_at: AwareDatetime = Field(alias="createdAt")
    updated_at: AwareDatetime = Field(alias="updatedAt")


class TaskPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[TaskResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class DependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    predecessor_task_id: UUID = Field(alias="predecessorTaskId")
    successor_task_id: UUID = Field(alias="successorTaskId")
    created_at: AwareDatetime = Field(alias="createdAt")


class DependencyPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    items: list[DependencyResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


__all__ = [
    "AssigneePage",
    "AssigneeResponse",
    "DependencyPage",
    "DependencyResponse",
    "MilestoneCreateRequest",
    "MilestonePage",
    "MilestoneResponse",
    "MilestoneUpdateRequest",
    "ProjectCreateRequest",
    "ProjectPage",
    "ProjectResponse",
    "StageCreateRequest",
    "StagePage",
    "StageResponse",
    "StageUpdateRequest",
    "TaskCreateRequest",
    "TaskDependencyCreateRequest",
    "TaskPage",
    "TaskPriority",
    "TaskResponse",
    "TaskStatus",
    "TaskStatusUpdateRequest",
    "TaskUpdateRequest",
]


class StructureCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    expected_project_revision: int = Field(alias="expectedProjectRevision", ge=1)


class StageCreateRequest(StructureCreateRequest):
    name: str = Field(min_length=1, max_length=120)
    position: int = Field(ge=0, le=2147483647, strict=True)


class StructureUpdateRequest(StructureCreateRequest):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra=_patch_json_schema,
    )
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    archived: bool = Field(default_factory=lambda: cast(bool, None), strict=True)

    @model_validator(mode="after")
    def validate_structure_patch(self) -> "StructureUpdateRequest":
        if "archived" in self.model_fields_set and self.model_fields_set - {
            "archived",
            "expected_revision",
            "expected_project_revision",
        }:
            raise ValueError("Lifecycle changes cannot be combined with ordinary edits")
        if not self.model_fields_set - {"expected_revision", "expected_project_revision"}:
            raise ValueError("At least one editable field is required")
        return self


class StageUpdateRequest(StructureUpdateRequest):
    name: str = Field(default_factory=lambda: cast(str, None), min_length=1, max_length=120)
    position: int = Field(default_factory=lambda: cast(int, None), ge=0, le=2147483647, strict=True)


class MilestoneCreateRequest(StructureCreateRequest):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    acceptance_criteria: str | None = Field(
        default=None, alias="acceptanceCriteria", max_length=10000
    )
    due_at: AwareDatetime | None = Field(default=None, alias="dueAt")
    stage_id: UUID | None = Field(default=None, alias="stageId")


class MilestoneUpdateRequest(StructureUpdateRequest):
    name: str = Field(default_factory=lambda: cast(str, None), min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    acceptance_criteria: str | None = Field(
        default=None, alias="acceptanceCriteria", max_length=10000
    )
    due_at: AwareDatetime | None = Field(default=None, alias="dueAt")
    stage_id: UUID | None = Field(default=None, alias="stageId")


class StageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: UUID
    project_id: UUID = Field(alias="projectId")
    revision: int = Field(ge=1)
    archived: bool
    name: str = Field(min_length=1, max_length=120)
    position: int
    created_at: AwareDatetime = Field(alias="createdAt")
    updated_at: AwareDatetime = Field(alias="updatedAt")


class MilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: UUID
    project_id: UUID = Field(alias="projectId")
    revision: int = Field(ge=1)
    archived: bool
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(max_length=4000)
    acceptance_criteria: str | None = Field(alias="acceptanceCriteria", max_length=10000)
    due_at: AwareDatetime | None = Field(alias="dueAt")
    stage_id: UUID | None = Field(alias="stageId")
    created_at: AwareDatetime = Field(alias="createdAt")
    updated_at: AwareDatetime = Field(alias="updatedAt")


class StagePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    items: list[StageResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


class MilestonePage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    items: list[MilestoneResponse]
    next_cursor: str | None = Field(serialization_alias="nextCursor")
