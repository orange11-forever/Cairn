from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity
from cairn_api.knowledge.dependencies import AnswerModelsDependency, EmbeddingClientDependency
from cairn_api.knowledge.router import (
    ANSWER_ERRORS,
    REQUEST_ID_HEADER,
    AuditContext,
    SessionDependency,
    SettingsDependency,
)
from cairn_api.knowledge.search_service import KnowledgeSearchService
from cairn_api.projects.analysis_schemas import ProjectAnalysisResponse, ProjectPlanPreviewResponse
from cairn_api.projects.analysis_service import ProjectAnalysisService
from cairn_api.projects.plan_schemas import (
    ProjectPlanApplicationPage,
    ProjectPlanApplicationResponse,
    ProjectPlanApplyRequest,
)
from cairn_api.projects.plan_service import ProjectPlanService

router = APIRouter(prefix="/api/v1/projects", tags=["project-analysis"])


@router.post(
    "/{project_id}/analysis",
    response_model=ProjectAnalysisResponse,
    responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def analyze_project(
    project_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
    embedding: EmbeddingClientDependency,
    models: AnswerModelsDependency,
) -> ProjectAnalysisResponse:
    search = KnowledgeSearchService(
        session,
        embedding,
        user_limit=settings.search_user_limit_per_minute,
        org_limit=settings.search_org_limit_per_minute,
        audit_secret=settings.search_audit_secret.get_secret_value(),
    )
    return ProjectAnalysisService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        audit,
        answer_models=models,
    ).analyze(project_id, search)


@router.post(
    "/{project_id}/plan-preview",
    response_model=ProjectPlanPreviewResponse,
    responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def preview_project_plan(
    project_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
    embedding: EmbeddingClientDependency,
    models: AnswerModelsDependency,
) -> ProjectPlanPreviewResponse:
    search = KnowledgeSearchService(
        session,
        embedding,
        user_limit=settings.search_user_limit_per_minute,
        org_limit=settings.search_org_limit_per_minute,
        audit_secret=settings.search_audit_secret.get_secret_value(),
    )
    return ProjectAnalysisService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        audit,
        answer_models=models,
    ).preview_plan(project_id, search)


@router.post(
    "/{project_id}/plans",
    response_model=ProjectPlanApplicationResponse,
    status_code=201,
    responses={
        200: {"model": ProjectPlanApplicationResponse, "headers": REQUEST_ID_HEADER},
        201: {"headers": REQUEST_ID_HEADER},
        **ANSWER_ERRORS,
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def apply_project_plan(
    project_id: UUID,
    payload: ProjectPlanApplyRequest,
    request: Request,
    response: Response,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
) -> ProjectPlanApplicationResponse:
    result, created = ProjectPlanService(
        session, identity, request.cookies.get(settings.session_cookie_name), audit
    ).apply(project_id, payload)
    response.status_code = 201 if created else 200
    return result


@router.get(
    "/{project_id}/plans",
    response_model=ProjectPlanApplicationPage,
    responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
)
def list_applied_project_plans(
    project_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=10, ge=1, le=20),
) -> ProjectPlanApplicationPage:
    return ProjectPlanService(
        session, identity, request.cookies.get(settings.session_cookie_name), audit
    ).list_plans(project_id, cursor, limit)


@router.get(
    "/{project_id}/plans/{operation_id}",
    response_model=ProjectPlanApplicationResponse,
    responses={200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS},
)
def get_applied_project_plan(
    project_id: UUID,
    operation_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
) -> ProjectPlanApplicationResponse:
    return ProjectPlanService(
        session, identity, request.cookies.get(settings.session_cookie_name), audit
    ).get(project_id, operation_id)
