from dataclasses import asdict
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity, get_audit_context, get_request_settings
from cairn_api.auth.service import AuthService
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import assistant_repository
from cairn_api.knowledge.answer_models import selected_answer_model
from cairn_api.knowledge.dependencies import AnswerModelsDependency
from cairn_api.projects import repository as project_repository
from cairn_api.workspace.coding import ACTIVE, CodingProvider, CodingRunner
from cairn_api.workspace.coding_schemas import (
    CodingConcurrency,
    CodingOverview,
    CodingRun,
    CodingRunList,
    CodingRunSummary,
    CodingStart,
    CommandDecision,
)
from cairn_api.workspace.local import DesktopWorkspace
from cairn_api.workspace.router import ERRORS, Db, Workspace, no_store

router = APIRouter(prefix='/api/v1/desktop',
    tags=['desktop-coding'], dependencies=[Depends(no_store)])
MUTATION = [Depends(require_mutation_csrf)]


def runner(workspace: DesktopWorkspace) -> CodingRunner:
    with workspace.lock:
        if workspace.coding is None:
            workspace.coding = CodingRunner(workspace)
        return workspace.coding


@router.get('/coding-runs', response_model=CodingOverview, responses=ERRORS)
def overview(identity: CurrentIdentity, session: Db, workspace: Workspace) -> CodingOverview:
    service = runner(workspace)
    policy = AuthorizationPolicy(session)
    with workspace.lock:
        # The header polls summaries; do not copy every retained source diff and
        # command transcript while holding the workers' shared lock.
        records = [CodingRunSummary(
            id=run.id, project_id=run.project_id, project_name='',
            assistant_name=run.assistant_name, task=run.task, model_name=run.model.name,
            status=run.status, updated_at=run.updated_at,
            progress=run.summary or (run.events[-1].message[-300:] if run.events else ''),
            changed_files=len(run.changes), depends_on=run.depends_on,
            delivery_phase=run.delivery.phase if run.delivery else None,
            pr_url=run.delivery.pr_url if run.delivery else None,
        ) for run in service.runs.values() if run.user_id == identity.user.id]
        limit = service.concurrency
    names: dict[UUID, str] = {}
    for project_id in {run.project_id for run in records}:
        project = policy.find_project(identity, project_id, ProjectPermission.READ)
        if project is not None:
            names[project_id] = project.name
    visible = sorted((run for run in records if run.project_id in names), key=lambda run: run.updated_at, reverse=True)
    visible = [run for run in visible if run.status in ACTIVE] + [run for run in visible if run.status not in ACTIVE][:20]
    for item in visible:
        item.project_name = names[item.project_id]
    return CodingOverview(concurrency=limit, items=visible)


@router.put('/coding-concurrency', response_model=CodingConcurrency, responses=ERRORS,
    dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def set_concurrency(payload: CodingConcurrency, identity: CurrentIdentity, workspace: Workspace) -> CodingConcurrency:
    if identity.membership.role not in {'owner', 'admin'}:
        raise ApiProblem(status_code=403, code='forbidden', message='仅管理员可以调整本机并发上限')
    runner(workspace).set_concurrency(payload.limit)
    return payload


@router.get('/projects/{project_id}/coding-runs', response_model=CodingRunList, responses=ERRORS)
def list_runs(project_id: UUID, identity: CurrentIdentity, session: Db, workspace: Workspace) -> CodingRunList:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    return runner(workspace).list(identity.user.id, project_id)


@router.get('/projects/{project_id}/coding-runs/{run_id}', response_model=CodingRun, responses=ERRORS)
def get_run(project_id: UUID, run_id: UUID, identity: CurrentIdentity, session: Db, workspace: Workspace) -> CodingRun:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    return runner(workspace).get(identity.user.id, project_id, run_id)


@router.post('/projects/{project_id}/coding-runs', response_model=CodingRun, status_code=202, responses=ERRORS,
    dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def start_run(project_id: UUID, payload: CodingStart, request: Request, identity: CurrentIdentity,
              session: Db, workspace: Workspace, models: AnswerModelsDependency) -> CodingRun:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    if payload.source_task is not None:
        task = project_repository.get_task(session, org_id=identity.organization.id,
                                           task_id=payload.source_task.task_id, for_update=True)
        if task is None or task.project_id != project_id:
            raise ApiProblem(status_code=404, code='not_found', message='项目任务不存在或不可访问')
        if task.revision != payload.source_task.revision:
            raise ApiProblem(status_code=409, code='coding_task_changed',
                             message='任务在生成派发建议后已变化，请回到助手重新生成建议')
    assistant, guidance = assistant_repository.guidance(session, identity.organization.id,
        project_id, identity.user.id, payload.assistant_revision, payload.skill_id)
    if assistant.id != payload.assistant_id:
        raise assistant_repository.assistant_changed()
    model = selected_answer_model(models, assistant.model_id)
    if not callable(getattr(model.provider, 'coding_step', None)):
        raise ApiProblem(status_code=503, code='coding_model_unsupported', message='当前模型未接入编程执行协议，请更换模型')
    # Release the assistant row lock before the worker rechecks it in a new session.
    session.commit()
    settings = get_request_settings(request)
    token = request.cookies.get(settings.session_cookie_name)
    audit = get_audit_context(request)
    database = cast(Database, request.app.state.database)

    def authorize() -> None:
        with database.session_factory() as current:
            restored = AuthService(current, settings).restore(session_token=token, audit=audit)
            AuthorizationPolicy(current).require_project(restored, project_id, ProjectPermission.WRITE)
            # Each task retains its own Agent/model/Skill snapshot. Selecting or
            # editing another profile affects subsequent tasks, not this worker.

    return runner(workspace).start(identity.user.id, project_id, payload,
        assistant_name=assistant.name, model=model.info, provider=cast(CodingProvider, model.provider),
        guidance=asdict(guidance) if guidance else None, authorize=authorize)


@router.post('/projects/{project_id}/coding-runs/{run_id}/decision', response_model=CodingRun, responses=ERRORS,
    dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def decide_command(project_id: UUID, run_id: UUID, payload: CommandDecision,
                   identity: CurrentIdentity, session: Db, workspace: Workspace) -> CodingRun:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    return runner(workspace).decide(identity.user.id, project_id, run_id, payload)


@router.post('/projects/{project_id}/coding-runs/{run_id}/cancel', response_model=CodingRun, responses=ERRORS,
    dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def cancel_run(project_id: UUID, run_id: UUID, identity: CurrentIdentity,
               session: Db, workspace: Workspace) -> CodingRun:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    return runner(workspace).cancel(identity.user.id, project_id, run_id)
