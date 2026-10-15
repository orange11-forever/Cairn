from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.routing import APIRoute
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
    AssigneePage,
    DependencyPage,
    DependencyResponse,
    MilestoneCreateRequest,
    MilestonePage,
    MilestoneResponse,
    MilestoneUpdateRequest,
    ProjectCreateRequest,
    ProjectPage,
    ProjectResponse,
    StageCreateRequest,
    StagePage,
    StageResponse,
    StageUpdateRequest,
    TaskCreateRequest,
    TaskDependencyCreateRequest,
    TaskPage,
    TaskResponse,
    TaskStatusUpdateRequest,
    TaskUpdateRequest,
)
from cairn_api.projects.service import ProjectService
from cairn_api.projects.structure_service import ProjectStructureService

router = APIRouter(prefix="/api/v1", tags=["projects"])
SessionDependency = Annotated[Session, Depends(get_db)]
AuditContext = Annotated[RequestAuditContext, Depends(get_audit_context)]
Cursor = Annotated[str | None, Query(max_length=2048)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
EventCursor = Annotated[str | None, Query(max_length=2048)]


def require_structure_csrf(request: Request, identity: CurrentIdentity) -> None:
    del identity
    require_mutation_csrf(request)


AUTHENTICATED_ERRORS: dict[int | str, dict[str, Any]] = {
    500: {"description": "服务器内部错误", "model": ErrorBody},
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
        500: {"description": "服务器内部错误", "model": ErrorBody},
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
        409: {
            "description": "项目修订冲突（revision_conflict），或任务归属结构已归档（structure_archived）",
            "model": ErrorBody,
        },
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
        description=payload.description,
        assignee_user_id=payload.assignee_user_id,
        milestone_id=payload.milestone_id,
        expected_project_revision=payload.expected_project_revision,
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
        expected_revision=payload.expected_revision,
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
        expected_revision=payload.expected_revision,
        audit=audit,
    )


TASK_READ_ERRORS = {
    **AUTHENTICATED_ERRORS,
    404: {"description": "任务或项目不存在", "model": ErrorBody},
}
TASK_WRITE_ERRORS = {
    **MUTATION_ERRORS,
    404: {"description": "任务或项目不存在", "model": ErrorBody},
    409: {"description": "任务修订冲突", "model": ErrorBody},
}


TASK_GROUPING_WRITE_ERRORS = {
    **TASK_WRITE_ERRORS,
    409: {
        "description": "任务或项目修订冲突（revision_conflict），或归属结构已归档（structure_archived）",
        "model": ErrorBody,
    },
}
STRUCTURE_CREATE_ERRORS = {
    **MUTATION_ERRORS,
    404: {"description": "项目或结构引用不存在", "model": ErrorBody},
    409: {"description": "项目修订冲突（revision_conflict）", "model": ErrorBody},
}
STAGE_EDIT_ERRORS = {
    **STRUCTURE_CREATE_ERRORS,
    409: {
        "description": "对象或项目修订冲突（revision_conflict）、结构被占用（structure_in_use），或归档状态冲突（structure_archived）",
        "model": ErrorBody,
    },
}
MILESTONE_CREATE_ERRORS = {
    **STRUCTURE_CREATE_ERRORS,
    409: {
        "description": "项目修订冲突（revision_conflict），或所属阶段已归档（structure_archived）",
        "model": ErrorBody,
    },
}
MILESTONE_EDIT_ERRORS = {
    **STAGE_EDIT_ERRORS,
    409: {
        "description": "对象或项目修订冲突（revision_conflict）、结构被占用（structure_in_use）、归档状态冲突（structure_archived），或里程碑移动与关联任务冲突（milestone_in_use）",
        "model": ErrorBody,
    },
}


@router.get("/tasks/{task_id}", response_model=TaskResponse, responses=TASK_READ_ERRORS)
def get_task(task_id: UUID, identity: CurrentIdentity, session: SessionDependency) -> TaskResponse:
    return ProjectService(session).get_task(identity=identity, task_id=task_id)


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    responses=TASK_GROUPING_WRITE_ERRORS,
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def update_task(
    task_id: UUID,
    payload: TaskUpdateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> TaskResponse:
    return ProjectService(session).update_task(
        identity=identity, task_id=task_id, payload=payload, audit=audit
    )


@router.get(
    "/projects/{project_id}/assignees", response_model=AssigneePage, responses=TASK_READ_ERRORS
)
def list_assignees(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> AssigneePage:
    return load_cursor_page(
        lambda: ProjectService(session).list_assignees(
            identity=identity, project_id=project_id, cursor=cursor, limit=limit
        )
    )


@router.get(
    "/tasks/{task_id}/dependencies", response_model=DependencyPage, responses=TASK_READ_ERRORS
)
def list_dependencies(
    task_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> DependencyPage:
    return load_cursor_page(
        lambda: ProjectService(session).list_dependencies(
            identity=identity, task_id=task_id, cursor=cursor, limit=limit
        )
    )


@router.delete(
    "/tasks/{task_id}/dependencies/{dependency_id}",
    status_code=204,
    responses=TASK_WRITE_ERRORS,
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def delete_dependency(
    task_id: UUID,
    dependency_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    expected_revision: Annotated[int, Query(alias="expectedRevision", ge=1)],
) -> Response:
    ProjectService(session).delete_dependency(
        identity=identity,
        task_id=task_id,
        dependency_id=dependency_id,
        expected_revision=expected_revision,
        audit=audit,
    )
    return Response(status_code=204)


@router.get("/projects/{project_id}/stages", response_model=StagePage, responses=TASK_READ_ERRORS)
def list_stages(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> StagePage:
    return load_cursor_page(
        lambda: ProjectStructureService(session).list_stages(
            identity=identity, project_id=project_id, cursor=cursor, limit=limit
        )
    )


@router.post(
    "/projects/{project_id}/stages",
    response_model=StageResponse,
    status_code=201,
    responses=STRUCTURE_CREATE_ERRORS,
    dependencies=[Depends(require_structure_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def create_stage(
    project_id: UUID,
    payload: StageCreateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> StageResponse:
    return ProjectStructureService(session).create_stage(
        identity=identity, project_id=project_id, payload=payload, audit=audit
    )


@router.patch(
    "/projects/{project_id}/stages/{stage_id}",
    response_model=StageResponse,
    responses=STAGE_EDIT_ERRORS,
    dependencies=[Depends(require_structure_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def update_stage(
    project_id: UUID,
    stage_id: UUID,
    payload: StageUpdateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> StageResponse:
    return ProjectStructureService(session).update_stage(
        identity=identity, project_id=project_id, stage_id=stage_id, payload=payload, audit=audit
    )


@router.get(
    "/projects/{project_id}/milestones", response_model=MilestonePage, responses=TASK_READ_ERRORS
)
def list_milestones(
    project_id: UUID,
    identity: CurrentIdentity,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: PageLimit = 50,
) -> MilestonePage:
    return load_cursor_page(
        lambda: ProjectStructureService(session).list_milestones(
            identity=identity, project_id=project_id, cursor=cursor, limit=limit
        )
    )


@router.post(
    "/projects/{project_id}/milestones",
    response_model=MilestoneResponse,
    status_code=201,
    responses=MILESTONE_CREATE_ERRORS,
    dependencies=[Depends(require_structure_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def create_milestone(
    project_id: UUID,
    payload: MilestoneCreateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> MilestoneResponse:
    return ProjectStructureService(session).create_milestone(
        identity=identity, project_id=project_id, payload=payload, audit=audit
    )


@router.patch(
    "/projects/{project_id}/milestones/{milestone_id}",
    response_model=MilestoneResponse,
    responses=MILESTONE_EDIT_ERRORS,
    dependencies=[Depends(require_structure_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def update_milestone(
    project_id: UUID,
    milestone_id: UUID,
    payload: MilestoneUpdateRequest,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
) -> MilestoneResponse:
    return ProjectStructureService(session).update_milestone(
        identity=identity,
        project_id=project_id,
        milestone_id=milestone_id,
        payload=payload,
        audit=audit,
    )


# Declare the headers added at the outer HTTP boundary on every non-SSE response.
PROJECT_HEADERS = {
    "X-Request-ID": {"description": "请求追踪标识", "schema": {"type": "string"}},
    "Cache-Control": {"schema": {"type": "string", "const": "private, no-store"}},
    "X-Content-Type-Options": {"schema": {"type": "string", "const": "nosniff"}},
}
for route in router.routes:
    if isinstance(route, APIRoute) and not route.path.endswith("/events"):
        # Error response dictionaries are shared across route declarations; copy
        # before adding non-SSE headers so event errors keep their old contract.
        route.responses = {code: dict(response) for code, response in route.responses.items()}
        route.responses.setdefault(route.status_code or 200, {})
        for response in route.responses.values():
            response["headers"] = PROJECT_HEADERS


__all__ = ["router"]
