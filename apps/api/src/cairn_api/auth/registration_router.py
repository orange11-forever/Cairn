import logging
from collections.abc import Callable
from typing import Any, cast

from fastapi import APIRouter, Request

from cairn_api.auth.dependencies import get_audit_context, get_request_settings
from cairn_api.auth.registration_mail import RegistrationMailSender
from cairn_api.auth.registration_schemas import (
    RegistrationAvailability,
    RegistrationCreated,
    RegistrationRequest,
)
from cairn_api.auth.registration_service import RegistrationService
from cairn_api.auth.router import INTERNAL_ERROR, SessionDependency, require_login_origin
from cairn_api.db.errors import DATABASE_UNAVAILABLE_ERRORS
from cairn_api.errors import ApiProblem, ErrorBody

router = APIRouter(prefix="/api/v1/auth", tags=["registration"])
ERRORS: dict[int | str, dict[str, Any]] = {
    **INTERNAL_ERROR,
    409: {"description": "邮箱无法用于创建新账号", "model": ErrorBody},
    403: {"description": "请求来源无效", "model": ErrorBody},
    422: {"description": "请求参数无效", "model": ErrorBody},
    429: {
        "description": "操作过于频繁",
        "model": ErrorBody,
        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
    },
    503: {"description": "注册或数据库暂时不可用", "model": ErrorBody},
}


def run_registration[T](request: Request, operation: Callable[[], T]) -> T:
    try:
        return operation()
    except (ApiProblem, *DATABASE_UNAVAILABLE_ERRORS):
        raise
    except Exception as exc:  # noqa: BLE001 - sanitize the complete public registration boundary
        # Database exceptions may include passwords or email addresses.
        logging.getLogger("cairn_api").error(
            "Unhandled registration exception (%s)",
            type(exc).__name__,
            extra={"request_id": get_audit_context(request).trace_id},
        )
        raise ApiProblem(status_code=500, code="internal_error", message="服务器内部错误") from None


def service(request: Request, session: SessionDependency) -> RegistrationService:
    settings = get_request_settings(request)
    require_login_origin(request, settings)
    return RegistrationService(
        session, settings, cast(RegistrationMailSender, request.app.state.registration_mail_sender)
    )


@router.get("/registration", response_model=RegistrationAvailability, responses=INTERNAL_ERROR)
def availability(request: Request) -> RegistrationAvailability:
    return RegistrationAvailability(enabled=get_request_settings(request).registration_enabled)


@router.post("/register", status_code=201, response_model=RegistrationCreated, responses=ERRORS)
def register(
    payload: RegistrationRequest, request: Request, session: SessionDependency
) -> RegistrationCreated:
    audit = get_audit_context(request)
    return run_registration(
        request,
        lambda: service(request, session).request_direct(payload, audit.ip or "unknown", audit),
    )


@router.post("/register/resend", status_code=410, response_model=ErrorBody, deprecated=True)
@router.post("/register/verify", status_code=410, response_model=ErrorBody, deprecated=True)
@router.post("/password/reset/request", status_code=410, response_model=ErrorBody, deprecated=True)
@router.post("/password/reset/confirm", status_code=410, response_model=ErrorBody, deprecated=True)
def email_flow_disabled() -> ErrorBody:
    raise ApiProblem(
        status_code=410,
        code="email_flow_disabled",
        message="邮件验证和邮件找回功能已关闭，请直接注册或登录。",
    )
