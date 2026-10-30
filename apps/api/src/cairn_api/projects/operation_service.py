import hashlib
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import ValidationError
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
from cairn_api.knowledge.conversation_service import safe_knowledge_operation
from cairn_api.pagination import load_cursor_page, page_by_timestamp
from cairn_api.projects.analysis_service import ProjectAnalysisService, analysis_changed
from cairn_api.projects.operation_models import ProjectOperation
from cairn_api.projects.operation_schemas import (
    AddDependencyAction,
    ChangeStatusAction,
    CreateTaskAction,
    ProjectOperationApplyRequest,
    ProjectOperationPage,
    ProjectOperationPreviewRequest,
    ProjectOperationPreviewResponse,
    ProjectOperationResponse,
    RemoveDependencyAction,
    UpdateTaskAction,
)
from cairn_api.projects.schemas import TaskUpdateRequest
from cairn_api.projects.service import ProjectService, _not_found

# pyright: reportPrivateUsage=false


class ProjectOperationService(ProjectAnalysisService):
    def _guard(self, project_id: UUID, *, write: bool = False) -> None:
        ProjectService(self._session)._lock_organization(self._identity)
        identity = self._authorize(project_id)
        if write:
            self._policy.require_project(
                identity, project_id, ProjectPermission.WRITE, for_update=True
            )

    @safe_knowledge_operation
    def preview(
        self, project_id: UUID, payload: ProjectOperationPreviewRequest
    ) -> ProjectOperationPreviewResponse:
        with self._session.begin():
            self._guard(project_id)
            snapshot = self._snapshot(project_id)
            assistant = assistant_repository.settings_response(
                assistant_repository.settings_row(
                    self._session,
                    self._identity.organization.id,
                    project_id,
                    self._identity.user.id,
                )
            )
            model = selected_answer_model(self._answer_models, assistant.model_id)
        try:
            if not callable(getattr(model.provider, "suggest_project_operation", None)):
                raise AnswerProviderUnavailable()
            suggestion = cast(ProjectOperationProvider, model.provider).suggest_project_operation(
                intent=payload.intent,
                snapshot=snapshot.model_dump_json(by_alias=True),
                guidance=AnswerGuidance(
                    assistant_name=assistant.name,
                    instructions=assistant.instructions,
                    skill_id=None,
                    skill_instructions="",
                    resources=[],
                ),
            )
            response = ProjectOperationPreviewResponse(
                projectId=project_id,
                intent=payload.intent,
                generatedAt=datetime.now(UTC),
                assistantName=assistant.name,
                model=model.info,
                snapshot=snapshot,
                suggestion=suggestion,
                canExecute=False,
            )
        except (AnswerProviderUnavailable, AnswerProviderInvalidResponse, ValidationError):
            raise ApiProblem(
                status_code=503, code="answer_unavailable", message="操作建议暂时不可用，请稍后重试"
            ) from None
        with self._session.begin():
            self._check_inputs(project_id, snapshot, [])
            response.can_execute = (
                self._policy.find_project(
                    self._identity, project_id, ProjectPermission.WRITE, for_update=True
                )
                is not None
            )
            ProjectService(self._session)._audit(
                identity=self._identity,
                audit=self._audit,
                action="project.operation_previewed",
                resource_type="project",
                resource_id=project_id,
            )
        return response

    def _records(self, project_id: UUID):
        return select(ProjectOperation).where(
            ProjectOperation.org_id == self._identity.organization.id,
            ProjectOperation.project_id == project_id,
            ProjectOperation.owner_id == self._identity.user.id,
        )

    @staticmethod
    def _response(row: ProjectOperation) -> ProjectOperationResponse:
        return ProjectOperationResponse.model_validate(
            {
                "operationId": row.id,
                "projectId": row.project_id,
                "generatedAt": row.generated_at,
                "appliedAt": row.created_at,
                **row.details,
            }
        )

    @safe_knowledge_operation
    def get(self, project_id: UUID, operation_id: UUID) -> ProjectOperationResponse:
        with self._session.begin():
            self._guard(project_id)
            row = self._session.scalar(
                self._records(project_id).where(ProjectOperation.id == operation_id)
            )
            if row is None:
                raise _not_found()
            return self._response(row)

    @safe_knowledge_operation
    def list_operations(
        self, project_id: UUID, cursor: str | None, limit: int
    ) -> ProjectOperationPage:
        with self._session.begin():
            self._guard(project_id)
            rows, next_cursor = load_cursor_page(
                lambda: page_by_timestamp(
                    self._session,
                    self._records(project_id),
                    timestamp_column=ProjectOperation.created_at,
                    id_column=ProjectOperation.id,
                    cursor=cursor,
                    limit=limit,
                    descending=True,
                )
            )
            return ProjectOperationPage(
                items=[self._response(row) for row in rows], nextCursor=next_cursor
            )

    @safe_knowledge_operation
    def apply(
        self, project_id: UUID, payload: ProjectOperationApplyRequest
    ) -> tuple[ProjectOperationResponse, bool]:
        preview = payload.preview
        digest = hashlib.sha256(
            json.dumps(
                preview.model_dump(mode="json", by_alias=True),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).digest()
        with self._session.begin():
            self._guard(project_id, write=True)
            existing = self._session.scalar(
                self._records(project_id).where(ProjectOperation.id == payload.operation_id)
            )
            if existing is not None:
                if existing.request_digest != digest:
                    raise ApiProblem(
                        status_code=409,
                        code="operation_conflict",
                        message="此操作编号已用于另一项操作，请重新确认",
                    )
                return self._response(existing), False
            if preview.project_id != project_id:
                raise analysis_changed()
            self._check_inputs(project_id, preview.snapshot, [])
            writer = ProjectService(self._session)
            identity, audit = self._identity, self._audit
            action = preview.suggestion.action
            assert action is not None
            revisions = {task.id: task.revision for task in preview.snapshot.tasks}
            if isinstance(action, CreateTaskAction):
                result = writer._create_task_in_transaction(
                    identity=identity,
                    project_id=project_id,
                    audit=audit,
                    title=action.title,
                    description=action.description,
                    priority=action.priority,
                    stage_id=action.stage_id,
                    milestone_id=action.milestone_id,
                    acceptance_criteria=action.acceptance_criteria,
                    parent_task_id=None,
                    due_at=None,
                    expected_project_revision=preview.snapshot.project.revision,
                ).model_dump(mode="json", by_alias=True)
            elif isinstance(action, UpdateTaskAction):
                result = writer._update_task_in_transaction(
                    identity=identity,
                    task_id=action.task_id,
                    audit=audit,
                    payload=TaskUpdateRequest.model_validate(
                        {
                            "expectedRevision": revisions[action.task_id],
                            action.field: action.value,
                        }
                    ),
                ).model_dump(mode="json", by_alias=True)
            elif isinstance(action, ChangeStatusAction):
                result = writer._transition_task_in_transaction(
                    identity=identity,
                    task_id=action.task_id,
                    requested_status=action.status,
                    expected_revision=revisions[action.task_id],
                    audit=audit,
                ).model_dump(mode="json", by_alias=True)
            elif isinstance(action, AddDependencyAction):
                result = writer._add_dependency_in_transaction(
                    identity=identity,
                    predecessor_task_id=action.predecessor_task_id,
                    successor_task_id=action.successor_task_id,
                    expected_revision=revisions[action.successor_task_id],
                    audit=audit,
                ).model_dump(mode="json", by_alias=True)
            else:
                assert isinstance(action, RemoveDependencyAction)
                edge = next(
                    edge
                    for edge in preview.snapshot.dependencies
                    if edge.id == action.dependency_id
                )
                writer._delete_dependency_in_transaction(
                    identity=identity,
                    task_id=action.task_id,
                    dependency_id=action.dependency_id,
                    expected_revision=revisions[action.task_id],
                    audit=audit,
                )
                result = {
                    "taskId": str(action.task_id),
                    "dependencyId": str(action.dependency_id),
                    "predecessorTaskId": str(edge.predecessor_task_id),
                    "successorTaskId": str(edge.successor_task_id),
                    "removed": True,
                }
            if isinstance(action, (AddDependencyAction, RemoveDependencyAction)):
                titles = {str(task.id): task.title for task in preview.snapshot.tasks}
                result["predecessorTitle"] = titles[str(result["predecessorTaskId"])]
                result["successorTitle"] = titles[str(result["successorTaskId"])]
            writer._audit(
                identity=identity,
                audit=audit,
                action="project.operation_applied",
                resource_type="project",
                resource_id=project_id,
            )
            saved = ProjectOperation(
                id=payload.operation_id,
                org_id=identity.organization.id,
                project_id=project_id,
                owner_id=identity.user.id,
                request_digest=digest,
                generated_at=preview.generated_at,
                details={
                    "intent": preview.intent,
                    "action": action.model_dump(mode="json", by_alias=True),
                    "explanation": preview.suggestion.explanation,
                    "result": result,
                },
            )
            self._session.add(saved)
            self._session.flush()
            response = self._response(saved)
        return response, True
