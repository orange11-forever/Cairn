from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity
from cairn_api.errors import ErrorBody
from cairn_api.projects.router import (
    AUTHENTICATED_ERRORS,
    MUTATION_ERRORS,
    AuditContext,
    SessionDependency,
)
from cairn_api.projects.schedule_schemas import (
    ProjectCapacityUpdateRequest,
    ProjectScheduleResponse,
)
from cairn_api.projects.schedule_service import ProjectScheduleService
from cairn_api.projects.schemas import ProjectResponse

router = APIRouter(prefix="/api/v1/projects", tags=["project-scheduling"])


@router.patch(
    "/{project_id}/capacity",
    response_model=ProjectResponse,
    responses={
        **MUTATION_ERRORS,
        404: {"description": "项目不存在", "model": ErrorBody},
        409: {"description": "项目版本冲突", "model": ErrorBody},
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def update_project_capacity(
    project_id: UUID,
    payload: ProjectCapacityUpdateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> ProjectResponse:
    return ProjectScheduleService(session).update_capacity(
        identity=identity, project_id=project_id, payload=payload, audit=audit
    )


@router.get(
    "/{project_id}/schedule-scenario",
    response_model=ProjectScheduleResponse,
    responses={**AUTHENTICATED_ERRORS, 404: {"description": "项目不存在", "model": ErrorBody}},
)
def project_schedule_scenario(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    start_date: str = Query(alias="startDate", pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> ProjectScheduleResponse:
    from cairn_api.errors import ApiProblem

    try:
        parsed = date.fromisoformat(start_date)
    except ValueError:
        raise ApiProblem(
            status_code=422,
            code="validation_error",
            message="startDate必须是有效日期（YYYY-MM-DD）",
        ) from None
    return ProjectScheduleService(session).scenario(
        identity=identity, project_id=project_id, start_date=parsed
    )
