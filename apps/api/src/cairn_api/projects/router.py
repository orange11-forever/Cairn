from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import (
    CurrentIdentity,
    get_audit_context,
)
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.session import get_db
from cairn_api.errors import ErrorBody
from cairn_api.pagination import load_cursor_page
from cairn_api.projects.events import materialize_project_event_frames
from cairn_api.projects.schemas import (
    DependencyResponse,
    ProjectCreateRequest,
    ProjectPage,
    ProjectResponse,
    TaskCreateRequest,
    TaskDependencyCreateRequest,
    TaskPage,
    TaskResponse,
    TaskStatusUpdateRequest,
)
from cairn_api.projects.service import ProjectService

router = APIRouter(prefix="/api/v1", tags=["projects"])
SessionDependency = Annotated[Session, Depends(get_db)]
AuditContext = Annotated[RequestAuditContext, Depends(get_audit_context)]
Cursor = Annotated[str | None, Query(max_length=2048)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
EventCursor = Annotated[str | None, Query(max_length=2048)]

AUTHENTICATED_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "会话无效", "model": ErrorBody},
    422: {"description": "请求参数无效", "model": ErrorBody},
    503: {"description": "数据库暂时不可用", "model": ErrorBody},
}
MUTATION_ERRORS: dict[int | str, dict[str, Any]] = {
    **AUTHENTICATED_ERRORS,
    403: {"description": "请求来源或 CSRF 令牌无效", "model": ErrorBody},
}
@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    responses=MUTATION_ERRORS,
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def create_project(
    payload: ProjectCreateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> ProjectResponse:
    return ProjectService(session).create_project(
        identity=identity,
        name=payload.name,
        description=payload.description,
        audit=audit,
    )


@router.get(
    "/projects",
    response_model=ProjectPage,
    responses=AUTHENTICATED_ERRORS,
)
def list_projects(
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> ProjectPage:
    return load_cursor_page(
        lambda: ProjectService(session).list_projects(
            identity=identity,
            cursor=cursor,
            limit=limit,
        ),
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    responses={
        **AUTHENTICATED_ERRORS,
        404: {"description": "项目不存在", "model": ErrorBody},
    },
)
def get_project(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
) -> ProjectResponse:
    return ProjectService(session).get_project(
        identity=identity,
        project_id=project_id,
    )


@router.get(
    "/projects/{project_id}/events",
    response_class=StreamingResponse,
    responses={
        **AUTHENTICATED_ERRORS,
        200: {
            "description": "有界项目事件批次",
            "content": {"text/event-stream": {}},
        },
        503: {"description": "数据库暂时不可用", "model": ErrorBody},
    },
)
def get_project_events(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    after: EventCursor = None,
) -> StreamingResponse:
    if (
        AuthorizationPolicy(session).find_project(
            identity,
            project_id,
            ProjectPermission.READ,
        )
        is None
    ):
        return StreamingResponse(
            iter(()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
    frames = materialize_project_event_frames(
        session,
        org_id=identity.organization.id,
        project_id=project_id,
        after=after,
    )
    return StreamingResponse(
        iter(frames),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        **MUTATION_ERRORS,
        404: {"description": "项目或任务引用不存在", "model": ErrorBody},
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def create_task(
    project_id: UUID,
    payload: TaskCreateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> TaskResponse:
    return ProjectService(session).create_task(
        identity=identity,
        project_id=project_id,
        title=payload.title,
        stage_id=payload.stage_id,
        parent_task_id=payload.parent_task_id,
        priority=payload.priority,
        due_at=payload.due_at,
        acceptance_criteria=payload.acceptance_criteria,
        audit=audit,
    )


@router.get(
    "/projects/{project_id}/tasks",
    response_model=TaskPage,
    responses={
        **AUTHENTICATED_ERRORS,
        404: {"description": "项目不存在", "model": ErrorBody},
    },
)
def list_project_tasks(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> TaskPage:
    return load_cursor_page(
        lambda: ProjectService(session).list_project_tasks(
            identity=identity,
            project_id=project_id,
            cursor=cursor,
            limit=limit,
        ),
    )


@router.patch(
    "/tasks/{task_id}/status",
    response_model=TaskResponse,
    responses={
        **MUTATION_ERRORS,
        404: {"description": "任务不存在", "model": ErrorBody},
        409: {"description": "状态转换无效", "model": ErrorBody},
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def transition_task(
    task_id: UUID,
    payload: TaskStatusUpdateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> TaskResponse:
    return ProjectService(session).transition_task(
        identity=identity,
        task_id=task_id,
        requested_status=payload.status,
        audit=audit,
    )


@router.post(
    "/tasks/{task_id}/dependencies",
    response_model=DependencyResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        **MUTATION_ERRORS,
        404: {"description": "任务不存在", "model": ErrorBody},
        409: {"description": "任务依赖冲突", "model": ErrorBody},
    },
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def add_dependency(
    task_id: UUID,
    payload: TaskDependencyCreateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> DependencyResponse:
    return ProjectService(session).add_dependency(
        identity=identity,
        predecessor_task_id=payload.predecessor_task_id,
        successor_task_id=task_id,
        audit=audit,
    )


__all__ = ["router"]
