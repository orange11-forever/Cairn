import logging
import re
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
        if request.url.path.startswith(
            ("/api/v1/tasks/", "/api/v1/projects")
        ) and not request.url.path.endswith("/events"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


class ProjectErrorBoundary:
    """Keep handled task/project failures from being logged again with private inputs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        protected = (
            scope["type"] == "http"
            and scope.get("path", "").startswith(("/api/v1/tasks/", "/api/v1/projects"))
            and not scope.get("path", "").endswith("/events")
        )
        failed = False
        complete = False

        async def protected_send(message: Message) -> None:
            nonlocal failed, complete
            if message["type"] == "http.response.start":
                failed = message["status"] == 500
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True
            await send(message)

        try:
            await self.app(scope, receive, protected_send)
        except Exception:
            if not (protected and failed and complete):
                raise
