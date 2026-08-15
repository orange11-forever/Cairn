import logging
import re
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
logger = logging.getLogger("cairn_api")


def new_request_id() -> str:
    return secrets.token_urlsafe(16)


def select_request_id(candidate: str | None) -> str:
    if candidate is not None and REQUEST_ID_PATTERN.fullmatch(candidate) is not None:
        return candidate
    return new_request_id()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = select_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        response = await call_next(request)
        logger.info(
            "%s %s status=%s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"request_id": request_id},
        )
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api/v1/projects/") and "/knowledge/" in request.url.path:
            response.headers["Cache-Control"] = "private, no-store"
        return response
