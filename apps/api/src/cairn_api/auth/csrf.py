from typing import Any

from fastapi import Request

from cairn_api.auth.dependencies import get_request_settings
from cairn_api.auth.security import verify_csrf_token
from cairn_api.errors import ApiProblem

CSRF_REQUIRED_OPENAPI: dict[str, Any] = {
    "parameters": [
        {
            "name": "X-CSRF-Token",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "minLength": 1},
            "description": "Session-bound CSRF token returned by login or session restore.",
        }
    ]
}


def require_mutation_csrf(
    request: Request,
) -> None:
    settings = get_request_settings(request)
    expected_origin = str(settings.app_url).rstrip("/") if settings.app_url is not None else None
    session_token = request.cookies.get(settings.session_cookie_name)
    csrf_token = request.headers.get("x-csrf-token")
    valid_token = False
    if (
        session_token is not None
        and csrf_token is not None
        and session_token.isascii()
        and csrf_token.isascii()
    ):
        valid_token = verify_csrf_token(
            session_token,
            csrf_token,
            settings.csrf_secret.encode("utf-8"),
        )
    if expected_origin is None or request.headers.get("origin") != expected_origin or not valid_token:
        raise ApiProblem(
            status_code=403,
            code="csrf_failed",
            message="请求来源或 CSRF 令牌无效",
        )
