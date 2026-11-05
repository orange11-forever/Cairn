from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity, get_request_settings
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import AuthService
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.session import Database
from cairn_api.workspace.local import DesktopWorkspace
from cairn_api.workspace.router import ERRORS, Db, Workspace, no_store
from cairn_api.workspace.terminal import (
    TerminalInput,
    TerminalManager,
    TerminalSize,
    TerminalSnapshot,
    TerminalStart,
)

router = APIRouter(prefix='/api/v1/desktop/projects/{project_id}', tags=['desktop-terminal'],
                   dependencies=[Depends(no_store)])
MUTATION = [Depends(require_mutation_csrf)]


def terminal_identity(request: Request, session: Db) -> IdentityContextResponse:
    settings = get_request_settings(request)
    return AuthService(session, settings).restore(
        session_token=request.cookies.get(settings.session_cookie_name), audit=None)


TerminalIdentity = Annotated[IdentityContextResponse, Depends(terminal_identity)]


def manager(workspace: DesktopWorkspace) -> TerminalManager:
    with workspace.lock:
        if workspace.terminals is None:
            workspace.terminals = TerminalManager(workspace)
        return workspace.terminals


@router.get('/terminal', response_model=TerminalSnapshot | None, responses=ERRORS)
def current(project_id: UUID, identity: TerminalIdentity, session: Db, workspace: Workspace,
            after: Annotated[int, Query(ge=0)] = 0) -> TerminalSnapshot | None:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    return manager(workspace).current(identity.user.id, project_id, after)


@router.post('/terminal', response_model=TerminalSnapshot, status_code=201, responses=ERRORS,
             dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def start(project_id: UUID, payload: TerminalStart, request: Request, identity: CurrentIdentity,
          session: Db, workspace: Workspace) -> TerminalSnapshot:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    settings = get_request_settings(request)
    token = request.cookies.get(settings.session_cookie_name)
    database = cast(Database, request.app.state.database)

    def authorize() -> None:
        with database.session_factory() as current:
            restored = AuthService(current, settings).restore(session_token=token, audit=None)
            AuthorizationPolicy(current).require_project(restored, project_id, ProjectPermission.WRITE)

    return manager(workspace).start(identity.user.id, project_id, payload, authorize)


@router.post('/terminal/{terminal_id}/input', status_code=204, responses=ERRORS,
             dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def write(project_id: UUID, terminal_id: UUID, payload: TerminalInput, identity: TerminalIdentity,
          session: Db, workspace: Workspace) -> Response:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    manager(workspace).session(identity.user.id, project_id, terminal_id).write(payload.data)
    response = Response(status_code=204)
    no_store(response)
    return response


@router.post('/terminal/{terminal_id}/resize', status_code=204, responses=ERRORS,
             dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def resize(project_id: UUID, terminal_id: UUID, payload: TerminalSize, identity: TerminalIdentity,
           session: Db, workspace: Workspace) -> Response:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    manager(workspace).session(identity.user.id, project_id, terminal_id).resize(payload.cols, payload.rows)
    response = Response(status_code=204)
    no_store(response)
    return response


@router.post('/terminal/{terminal_id}/close', response_model=TerminalSnapshot, responses=ERRORS,
             dependencies=MUTATION, openapi_extra=CSRF_REQUIRED_OPENAPI)
def close(project_id: UUID, terminal_id: UUID, identity: CurrentIdentity,
          session: Db, workspace: Workspace) -> TerminalSnapshot:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    terminal = manager(workspace).session(identity.user.id, project_id, terminal_id)
    terminal.stop()
    return terminal.snapshot(0)
