from uuid import UUID

from fastapi import APIRouter, Depends, Request

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
