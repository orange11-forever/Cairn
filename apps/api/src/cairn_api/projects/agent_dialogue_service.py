import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import assistant_repository
from cairn_api.knowledge.answer_models import selected_answer_model
from cairn_api.knowledge.answer_provider import (
    AnswerGuidance,
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
    ProjectOperationProvider,
)
from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings
from cairn_api.knowledge.assistant_schemas import AssistantSettingsResponse
from cairn_api.knowledge.conversation_service import safe_knowledge_operation
from cairn_api.projects import task_repository
from cairn_api.projects.agent_dialogue_schemas import (
    AgentDialogueApplyRequest,
    AgentDialogueContext,
    AgentDialoguePreviewRequest,
    AgentDialoguePreviewResponse,
)
from cairn_api.projects.creation_service import ProjectCreationService
from cairn_api.projects.operation_models import ProjectOperation
from cairn_api.projects.operation_schemas import (
    AssignTaskAction,
    CreateProjectAction,
    DispatchTaskAction,
    ProjectCreationApplyRequest,
    ProjectCreationPreviewResponse,
    ProjectOperationApplyRequest,
    ProjectOperationPreviewResponse,
    ProjectOperationResponse,
)
from cairn_api.projects.operation_service import ProjectOperationService
from cairn_api.projects.service import ProjectService, _not_found

# pyright: reportPrivateUsage=false


class AgentDialogueService(ProjectCreationService):
    """Ephemeral proposals with pinned private profiles and existing durable receipts."""

    _agent: AgentDialogueContext
    _expected_assistant: AssistantSettingsResponse | None = None
    _dialogue_preview: AgentDialoguePreviewResponse | None = None

    @staticmethod
    def _configuration(assistant: AssistantSettingsResponse) -> dict[str, object]:
        # Selecting a profile changes its global active revision, not its behavior.
        return assistant.model_dump(exclude={"revision"})

    def _source(self) -> AssistantSettingsResponse:
        ProjectService(self._session)._lock_organization(self._identity)
        self._identity = self._authorize(self._agent.origin_project_id)
        row = None
        if self._agent.assistant_id is not None:
            row = self._session.scalar(select(KnowledgeAssistantSettings).where(
                KnowledgeAssistantSettings.org_id == self._identity.organization.id,
                KnowledgeAssistantSettings.project_id == self._agent.origin_project_id,
                KnowledgeAssistantSettings.owner_id == self._identity.user.id,
                KnowledgeAssistantSettings.id == self._agent.assistant_id,
            ).with_for_update())
            if row is None:
                raise _not_found()
        assistant = assistant_repository.settings_response(row)
        if self._expected_assistant is not None and self._configuration(assistant) != self._configuration(self._expected_assistant):
            raise assistant_repository.assistant_changed()
        return assistant

    def _guard(self, project_id: UUID, *, write: bool = False) -> None:
        self._source()
        super()._guard(project_id, write=write)

    def _creation_guard(self, *, write: bool = True) -> None:
        self._source()
        super()._creation_guard(write=write)
        if self._dialogue_preview is not None:
            super()._guard(self._dialogue_preview.target_project_id)

    def _receipt_digest(self, preview: BaseModel) -> bytes:
        return super()._receipt_digest(self._dialogue_preview or preview)

    def _receipt_scope(self, working_project_id: UUID) -> dict[str, object]:
        return {**self._agent.model_dump(mode="json", by_alias=True), "workingProjectId": str(working_project_id)}

    def _receipt_attribution(self) -> dict[str, object]:
        assert self._dialogue_preview is not None
        return {"agentDialogue": self._receipt_scope(self._dialogue_preview.target_project_id)}

    def _dialogue_record(self, operation_id: UUID, working_project_id: UUID) -> ProjectOperation | None:
        return self._session.scalar(select(ProjectOperation).where(
            ProjectOperation.org_id == self._identity.organization.id,
            ProjectOperation.owner_id == self._identity.user.id,
            ProjectOperation.id == operation_id,
            ProjectOperation.details["agentDialogue"].contains(self._receipt_scope(working_project_id)),
        ))

    def _creation_record(self, operation_id: UUID) -> ProjectOperation | None:
        assert self._dialogue_preview is not None
        return self._dialogue_record(operation_id, self._dialogue_preview.target_project_id)

    def list_dialogue_operations(self, agent: AgentDialogueContext, target_project_id: UUID,
                                 cursor: str | None, limit: int):
        self._agent = agent
        return self.list_operations(target_project_id, cursor, limit)

    def _receipt_record(self, project_id: UUID, operation_id: UUID) -> ProjectOperation | None:
        scoped = self._dialogue_record(operation_id, project_id)
        if scoped is not None:
            return scoped
        # The existing table key has no Agent column. A colliding identifier
        # in another dialogue must conflict instead of attempting a duplicate insert.
        return self._session.scalar(ProjectOperationService._records(self, project_id).where(
            ProjectOperation.id == operation_id,
        ))

    def _records(self, project_id: UUID):
        return super()._records(project_id).where(
            ProjectOperation.details["agentDialogue"].contains(self._agent.model_dump(mode="json", by_alias=True))
        )

    @safe_knowledge_operation
    def preview_dialogue(self, payload: AgentDialoguePreviewRequest) -> AgentDialoguePreviewResponse:
        self._agent = payload.agent
        with self._session.begin():
            assistant = self._source()
            self._expected_assistant = assistant
            super()._guard(payload.target_project_id)
            snapshot = self._snapshot(payload.target_project_id)
            members, cursor = task_repository.list_assignees(
                self._session, org_id=self._identity.organization.id, project_id=payload.target_project_id,
                requester_id=self._identity.user.id, cursor=None, limit=100,
            )
            assignees = {user.id: user.display_name or str(user.id) for _, user in members}
            agents: dict[UUID | None, str] = {row.id: row.name for row in assistant_repository.assistant_rows(
                self._session, self._identity.organization.id, payload.target_project_id, self._identity.user.id,
            )}
            active_target = assistant_repository.settings_row(
                self._session, self._identity.organization.id,
                payload.target_project_id, self._identity.user.id,
            )
            if active_target is None:
                agents[None] = "岑宁"
            model = selected_answer_model(self._answer_models, assistant.model_id)
            model_snapshot = snapshot.model_dump(mode="json", by_alias=True)
            model_snapshot.update({
                "scope": "agent_dialogue",
                "dialogueHistory": [message.model_dump() for message in payload.history],
                "assignees": [{"userId": str(key), "displayName": value} for key, value in assignees.items()],
                "assigneesComplete": cursor is None,
                "codingAssistants": [{"assistantId": str(key) if key else None, "name": value} for key, value in agents.items()],
            })
        try:
            if not callable(getattr(model.provider, "suggest_project_operation", None)):
                raise AnswerProviderUnavailable()
            suggestion = cast(ProjectOperationProvider, model.provider).suggest_project_operation(
                intent=payload.intent, snapshot=json.dumps(model_snapshot, ensure_ascii=False),
                guidance=AnswerGuidance(assistant_name=assistant.name, instructions=assistant.instructions,
                                        skill_id=None, skill_instructions="", resources=[]),
            )
            if isinstance(suggestion.action, AssignTaskAction):
                if suggestion.action.assignee_user_id is not None and suggestion.action.assignee_user_id not in assignees:
                    raise AnswerProviderInvalidResponse()
                suggestion.action.assignee_name = assignees.get(suggestion.action.assignee_user_id) if suggestion.action.assignee_user_id else None
            if isinstance(suggestion.action, DispatchTaskAction):
                if suggestion.action.assistant_id not in agents:
                    raise AnswerProviderInvalidResponse()
                suggestion.action.assistant_name = agents[suggestion.action.assistant_id]
            if isinstance(suggestion.action, CreateProjectAction):
                preview = ProjectCreationPreviewResponse(
                    organizationId=self._identity.organization.id, intent=payload.intent,
                    generatedAt=datetime.now(UTC), model=model.info, suggestion=suggestion,
                )
            else:
                preview = ProjectOperationPreviewResponse(
                    projectId=payload.target_project_id, assistantName=assistant.name,
                    snapshot=snapshot, canExecute=False, intent=payload.intent,
                    generatedAt=datetime.now(UTC), model=model.info, suggestion=suggestion,
                )
        except (AnswerProviderUnavailable, AnswerProviderInvalidResponse, ValidationError):
            raise ApiProblem(status_code=503, code="answer_unavailable", message="智能体建议暂时不可用，请稍后重试") from None
        with self._session.begin():
            self._source()
            self._check_inputs(payload.target_project_id, snapshot, [])
            if isinstance(preview, ProjectCreationPreviewResponse):
                self._policy.require_project_creation(self._identity)
            else:
                preview.can_execute = self._policy.find_project(
                    self._identity, payload.target_project_id, ProjectPermission.WRITE, for_update=True,
                ) is not None
        return AgentDialoguePreviewResponse(agent=payload.agent, targetProjectId=payload.target_project_id,
                                             assistant=assistant, preview=preview)

    def apply_dialogue(self, payload: AgentDialogueApplyRequest) -> tuple[ProjectOperationResponse, bool]:
        self._agent = payload.preview.agent
        self._expected_assistant = payload.preview.assistant
        self._dialogue_preview = payload.preview
        if isinstance(payload.preview.preview, ProjectCreationPreviewResponse):
            return self.apply_creation(ProjectCreationApplyRequest(
                operationId=payload.operation_id, confirmed=True, preview=payload.preview.preview,
            ))
        return self.apply(payload.preview.target_project_id, ProjectOperationApplyRequest(
            operationId=payload.operation_id, confirmed=True, preview=payload.preview.preview,
        ))

    @safe_knowledge_operation
    def get_dialogue_operation(self, agent: AgentDialogueContext, operation_id: UUID, target_project_id: UUID) -> ProjectOperationResponse:
        self._agent = agent
        with self._session.begin():
            self._source()
            super()._guard(target_project_id)
            row = self._dialogue_record(operation_id, target_project_id)
            if row is None:
                raise _not_found()
            super()._guard(row.project_id)
            return self._response(row)
