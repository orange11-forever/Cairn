from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity, get_audit_context, get_request_settings
from cairn_api.auth.service import AuthService
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.session import Database
from cairn_api.workspace.coding_delivery import CodingDelivery
from cairn_api.workspace.coding_router import runner
from cairn_api.workspace.coding_schemas import CodingRun
from cairn_api.workspace.delivery_schemas import (
    CommitRequest,
    DeliveryReview,
    PrepareRemoteRequest,
    PullRequestInput,
    PushRequest,
    RemoteTarget,
)
from cairn_api.workspace.router import ERRORS, Db, Workspace, no_store

router = APIRouter(prefix='/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/delivery',
                   tags=['desktop-coding'], dependencies=[Depends(no_store)])
MUTATION = [Depends(require_mutation_csrf)]
HEADERS = {
    'X-Request-ID': {'schema': {'type': 'string'}, 'description': 'Request trace identifier'},
    'Cache-Control': {'schema': {'type': 'string', 'const': 'no-store'}},
    'Referrer-Policy': {'schema': {'type': 'string', 'const': 'no-referrer'}},
}
RESPONSES = {200: {'headers': HEADERS}, **{code: {**value, 'headers': HEADERS} for code, value in ERRORS.items()}}


def delivery(project_id: UUID, run_id: UUID, request: Request, identity: CurrentIdentity,
             session: Db, workspace: Workspace) -> CodingDelivery:
    AuthorizationPolicy(session).require_project(identity, project_id, ProjectPermission.READ)
    settings, audit = get_request_settings(request), get_audit_context(request)
    token = request.cookies.get(settings.session_cookie_name)
    database = cast(Database, request.app.state.database)

    def authorize() -> None:
        with database.session_factory() as current:
            restored = AuthService(current, settings).restore(session_token=token, audit=audit)
            AuthorizationPolicy(current).require_project(restored, project_id, ProjectPermission.WRITE)

    return CodingDelivery(runner(workspace), identity.user.id, project_id, run_id, authorize=authorize)


Delivery = Annotated[CodingDelivery, Depends(delivery)]


@router.get('', response_model=DeliveryReview, responses=RESPONSES)
def review(service: Delivery) -> DeliveryReview:
    return service.review()


@router.post('/commit', response_model=CodingRun, responses=RESPONSES, dependencies=MUTATION,
             openapi_extra=CSRF_REQUIRED_OPENAPI)
def commit(payload: CommitRequest, service: Delivery) -> CodingRun:
    return service.commit(payload)


@router.post('/target', response_model=RemoteTarget, responses=RESPONSES, dependencies=MUTATION,
             openapi_extra=CSRF_REQUIRED_OPENAPI)
def prepare_target(payload: PrepareRemoteRequest, service: Delivery) -> RemoteTarget:
    return service.prepare_remote(payload.base_branch)


@router.post('/push', response_model=CodingRun, responses=RESPONSES, dependencies=MUTATION,
             openapi_extra=CSRF_REQUIRED_OPENAPI)
def push(payload: PushRequest, service: Delivery) -> CodingRun:
    return service.push(payload)


@router.post('/pull-request', response_model=CodingRun, responses=RESPONSES, dependencies=MUTATION,
             openapi_extra=CSRF_REQUIRED_OPENAPI)
def create_pr(payload: PullRequestInput, service: Delivery) -> CodingRun:
    return service.create_pr(payload)


@router.post('/reconcile', response_model=CodingRun, responses=RESPONSES, dependencies=MUTATION,
             openapi_extra=CSRF_REQUIRED_OPENAPI)
def reconcile(service: Delivery) -> CodingRun:
    return service.reconcile()
