from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from cairn_api.auth.dependencies import get_audit_context, get_request_settings
from cairn_api.auth.schemas import IdentityContextResponse, LoginRequest
from cairn_api.auth.service import AuthService
from cairn_api.db.session import get_db
from cairn_api.errors import ApiProblem, ErrorBody
from cairn_api.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["identity"])
SessionDependency = Annotated[Session, Depends(get_db)]

INTERNAL_ERROR: dict[int | str, dict[str, Any]] = {
    500: {"description": "服务器内部错误", "model": ErrorBody},
}

LOGIN_ERRORS: dict[int | str, dict[str, Any]] = {
    **INTERNAL_ERROR,
    401: {"description": "邮箱或密码错误", "model": ErrorBody},
    403: {"description": "请求来源无效", "model": ErrorBody},
    409: {"description": "需要选择组织", "model": ErrorBody},
    422: {"description": "请求参数无效", "model": ErrorBody},
    429: {"description": "登录尝试过于频繁", "model": ErrorBody},
    503: {"description": "数据库暂时不可用", "model": ErrorBody},
}
SESSION_ERRORS: dict[int | str, dict[str, Any]] = {
    **INTERNAL_ERROR,
    401: {"description": "会话无效", "model": ErrorBody},
    503: {"description": "数据库暂时不可用", "model": ErrorBody},
}
LOGOUT_ERRORS: dict[int | str, dict[str, Any]] = {
    **INTERNAL_ERROR,
    403: {"description": "请求来源或 CSRF 令牌无效", "model": ErrorBody},
    503: {"description": "数据库暂时不可用", "model": ErrorBody},
}
LOGOUT_OPENAPI: dict[str, Any] = {
    "parameters": [
        {
            "name": "X-CSRF-Token",
            "in": "header",
            "required": False,
            "schema": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "X-Csrf-Token",
            },
        }
    ]
}


def _require_origin(request: Request, settings: Settings) -> None:
    expected = str(settings.app_url).rstrip("/") if settings.app_url is not None else None
    if expected is None or request.headers.get("origin") != expected:
        raise ApiProblem(
            status_code=403,
            code="csrf_failed",
            message="请求来源或 CSRF 令牌无效",
        )


def set_session_cookie(response: Response, settings: Settings, session_token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        max_age=settings.session_ttl_seconds,
        expires=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/login",
    response_model=IdentityContextResponse,
    responses=LOGIN_ERRORS,
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
) -> IdentityContextResponse:
    settings = get_request_settings(request)
    _require_origin(request, settings)
    audit = get_audit_context(request)
    result = AuthService(session, settings).login(
        email=str(payload.email),
        password=payload.password,
        audit=audit,
        client_ip=audit.ip or "unknown",
    )
    set_session_cookie(response, settings, result.session_token)
    return result.identity


@router.get(
    "/session",
    response_model=IdentityContextResponse,
    responses=SESSION_ERRORS,
)
def restore_session(request: Request, session: SessionDependency) -> IdentityContextResponse:
    settings = get_request_settings(request)
    return AuthService(session, settings).restore(
        session_token=request.cookies.get(settings.session_cookie_name),
        audit=get_audit_context(request),
    )


@router.post(
    "/logout",
    status_code=204,
    responses=LOGOUT_ERRORS,
    openapi_extra=LOGOUT_OPENAPI,
)
def logout(
    request: Request,
    session: SessionDependency,
) -> Response:
    settings = get_request_settings(request)
    _require_origin(request, settings)
    AuthService(session, settings).logout(
        session_token=request.cookies.get(settings.session_cookie_name),
        csrf_token=request.headers.get("X-CSRF-Token"),
        audit=get_audit_context(request),
    )
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response
