from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cairn_api.projects.schemas import DependencyResponse, ProjectResponse, TaskPriority, TaskStatus

MinuteInput = Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)]
Weekday = Annotated[int, Field(strict=True, ge=1, le=7)]


class ScheduleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, from_attributes=True)


class ProjectCapacityUpdateRequest(ScheduleModel):
    expected_project_revision: int = Field(alias="expectedProjectRevision", ge=1)
    daily_capacity_minutes: MinuteInput | None = Field(alias="dailyCapacityMinutes")
    working_weekdays: list[Weekday] = Field(alias="workingWeekdays", min_length=1, max_length=7)

    @model_validator(mode="after")
    def distinct_weekdays(self) -> "ProjectCapacityUpdateRequest":
        if len(set(self.working_weekdays)) != len(self.working_weekdays):
            raise ValueError("workingWeekdays must be unique ISO weekdays (Monday=1)")
        self.working_weekdays.sort()
        return self


class ScheduleTaskInput(ScheduleModel):
    id: UUID
    revision: int = Field(ge=1)
    title: str
    status: TaskStatus
    priority: TaskPriority
    created_at: AwareDatetime = Field(alias="createdAt")
    estimated_effort_minutes: MinuteInput | None = Field(alias="estimatedEffortMinutes")
    remaining_effort_minutes: MinuteInput | None = Field(alias="remainingEffortMinutes")


class ScheduleIssue(ScheduleModel):
    code: str
    message: str
    task_ids: list[UUID] = Field(alias="taskIds")


class ScheduledTask(ScheduleModel):
    task_id: UUID = Field(alias="taskId")
    start_offset_minutes: int = Field(alias="startOffsetMinutes", ge=0)
    end_offset_minutes: int = Field(alias="endOffsetMinutes", ge=0)
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")


class DependencyCriticalChain(ScheduleModel):
    task_ids: list[UUID] = Field(alias="taskIds")
    remaining_minutes: int = Field(alias="remainingMinutes", ge=0)
    workday_lower_bound: float = Field(alias="workdayLowerBound", ge=0)


class ScheduleCalculation(ScheduleModel):
    effective_start_date: date | None = Field(default=None, alias="effectiveStartDate")
    completion_date: date | None = Field(default=None, alias="completionDate")
    known_remaining_minutes: int = Field(alias="knownRemainingMinutes", ge=0)
    gaps: list[ScheduleIssue]
    warnings: list[ScheduleIssue]
    schedule: list[ScheduledTask] = Field(default_factory=lambda: list[ScheduledTask]())
    critical_chain: DependencyCriticalChain | None = Field(default=None, alias="criticalChain")


class ScheduleProjectInput(ProjectResponse):
    # A schedule snapshot requires a revision; the older project response permits null.
    revision: int = Field(default=..., ge=1)  # pyright: ignore[reportIncompatibleVariableOverride]
    daily_capacity_minutes: MinuteInput | None = Field(default=..., alias="dailyCapacityMinutes")
    working_weekdays: list[Weekday] = Field(
        default=..., alias="workingWeekdays", min_length=1, max_length=7
    )


class ProjectScheduleResponse(ScheduleCalculation):
    project: ScheduleProjectInput
    schedule: list[ScheduledTask] = Field(default=...)
    effective_start_date: date | None = Field(default=..., alias="effectiveStartDate")
    completion_date: date | None = Field(default=..., alias="completionDate")
    critical_chain: DependencyCriticalChain | None = Field(default=..., alias="criticalChain")
    read_at: AwareDatetime = Field(alias="readAt")
    start_date: date = Field(alias="startDate")
    tasks: list[ScheduleTaskInput]
    dependencies: list[DependencyResponse]
    can_write: bool = Field(alias="canWrite")
    method: Literal["serial_shared_capacity"] = "serial_shared_capacity"
    assumptions: list[str]
