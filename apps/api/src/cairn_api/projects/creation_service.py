import hashlib
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.answer_models import selected_answer_model
from cairn_api.knowledge.answer_provider import (
    AnswerGuidance,
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
    ProjectOperationProvider,
)
from cairn_api.knowledge.conversation_service import safe_knowledge_operation
from cairn_api.projects.operation_models import ProjectOperation
from cairn_api.projects.operation_schemas import (
    CreateProjectAction,
    ProjectCreationApplyRequest,
    ProjectCreationPreviewResponse,
    ProjectOperationPreviewRequest,
    ProjectOperationResponse,
)
from cairn_api.projects.operation_service import ProjectOperationService
from cairn_api.projects.service import ProjectService, _not_found

# pyright: reportPrivateUsage=false


class ProjectCreationService(ProjectOperationService):
    def _creation_guard(self, *, write: bool = True) -> None:
        # Serialize receipt lookup and creation with membership changes. The receipt
        # and new project commit together, so a lost response cannot create a duplicate.
        ProjectService(self._session)._lock_organization(self._identity)
        self._session.expire_all()
        self._identity = self._authorize_identity()
        if write:
            self._policy.require_project_creation(self._identity)

    def _creation_record(self, operation_id: UUID) -> ProjectOperation | None:
        return self._session.scalar(select(ProjectOperation).where(
            ProjectOperation.org_id == self._identity.organization.id,
            ProjectOperation.owner_id == self._identity.user.id,
            ProjectOperation.id == operation_id,
            ProjectOperation.details["action"]["type"].astext == "create_project",
        ))

    @safe_knowledge_operation
    def preview_creation(self, payload: ProjectOperationPreviewRequest) -> ProjectCreationPreviewResponse:
        with self._session.begin():
            self._creation_guard()
            model = selected_answer_model(self._answer_models, None)
        try:
            if not callable(getattr(model.provider, "suggest_project_operation", None)):
                raise AnswerProviderUnavailable()
            suggestion = cast(ProjectOperationProvider, model.provider).suggest_project_operation(
                intent=payload.intent, snapshot='{"scope":"project_creation"}',
                guidance=AnswerGuidance(assistant_name="岑宁", instructions="", skill_id=None,
                                        skill_instructions="", resources=[]),
            )
            result = ProjectCreationPreviewResponse(
                organizationId=self._identity.organization.id,
                intent=payload.intent, generatedAt=datetime.now(UTC), model=model.info,
                suggestion=suggestion,
            )
        except (AnswerProviderUnavailable, AnswerProviderInvalidResponse, ValidationError):
            raise ApiProblem(status_code=503, code="answer_unavailable",
                             message="项目创建建议暂时不可用，请稍后重试") from None
        with self._session.begin():
            self._creation_guard()
        return result

    @safe_knowledge_operation
    def get_creation(self, operation_id: UUID) -> ProjectOperationResponse:
        with self._session.begin():
            self._creation_guard(write=False)
            row = self._creation_record(operation_id)
            if row is None:
                raise _not_found()
            self._policy.require_project(self._identity, row.project_id, ProjectPermission.READ)
            return self._response(row)

    @safe_knowledge_operation
    def apply_creation(self, payload: ProjectCreationApplyRequest) -> tuple[ProjectOperationResponse, bool]:
        preview = payload.preview
        digest = hashlib.sha256(json.dumps(
            preview.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":")
        ).encode()).digest()
        with self._session.begin():
            self._creation_guard()
            if preview.organization_id != self._identity.organization.id:
                raise _not_found()
            existing = self._creation_record(payload.operation_id)
            if existing is not None:
                self._policy.require_project(self._identity, existing.project_id, ProjectPermission.READ)
                if existing.request_digest != digest:
                    raise ApiProblem(status_code=409, code="operation_conflict",
                                     message="此操作编号已用于另一项创建，请查询原结果")
                return self._response(existing), False
            action = preview.suggestion.action
            assert isinstance(action, CreateProjectAction)
            project = ProjectService(self._session)._create_project_in_transaction(
                identity=self._identity, name=action.name, description=action.description, audit=self._audit,
            )
            row = ProjectOperation(
                org_id=self._identity.organization.id, project_id=project.id,
                owner_id=self._identity.user.id, id=payload.operation_id, request_digest=digest,
                generated_at=preview.generated_at,
                details={"intent": preview.intent, "action": action.model_dump(mode="json", by_alias=True),
                         "explanation": preview.suggestion.explanation,
                         "result": project.model_dump(mode="json", by_alias=True)},
            )
            self._session.add(row)
            self._session.flush()
            result = self._response(row)
        return result, True
