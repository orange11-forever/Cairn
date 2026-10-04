from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from cairn_api.auth.csrf import require_mutation_csrf
from cairn_api.auth.dependencies import get_audit_context, get_request_settings
from cairn_api.auth.oauth_claims import browser_cookie_name
from cairn_api.auth.oauth_providers import OAuthProvider, ProviderFailure
from cairn_api.auth.oauth_schemas import (
    LinkedIdentitiesResponse,
    OAuthProviderResponse,
    OAuthStartRequest,
    OAuthStartResponse,
    ProviderName,
)
from cairn_api.auth.oauth_service import ATTEMPT_TTL, OAuthService, problem
from cairn_api.auth.router import require_login_origin, set_session_cookie
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.db.session import get_db
from cairn_api.errors import ApiProblem, ErrorBody
from cairn_api.settings import Settings

router = APIRouter(prefix="/api/v1/auth", tags=["identity"])
SessionDependency = Annotated[Session, Depends(get_db)]
ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorBody, "description": "授权或身份管理请求失败"}
    for status in (400, 401, 403, 404, 409, 422, 429, 500, 502, 503)
}


def _providers(request: Request) -> dict[ProviderName, OAuthProvider]:
    return cast(dict[ProviderName, OAuthProvider], request.app.state.oauth_providers)


def _provider(request: Request, provider: ProviderName) -> OAuthProvider:
    adapter = _providers(request).get(provider)
    if adapter is None:
        raise problem("provider_not_configured", "此登录方式尚未启用，请联系管理员", 503)
    return adapter


def _origin(settings: Settings) -> str:
    if settings.app_url is None:
        raise problem("provider_not_configured", "第三方登录尚未启用", 503)
    return str(settings.app_url).rstrip("/")


def _callback(settings: Settings, provider: ProviderName) -> str:
    # Never trust Host or forwarded headers to determine an OAuth callback.
    return _origin(settings) + f"/api/v1/auth/oauth/{provider}/callback"


def _cookie_name(settings: Settings, provider: ProviderName) -> str:
    return settings.session_cookie_name + "_oauth_" + provider


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.get("/oauth/providers", response_model=list[OAuthProviderResponse])
def providers(request: Request) -> list[OAuthProviderResponse]:
    enabled = _providers(request)
    return [
        OAuthProviderResponse(provider=name, enabled=name in enabled)
        for name in ("github", "feishu")
    ]


@router.post("/oauth/{provider}/start", response_model=OAuthStartResponse, responses=ERRORS)
def start(
    provider: ProviderName,
    payload: OAuthStartRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
) -> OAuthStartResponse:
    settings = get_request_settings(request)
    require_login_origin(request, settings)
    if payload.intent == "link":
        require_mutation_csrf(request)
    adapter = _provider(request, provider)
    started = OAuthService(session, settings).start(
        provider=provider,
        adapter=adapter,
        payload=payload,
        session_token=request.cookies.get(settings.session_cookie_name),
        audit=get_audit_context(request),
        login_browser=request.cookies.get(browser_cookie_name(settings.session_cookie_name)),
    )
    url = adapter.authorization_url(
        state=started.state, verifier=started.verifier, redirect_uri=_callback(settings, provider)
    )
    response.set_cookie(
        _cookie_name(settings, provider),
        started.browser,
        max_age=ATTEMPT_TTL,
        path=f"/api/v1/auth/oauth/{provider}",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    if payload.intent == "login" and started.login_browser is not None:
        response.set_cookie(
            browser_cookie_name(settings.session_cookie_name),
            started.login_browser,
            max_age=31 * 86400,
            path="/api/v1",
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="lax",
        )
    _no_store(response)
    return OAuthStartResponse(authorization_url=url)


@router.get(
    "/oauth/{provider}/callback", response_class=RedirectResponse, status_code=303, responses=ERRORS
)
def callback(provider: ProviderName, request: Request, session: SessionDependency) -> Response:
    settings = get_request_settings(request)
    adapter = _provider(request, provider)
    params = request.query_params
    if any(len(params.getlist(key)) > 1 for key in ("state", "code", "error")):
        raise problem("oauth_state_invalid", "授权请求无效，请重新发起", 400)
    service = OAuthService(session, settings)
    attempt = service.consume(
        provider=provider,
        client_id=adapter.client_id,
        state=params.get("state"),
        browser=request.cookies.get(_cookie_name(settings, provider)),
        login_browser=request.cookies.get(browser_cookie_name(settings.session_cookie_name)),
    )
    session_token = request.cookies.get(settings.session_cookie_name)
    try:
        service.validate_callback_session(attempt, session_token)
        if params.get("error") is not None:
            outcome = "cancelled"
        else:
            code = params.get("code")
            if not code or not code.isascii() or len(code) > 2048:
                raise problem("provider_failed", "第三方身份验证失败", 400)
            remote = adapter.exchange(
                code=code, verifier=attempt.verifier, redirect_uri=_callback(settings, provider)
            )
            service.finish(
                provider=provider,
                adapter=adapter,
                attempt=attempt,
                remote=remote,
                session_token=session_token,
                audit=get_audit_context(request),
                login_browser=request.cookies.get(
                    browser_cookie_name(settings.session_cookie_name)
                ),
            )
            outcome = "linked" if attempt.intent == "link" else "login_ready"
    except ProviderFailure:
        outcome = "provider_failed"
    except ApiProblem as exc:
        outcome = (
            "session_changed"
            if exc.code in ("oauth_session_invalid", "login_context_required")
            else exc.code
        )
    destination = (
        attempt.return_to
        if outcome == "linked"
        else ("/account/identities" if attempt.intent == "link" else "/login")
    )
    response = RedirectResponse(
        _origin(settings) + destination + "?oauth=" + outcome, status_code=303
    )
    _no_store(response)
    return response


@router.get("/identities", response_model=LinkedIdentitiesResponse, responses=ERRORS)
def identities(
    request: Request, response: Response, session: SessionDependency
) -> LinkedIdentitiesResponse:
    settings = get_request_settings(request)
    _no_store(response)
    return OAuthService(session, settings).identities(
        request.cookies.get(settings.session_cookie_name)
    )


@router.delete("/identities/{identity_id}", status_code=204, responses=ERRORS)
def unlink(identity_id: UUID, request: Request, session: SessionDependency) -> Response:
    require_mutation_csrf(request)
    settings = get_request_settings(request)
    OAuthService(session, settings).unlink(
        identity_id=identity_id,
        session_token=request.cookies.get(settings.session_cookie_name),
        enabled_clients={name: adapter.client_id for name, adapter in _providers(request).items()},
        audit=get_audit_context(request),
    )
    response = Response(status_code=204)
    _no_store(response)
    return response


@router.post("/oauth/finalize", response_model=IdentityContextResponse, responses=ERRORS)
def finalize(
    request: Request, response: Response, session: SessionDependency
) -> IdentityContextResponse:
    settings = get_request_settings(request)
    require_login_origin(request, settings)
    result = OAuthService(session, settings).finalize(
        login_browser=request.cookies.get(browser_cookie_name(settings.session_cookie_name)),
        session_token=request.cookies.get(settings.session_cookie_name),
        enabled_clients={name: adapter.client_id for name, adapter in _providers(request).items()},
        audit=get_audit_context(request),
    )
    set_session_cookie(response, settings, result.session_token)
    return result.identity
