import logging
from collections.abc import Callable
from typing import Any, cast

from fastapi import APIRouter, Request

from cairn_api.auth.dependencies import get_audit_context, get_request_settings
from cairn_api.auth.registration_mail import RegistrationMailSender, registration_available
from cairn_api.auth.registration_schemas import (
    RegistrationAccepted,
    RegistrationAvailability,
    RegistrationRequest,
    RegistrationResendRequest,
    RegistrationVerified,
    RegistrationVerifyRequest,
)
from cairn_api.auth.registration_service import RegistrationService
from cairn_api.auth.router import INTERNAL_ERROR, SessionDependency, require_login_origin
from cairn_api.db.errors import DATABASE_UNAVAILABLE_ERRORS
from cairn_api.errors import ApiProblem, ErrorBody

router = APIRouter(prefix="/api/v1/auth", tags=["registration"])
ERRORS: dict[int | str, dict[str, Any]] = {
    **INTERNAL_ERROR,
    400: {"description": "验证链接或密码无效", "model": ErrorBody},
    403: {"description": "请求来源无效", "model": ErrorBody},
    422: {"description": "请求参数无效", "model": ErrorBody},
    429: {
        "description": "操作过于频繁",
        "model": ErrorBody,
        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
    },
    503: {"description": "注册、邮件或数据库暂时不可用", "model": ErrorBody},
}


def run_registration[T](request: Request, operation: Callable[[], T]) -> T:
    try:
        return operation()
    except (ApiProblem, *DATABASE_UNAVAILABLE_ERRORS):
        raise
    except Exception as exc:  # noqa: BLE001 - sanitize the complete public registration boundary
        # Exceptions may include SMTP recipients, SQL parameters, or proof material.
        # Handle here so the ASGI server cannot re-log a raw exception traceback.
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
    return RegistrationAvailability(enabled=registration_available(get_request_settings(request)))


@router.post("/register", status_code=202, response_model=RegistrationAccepted, responses=ERRORS)
def register(
    payload: RegistrationRequest, request: Request, session: SessionDependency
) -> RegistrationAccepted:
    return run_registration(
        request,
        lambda: service(request, session).request(
            payload, get_audit_context(request).ip or "unknown"
        ),
    )


@router.post(
    "/register/resend", status_code=202, response_model=RegistrationAccepted, responses=ERRORS
)
def resend(
    payload: RegistrationResendRequest, request: Request, session: SessionDependency
) -> RegistrationAccepted:
    return run_registration(
        request,
        lambda: service(request, session).resend(
            payload, get_audit_context(request).ip or "unknown"
        ),
    )


@router.post("/register/verify", response_model=RegistrationVerified, responses=ERRORS)
def verify(
    payload: RegistrationVerifyRequest, request: Request, session: SessionDependency
) -> RegistrationVerified:
    audit = get_audit_context(request)
    return run_registration(
        request,
        lambda: service(request, session).verify(
            payload.token, payload.password, audit.ip or "unknown", audit
        ),
    )
