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
from cairn_api.workspace.coding import CodingProvider, CodingRunner
from cairn_api.workspace.coding_schemas import (
    CodingRun,
    CodingRunList,
    CodingStart,
    CommandDecision,
)
from cairn_api.workspace.local import DesktopWorkspace
from cairn_api.workspace.router import ERRORS, Db, Workspace, no_store

router = APIRouter(prefix='/api/v1/desktop/projects/{project_id}/coding-runs',
    tags=['desktop-coding'], dependencies=[Depends(no_store)])
MUTATION = [Depends(require_mutation_csrf)]


def runner(workspace: DesktopWorkspace) -> CodingRunner:
    with workspace.lock:
        if workspace.coding is None:
            workspace.coding = CodingRunner(workspace)
        return workspace.coding


@router.get('', response_model=CodingRunList, responses=ERRORS)
def list_runs(project_id: UUID, identity: CurrentIdentity, session: Db, workspace: Workspace) -> CodingRunList:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    return runner(workspace).list(identity.user.id, project_id)


@router.get('/{run_id}', response_model=CodingRun, responses=ERRORS)
def get_run(project_id: UUID, run_id: UUID, identity: CurrentIdentity, session: Db, workspace: Workspace) -> CodingRun:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    return runner(workspace).get(identity.user.id, project_id, run_id)


@router.post('', response_model=CodingRun, status_code=202, responses=ERRORS,
    dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def start_run(project_id: UUID, payload: CodingStart, request: Request, identity: CurrentIdentity,
              session: Db, workspace: Workspace, models: AnswerModelsDependency) -> CodingRun:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
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
            latest = assistant_repository.settings_response(assistant_repository.settings_row(
                current, restored.organization.id, project_id, restored.user.id))
            if latest != assistant:
                raise assistant_repository.assistant_changed()

    return runner(workspace).start(identity.user.id, project_id, payload,
        assistant_name=assistant.name, model=model.info, provider=cast(CodingProvider, model.provider),
        guidance=asdict(guidance) if guidance else None, authorize=authorize)


@router.post('/{run_id}/decision', response_model=CodingRun, responses=ERRORS,
    dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def decide_command(project_id: UUID, run_id: UUID, payload: CommandDecision,
                   identity: CurrentIdentity, session: Db, workspace: Workspace) -> CodingRun:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    return runner(workspace).decide(identity.user.id, project_id, run_id, payload)


@router.post('/{run_id}/cancel', response_model=CodingRun, responses=ERRORS,
    dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def cancel_run(project_id: UUID, run_id: UUID, identity: CurrentIdentity,
               session: Db, workspace: Workspace) -> CodingRun:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    return runner(workspace).cancel(identity.user.id, project_id, run_id)
