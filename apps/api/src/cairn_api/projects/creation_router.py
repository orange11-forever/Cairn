from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

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
from cairn_api.projects.creation_service import ProjectCreationService
from cairn_api.projects.operation_schemas import (
    ProjectCreationApplyRequest,
    ProjectCreationPreviewResponse,
    ProjectOperationPreviewRequest,
    ProjectOperationResponse,
)

router = APIRouter(prefix="/api/v1/project-creations", tags=["project-operations"])


def creation_service(request: Request, identity: CurrentIdentity, session: SessionDependency,
                     audit: AuditContext, settings: SettingsDependency,
                     models: AnswerModelsDependency) -> ProjectCreationService:
    return ProjectCreationService(session, identity, request.cookies.get(settings.session_cookie_name),
                                  audit, answer_models=models)


Service = Annotated[ProjectCreationService, Depends(creation_service)]


@router.post("/preview", response_model=ProjectCreationPreviewResponse,
             responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
             dependencies=[Depends(require_mutation_csrf)], openapi_extra=CSRF_REQUIRED_OPENAPI)
def preview_creation(payload: ProjectOperationPreviewRequest, service: Service) -> ProjectCreationPreviewResponse:
    return service.preview_creation(payload)


@router.post("", response_model=ProjectOperationResponse, status_code=201,
             responses={200: {"model": ProjectOperationResponse, "headers": REQUEST_ID_HEADER},
                        201: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
             dependencies=[Depends(require_mutation_csrf)], openapi_extra=CSRF_REQUIRED_OPENAPI)
def apply_creation(payload: ProjectCreationApplyRequest, response: Response, service: Service) -> ProjectOperationResponse:
    result, created = service.apply_creation(payload)
    response.status_code = 201 if created else 200
    return result


@router.get("/{operation_id}", response_model=ProjectOperationResponse,
            responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS})
def get_creation(operation_id: UUID, service: Service) -> ProjectOperationResponse:
    return service.get_creation(operation_id)
