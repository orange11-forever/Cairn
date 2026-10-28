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
from cairn_api.projects.operation_schemas import (
    ProjectOperationApplyRequest,
    ProjectOperationPage,
    ProjectOperationPreviewRequest,
    ProjectOperationPreviewResponse,
    ProjectOperationResponse,
)
from cairn_api.projects.operation_service import ProjectOperationService

router = APIRouter(prefix="/api/v1/projects", tags=["project-operations"])


@router.post(
    "/{project_id}/operation-preview",
    response_model=ProjectOperationPreviewResponse,
    responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def preview_project_operation(
    project_id: UUID,
    payload: ProjectOperationPreviewRequest,
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
    models: AnswerModelsDependency,
) -> ProjectOperationPreviewResponse:
    return ProjectOperationService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        audit,
        answer_models=models,
    ).preview(project_id, payload)


@router.post(
    "/{project_id}/operations",
    response_model=ProjectOperationResponse,
    status_code=201,
    responses={
        200: {"model": ProjectOperationResponse, "headers": REQUEST_ID_HEADER},
        201: {"headers": REQUEST_ID_HEADER},
        **ANSWER_ERRORS,
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def apply_project_operation(
    project_id: UUID,
    payload: ProjectOperationApplyRequest,
    request: Request,
    response: Response,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
) -> ProjectOperationResponse:
    result, created = ProjectOperationService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        audit,
    ).apply(project_id, payload)
    response.status_code = 201 if created else 200
    return result


@router.get(
    "/{project_id}/operations",
    response_model=ProjectOperationPage,
    responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
)
def list_project_operations(
    project_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=10, ge=1, le=20),
) -> ProjectOperationPage:
    return ProjectOperationService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        audit,
    ).list_operations(project_id, cursor, limit)


@router.get(
    "/{project_id}/operations/{operation_id}",
    response_model=ProjectOperationResponse,
    responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
)
def get_project_operation(
    project_id: UUID,
    operation_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
) -> ProjectOperationResponse:
    return ProjectOperationService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        audit,
    ).get(project_id, operation_id)
