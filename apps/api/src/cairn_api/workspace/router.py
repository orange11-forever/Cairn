from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity, get_audit_context, get_request_settings
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.session import get_db
from cairn_api.errors import ApiProblem, ErrorBody
from cairn_api.knowledge.dependencies import AnswerModelsDependency
from cairn_api.workspace.architecture import RepositorySnapshot
from cairn_api.workspace.architecture_service import (
    ArchitectureAnalysis,
    ArchitectureRequest,
    RepositoryArchitectureService,
)
from cairn_api.workspace.device import DEVICE_COOKIE
from cairn_api.workspace.github import github_problem
from cairn_api.workspace.local import DesktopWorkspace
from cairn_api.workspace.schemas import (
    GitHubConnection,
    GitHubDevicePoll,
    GitHubDeviceResult,
    GitHubDeviceStart,
    GitHubDeviceStarted,
    GitHubRepositoryPage,
    RepositoryBinding,
    RepositoryBindRequest,
    WorkspaceStatus,
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


router = APIRouter(
    prefix="/api/v1/desktop", tags=["desktop-workspace"], dependencies=[Depends(no_store)]
)
Db = Annotated[Session, Depends(get_db)]
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorBody, "description": "GitHub 授权或仓库操作失败"}
    for code in (400, 401, 403, 404, 409, 422, 429, 500, 502, 503, 504)
}


def desktop_workspace(request: Request) -> DesktopWorkspace:
    workspace = getattr(request.app.state, "desktop_workspace", None)
    if not isinstance(workspace, DesktopWorkspace):
        raise github_problem("desktop_required", "本地代码仓库仅在 Cairn 桌面版中可用", 503)
    return workspace


Workspace = Annotated[DesktopWorkspace, Depends(desktop_workspace)]


@router.get(
    "/projects/{project_id}/architecture", response_model=RepositorySnapshot, responses=ERRORS
)
def architecture_sources(
    project_id: UUID, request: Request, identity: CurrentIdentity, session: Db, workspace: Workspace
) -> RepositorySnapshot:
    settings = get_request_settings(request)
    return RepositoryArchitectureService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        get_audit_context(request),
    ).preview(project_id, workspace)


@router.post(
    "/projects/{project_id}/architecture",
    response_model=ArchitectureAnalysis,
    responses=ERRORS,
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def analyze_architecture(
    project_id: UUID,
    payload: ArchitectureRequest,
    request: Request,
    identity: CurrentIdentity,
    session: Db,
    workspace: Workspace,
    models: AnswerModelsDependency,
) -> ArchitectureAnalysis:
    settings = get_request_settings(request)
    return RepositoryArchitectureService(
        session,
        identity,
        request.cookies.get(settings.session_cookie_name),
        get_audit_context(request),
        answer_models=models,
    ).analyze(project_id, workspace, payload)


@router.post("/github/device", response_model=GitHubDeviceStarted, responses=ERRORS)
def device_start(
    payload: GitHubDeviceStart,
    request: Request,
    response: Response,
    session: Db,
    workspace: Workspace,
) -> GitHubDeviceStarted:
    return workspace.devices.start(workspace, payload.intent, request, response, session)


@router.post("/github/device/poll", response_model=GitHubDeviceResult, responses=ERRORS)
def device_poll(
    payload: GitHubDevicePoll, request: Request, session: Db, workspace: Workspace
) -> GitHubDeviceResult:
    return workspace.devices.poll(workspace, payload.attempt_id, request, session)


@router.delete("/github/device", status_code=204, responses=ERRORS)
def device_cancel(
    payload: GitHubDevicePoll, request: Request, session: Db, workspace: Workspace
) -> Response:
    workspace.devices.cancel(workspace, payload.attempt_id, request, session)
    response = Response(status_code=204)
    no_store(response)
    response.delete_cookie(DEVICE_COOKIE, path="/api/v1/desktop/github")
    return response


@router.get("/github/connection", response_model=GitHubConnection, responses=ERRORS)
def connection(identity: CurrentIdentity, workspace: Workspace) -> GitHubConnection:
    credential = workspace.credential(identity.user.id)
    if credential is None or workspace.github is None:
        return GitHubConnection(configured=workspace.github is not None, status="disconnected")
    import time

    if credential.expires_at is not None and credential.expires_at <= time.time():
        return GitHubConnection(
            configured=True,
            status="expired",
            account=credential.account,
            message="GitHub 授权已过期，请重新授权",
        )
    try:
        account = workspace.github.account(credential.token.get_secret_value())
        if account.id != credential.account.id:
            raise github_problem(
                "github_credentials_invalid", "GitHub 账号与保存的授权不一致，请重新授权", 401
            )
        return GitHubConnection(configured=True, status="connected", account=account)
    except ApiProblem as error:
        return GitHubConnection(
            configured=True,
            status="revoked" if error.code == "github_credentials_invalid" else "unavailable",
            account=credential.account,
            message=error.message,
        )


@router.delete(
    "/github/connection",
    status_code=204,
    responses=ERRORS,
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def disconnect(identity: CurrentIdentity, workspace: Workspace) -> Response:
    workspace.disconnect(identity.user.id)
    response = Response(status_code=204)
    no_store(response)
    return response


@router.get("/github/repositories", response_model=GitHubRepositoryPage, responses=ERRORS)
def repositories(
    identity: CurrentIdentity, workspace: Workspace, page: Annotated[int, Query(ge=1, le=10000)] = 1
) -> GitHubRepositoryPage:
    credential = workspace.token(identity.user.id)
    assert workspace.github is not None
    return workspace.github.repositories(credential.token.get_secret_value(), page)


@router.get("/projects/{project_id}/repository", response_model=WorkspaceStatus, responses=ERRORS)
def repository_status(
    project_id: UUID, identity: CurrentIdentity, session: Db, workspace: Workspace
) -> WorkspaceStatus:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    binding = workspace.binding(identity.user.id, project_id)
    message = None
    repository_state: Literal["local", "available", "unavailable", "changed"] = "local"
    if binding:
        try:
            path, binding.branch = workspace.inspect(binding.local_path)
            if binding.repository:
                workspace.verify_remote(path, binding.repository)
                credential = workspace.token(identity.user.id)
                if binding.account and credential.account.id != binding.account.id:
                    raise github_problem(
                        "github_account_changed",
                        "当前 GitHub 授权账号与此仓库关联时的账号不同，请重新关联；本地文件已保留",
                        409,
                    )
                assert workspace.github is not None
                binding.repository = workspace.github.repository(
                    credential.token.get_secret_value(), binding.repository.id
                )
                repository_state = "available"
        except ApiProblem as error:
            message = error.message
            repository_state = (
                "changed" if error.code == "workspace_remote_mismatch" else "unavailable"
            )
    return WorkspaceStatus(
        binding=binding,
        git_available=workspace.git.is_file(),
        message=message,
        repository_status=repository_state,
    )


@router.put(
    "/projects/{project_id}/repository",
    response_model=RepositoryBinding,
    responses=ERRORS,
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def bind_repository(
    project_id: UUID,
    payload: RepositoryBindRequest,
    identity: CurrentIdentity,
    session: Db,
    workspace: Workspace,
) -> RepositoryBinding:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    with workspace.lock:
        remote = None
        credential = None
        if payload.repository_id is not None:
            credential = workspace.token(identity.user.id)
            assert workspace.github is not None
            remote = workspace.github.repository(
                credential.token.get_secret_value(), payload.repository_id
            )
        if payload.mode == "clone":
            if remote is None or credential is None:
                raise github_problem(
                    "workspace_repository_required", "请先选择要克隆的 GitHub 仓库", 422
                )
            return workspace.clone(
                identity.user.id,
                project_id,
                remote,
                payload.local_path,
                credential.token.get_secret_value(),
                credential.account,
            )
        return workspace.bind_local(
            identity.user.id,
            project_id,
            payload.local_path,
            remote,
            credential.account if credential else None,
        )


@router.delete(
    "/projects/{project_id}/repository",
    status_code=204,
    responses=ERRORS,
    dependencies=[Depends(require_mutation_csrf)],
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def unbind_repository(
    project_id: UUID, identity: CurrentIdentity, session: Db, workspace: Workspace
) -> Response:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.WRITE)
    workspace.unbind(identity.user.id, project_id)
    response = Response(status_code=204)
    no_store(response)
    return response
