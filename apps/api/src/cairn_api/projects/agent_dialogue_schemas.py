from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from cairn_api.knowledge.assistant_schemas import AssistantSettingsResponse
from cairn_api.projects.operation_schemas import (
    DispatchTaskAction,
    OperationModel,
    ProjectCreationPreviewResponse,
    ProjectOperationPreviewResponse,
)


class AgentDialogueContext(OperationModel):
    origin_project_id: UUID = Field(alias="originProjectId")
    assistant_id: UUID | None = Field(alias="assistantId")


class AgentDialogueMessage(OperationModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class AgentDialoguePreviewRequest(OperationModel):
    agent: AgentDialogueContext
    target_project_id: UUID = Field(alias="targetProjectId")
    intent: str = Field(min_length=1, max_length=2000)
    history: list[AgentDialogueMessage] = Field(default_factory=list[AgentDialogueMessage], max_length=12)


class AgentDialoguePreviewResponse(OperationModel):
    agent: AgentDialogueContext
    target_project_id: UUID = Field(alias="targetProjectId")
    assistant: AssistantSettingsResponse
    preview: ProjectOperationPreviewResponse | ProjectCreationPreviewResponse

    @model_validator(mode="after")
    def valid_context(self) -> "AgentDialoguePreviewResponse":
        if self.assistant.id != self.agent.assistant_id:
            raise ValueError("assistant identity mismatch")
        if isinstance(self.preview, ProjectOperationPreviewResponse) and self.preview.project_id != self.target_project_id:
            raise ValueError("target project mismatch")
        return self


class AgentDialogueApplyRequest(OperationModel):
    operation_id: UUID = Field(alias="operationId")
    confirmed: Literal[True]
    preview: AgentDialoguePreviewResponse

    @model_validator(mode="after")
    def require_proposed(self) -> "AgentDialogueApplyRequest":
        if self.preview.preview.suggestion.status != "proposed":
            raise ValueError("only proposed actions may be confirmed")
        if isinstance(self.preview.preview.suggestion.action, DispatchTaskAction):
            raise ValueError("coding tasks must be confirmed in the coding workspace")  # noqa: TRY004
        return self
