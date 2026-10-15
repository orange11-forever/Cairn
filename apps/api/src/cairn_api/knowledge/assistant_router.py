from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI
from cairn_api.auth.dependencies import CurrentIdentity
from cairn_api.knowledge.assistant_schemas import (
    AssistantCatalogResponse,
    AssistantSelectionRequest,
    AssistantSettingsRequest,
    AssistantSettingsResponse,
    KnowledgeSkillCatalogResponse,
    KnowledgeSkillImportResponse,
    KnowledgeSkillPreview,
    SkillImportRequest,
    SkillPreviewRequest,
)
from cairn_api.knowledge.assistant_service import KnowledgeAssistantService
from cairn_api.knowledge.conversation_router import MUTATION, RESPONSES
from cairn_api.knowledge.dependencies import AnswerModelsDependency
from cairn_api.knowledge.router import (
    ANSWER_ERRORS,
    REQUEST_ID_HEADER,
    AuditContext,
    SessionDependency,
    SettingsDependency,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/knowledge", tags=["knowledge-assistant"])


def get_service(
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
    models: AnswerModelsDependency,
) -> KnowledgeAssistantService:
    return KnowledgeAssistantService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        audit,
        answer_models=models,
    )


Service = Annotated[KnowledgeAssistantService, Depends(get_service)]


@router.get("/assistants", response_model=AssistantCatalogResponse, responses=RESPONSES)
def list_assistants(project_id: UUID, service: Service) -> AssistantCatalogResponse:
    return service.list_assistants(project_id)


@router.post(
    "/assistants",
    response_model=AssistantSettingsResponse,
    status_code=201,
    responses={201: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
    dependencies=MUTATION,
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def create_assistant(
    project_id: UUID, payload: AssistantSettingsRequest, service: Service
) -> AssistantSettingsResponse:
    return service.create_assistant(project_id, payload)


@router.post(
    "/assistants/{assistant_id}/select",
    response_model=AssistantSettingsResponse,
    responses=RESPONSES,
    dependencies=MUTATION,
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def select_assistant(
    project_id: UUID, assistant_id: UUID, payload: AssistantSelectionRequest, service: Service
) -> AssistantSettingsResponse:
    return service.select_assistant(project_id, assistant_id, payload.expected_revision)


@router.get("/assistant-settings", response_model=AssistantSettingsResponse, responses=RESPONSES)
def get_assistant_settings(project_id: UUID, service: Service) -> AssistantSettingsResponse:
    return service.get_settings(project_id)


@router.put(
    "/assistant-settings",
    response_model=AssistantSettingsResponse,
    responses=RESPONSES,
    dependencies=MUTATION,
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def save_assistant_settings(
    project_id: UUID, payload: AssistantSettingsRequest, service: Service
) -> AssistantSettingsResponse:
    return service.save_settings(project_id, payload)


@router.get("/skills", response_model=KnowledgeSkillCatalogResponse, responses=RESPONSES)
def list_skills(project_id: UUID, service: Service) -> KnowledgeSkillCatalogResponse:
    return service.list_skills(project_id)


@router.post(
    "/skills/preview",
    response_model=KnowledgeSkillPreview,
    responses=RESPONSES,
    dependencies=MUTATION,
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def preview_import(
    project_id: UUID, payload: SkillPreviewRequest, service: Service
) -> KnowledgeSkillPreview:
    return service.preview(project_id, payload.source)


@router.post(
    "/skills/import",
    response_model=KnowledgeSkillImportResponse,
    status_code=201,
    responses={
        **RESPONSES,
        200: {"model": KnowledgeSkillImportResponse, "headers": REQUEST_ID_HEADER},
        201: {"headers": REQUEST_ID_HEADER},
    },
    dependencies=MUTATION,
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def import_skill(
    project_id: UUID, payload: SkillImportRequest, response: Response, service: Service
) -> KnowledgeSkillImportResponse:
    result, created = service.import_skill(project_id, payload)
    response.status_code = 201 if created else 200
    return result
