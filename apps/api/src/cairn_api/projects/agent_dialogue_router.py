from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity
from cairn_api.knowledge.dependencies import AnswerModelsDependency
from cairn_api.knowledge.router import (
    ANSWER_ERRORS,
    REQUEST_ID_HEADER,
    AuditContext,
    SessionDependency,
    SettingsDependency,
)
from cairn_api.projects.agent_dialogue_schemas import (
    AgentDialogueApplyRequest,
    AgentDialogueContext,
    AgentDialoguePreviewRequest,
    AgentDialoguePreviewResponse,
)
from cairn_api.projects.agent_dialogue_service import AgentDialogueService
from cairn_api.projects.operation_schemas import ProjectOperationPage, ProjectOperationResponse

router = APIRouter(prefix="/api/v1/agent-dialogue", tags=["project-operations"])


def dialogue_service(request: Request, identity: CurrentIdentity, session: SessionDependency,
                     audit: AuditContext, settings: SettingsDependency,
                     models: AnswerModelsDependency) -> AgentDialogueService:
    return AgentDialogueService(session, identity, request.cookies.get(settings.session_cookie_name),
                                audit, answer_models=models)


Service = Annotated[AgentDialogueService, Depends(dialogue_service)]


@router.post("/preview", response_model=AgentDialoguePreviewResponse,
             responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
             dependencies=[Depends(require_mutation_csrf)], openapi_extra=CSRF_REQUIRED_OPENAPI)
def preview_dialogue(payload: AgentDialoguePreviewRequest, service: Service) -> AgentDialoguePreviewResponse:
    return service.preview_dialogue(payload)


@router.post("/operations", response_model=ProjectOperationResponse, status_code=201,
             responses={200: {"model": ProjectOperationResponse, "headers": REQUEST_ID_HEADER},
                        201: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
             dependencies=[Depends(require_mutation_csrf)], openapi_extra=CSRF_REQUIRED_OPENAPI)
def apply_dialogue(payload: AgentDialogueApplyRequest, response: Response, service: Service) -> ProjectOperationResponse:
    result, created = service.apply_dialogue(payload)
    response.status_code = 201 if created else 200
    return result


@router.get("/operations/{operation_id}", response_model=ProjectOperationResponse,
            responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS})
def get_dialogue_operation(operation_id: UUID, origin_project_id: UUID, target_project_id: UUID, service: Service,
                           assistant_id: UUID | None = None) -> ProjectOperationResponse:
    return service.get_dialogue_operation(
        AgentDialogueContext(originProjectId=origin_project_id, assistantId=assistant_id), operation_id, target_project_id,
    )


@router.get("/operations", response_model=ProjectOperationPage,
            responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS})
def list_dialogue_operations(origin_project_id: UUID, target_project_id: UUID, service: Service,
                             assistant_id: UUID | None = None,
                             cursor: str | None = Query(default=None, max_length=2048),
                             limit: int = Query(default=10, ge=1, le=20)) -> ProjectOperationPage:
    return service.list_dialogue_operations(
        AgentDialogueContext(originProjectId=origin_project_id, assistantId=assistant_id),
        target_project_id, cursor, limit,
    )
