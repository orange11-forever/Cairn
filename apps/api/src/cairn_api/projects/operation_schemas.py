from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cairn_api.knowledge.answer_models import AnswerModelOption
from cairn_api.projects.analysis_schemas import ProjectAnalysisSnapshot
from cairn_api.projects.schemas import TaskPriority, TaskStatus


class OperationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class CreateProjectAction(OperationModel):
    type: Literal["create_project"]
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class DispatchTaskAction(OperationModel):
    type: Literal["dispatch_task"]
    task_id: UUID = Field(alias="taskId")
    assistant_id: UUID | None = Field(alias="assistantId")
    assistant_name: str | None = Field(default=None, alias="assistantName", max_length=240)


class CreateTaskAction(OperationModel):
    type: Literal["create_task"]
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    priority: TaskPriority = TaskPriority.MEDIUM
    acceptance_criteria: str | None = Field(
        default=None, alias="acceptanceCriteria", max_length=10_000
    )
    stage_id: UUID | None = Field(default=None, alias="stageId")
    milestone_id: UUID | None = Field(default=None, alias="milestoneId")


class UpdateTaskAction(OperationModel):
    type: Literal["update_task"]
    task_id: UUID = Field(alias="taskId")
    field: Literal["title", "description", "priority", "acceptanceCriteria"]
    value: str | None = Field(max_length=10_000)

    @model_validator(mode="after")
    def validate_value(self) -> "UpdateTaskAction":
        if self.field == "title" and (not self.value or len(self.value) > 240):
            raise ValueError("title must contain 1 to 240 characters")
        if self.field == "priority" and self.value not in {p.value for p in TaskPriority}:
            raise ValueError("invalid priority")
        return self


class ChangeStatusAction(OperationModel):
    type: Literal["change_status"]
    task_id: UUID = Field(alias="taskId")
    status: TaskStatus


class AssignTaskAction(OperationModel):
    type: Literal["assign_task"]
    task_id: UUID = Field(alias="taskId")
    assignee_user_id: UUID | None = Field(alias="assigneeUserId")
    # The service fills this label from the authorized member record.
    assignee_name: str | None = Field(default=None, alias="assigneeName", max_length=240)


class AddDependencyAction(OperationModel):
    type: Literal["add_dependency"]
    predecessor_task_id: UUID = Field(alias="predecessorTaskId")
    successor_task_id: UUID = Field(alias="successorTaskId")


class RemoveDependencyAction(OperationModel):
    type: Literal["remove_dependency"]
    task_id: UUID = Field(alias="taskId")
    dependency_id: UUID = Field(alias="dependencyId")


ProjectAction = Annotated[
    CreateProjectAction
    | DispatchTaskAction
    | CreateTaskAction
    | UpdateTaskAction
    | ChangeStatusAction
    | AssignTaskAction
    | AddDependencyAction
    | RemoveDependencyAction,
    Field(discriminator="type"),
]


class ProjectOperationSuggestion(OperationModel):
    status: Literal["proposed", "needs_clarification"]
    explanation: str = Field(min_length=1, max_length=2000)
    action: ProjectAction | None

    @model_validator(mode="after")
    def require_action(self) -> "ProjectOperationSuggestion":
        if (self.status == "proposed") != (self.action is not None):
            raise ValueError("only proposed suggestions require an action")
        return self


class ProjectOperationPreviewRequest(OperationModel):
    intent: str = Field(min_length=1, max_length=2000)


class ProjectOperationPreviewResponse(OperationModel):
    project_id: UUID = Field(alias="projectId")
    intent: str = Field(min_length=1, max_length=2000)
    generated_at: AwareDatetime = Field(alias="generatedAt")
    assistant_name: str = Field(alias="assistantName")
    model: AnswerModelOption
    snapshot: ProjectAnalysisSnapshot
    suggestion: ProjectOperationSuggestion
    can_execute: bool = Field(alias="canExecute")

    @model_validator(mode="after")
    def validate_targets(self) -> "ProjectOperationPreviewResponse":
        if self.snapshot.project.id != self.project_id:
            raise ValueError("snapshot project mismatch")
        action = self.suggestion.action
        if isinstance(action, CreateProjectAction):
            raise ValueError("project creation requires its own preview")  # noqa: TRY004 - Pydantic validation
        task_ids = {task.id for task in self.snapshot.tasks}
        if (
            isinstance(action, (UpdateTaskAction, ChangeStatusAction, AssignTaskAction, RemoveDependencyAction, DispatchTaskAction))
            and action.task_id not in task_ids
        ):
            raise ValueError("unknown task")
        if (
            isinstance(action, AddDependencyAction)
            and not {action.predecessor_task_id, action.successor_task_id} <= task_ids
        ):
            raise ValueError("unknown dependency task")
        if isinstance(action, RemoveDependencyAction) and not any(
            edge.id == action.dependency_id and edge.successor_task_id == action.task_id
            for edge in self.snapshot.dependencies
        ):
            raise ValueError("unknown dependency")
        if isinstance(action, CreateTaskAction):
            if action.stage_id is not None and not any(
                s.id == action.stage_id for s in self.snapshot.stages
            ):
                raise ValueError("unknown stage")
            if action.milestone_id is not None and not any(
                m.id == action.milestone_id for m in self.snapshot.milestones
            ):
                raise ValueError("unknown milestone")
        return self


class ProjectOperationApplyRequest(OperationModel):
    operation_id: UUID = Field(alias="operationId")
    confirmed: Literal[True]
    preview: ProjectOperationPreviewResponse

    @model_validator(mode="after")
    def require_proposed(self) -> "ProjectOperationApplyRequest":
        if self.preview.suggestion.status != "proposed":
            raise ValueError("only a proposed action can be confirmed")
        if isinstance(self.preview.suggestion.action, DispatchTaskAction):
            raise ValueError("coding tasks must be confirmed in the coding workspace")  # noqa: TRY004
        return self


class ProjectCreationPreviewResponse(OperationModel):
    organization_id: UUID = Field(alias="organizationId")
    intent: str = Field(min_length=1, max_length=2000)
    generated_at: AwareDatetime = Field(alias="generatedAt")
    model: AnswerModelOption
    suggestion: ProjectOperationSuggestion

    @model_validator(mode="after")
    def creation_only(self) -> "ProjectCreationPreviewResponse":
        if self.suggestion.action is not None and not isinstance(self.suggestion.action, CreateProjectAction):
            raise ValueError("only project creation is supported")
        return self


class ProjectCreationApplyRequest(OperationModel):
    operation_id: UUID = Field(alias="operationId")
    confirmed: Literal[True]
    preview: ProjectCreationPreviewResponse

    @model_validator(mode="after")
    def require_creation(self) -> "ProjectCreationApplyRequest":
        if self.preview.suggestion.status != "proposed":
            raise ValueError("only a proposed creation can be confirmed")
        return self


class ProjectOperationResponse(OperationModel):
    operation_id: UUID = Field(alias="operationId")
    project_id: UUID = Field(alias="projectId")
    intent: str
    action: ProjectAction
    explanation: str
    generated_at: AwareDatetime = Field(alias="generatedAt")
    applied_at: AwareDatetime = Field(alias="appliedAt")
    result: dict[str, object]


class ProjectOperationPage(OperationModel):
    items: list[ProjectOperationResponse]
    next_cursor: str | None = Field(alias="nextCursor")
