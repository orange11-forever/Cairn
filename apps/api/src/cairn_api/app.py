import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from cairn_api import __version__
from cairn_api.errors import error_response
from cairn_api.middleware import RequestIdMiddleware, new_request_id
from cairn_api.settings import Settings

logger = logging.getLogger("cairn_api")


class HealthResponse(BaseModel):
    service: Literal["cairn-api"] = "cairn-api"
    version: str
    status: Literal["ok"] = "ok"


class ApiVersionResponse(BaseModel):
    version: Literal["v1"] = "v1"
    service: Literal["cairn-api"] = "cairn-api"


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else new_request_id()


def create_app(settings: Settings | None = None) -> FastAPI:
    current_settings = settings or Settings()
    logger.setLevel(current_settings.log_level)

    application = FastAPI(title="Cairn API", version=__version__)
    application.state.settings = current_settings
    application.add_middleware(RequestIdMiddleware)

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        error = {
            404: ("not_found", "请求的资源不存在"),
            405: ("method_not_allowed", "请求方法不被允许"),
        }.get(exc.status_code, ("http_error", "请求失败"))
        return error_response(
            status_code=exc.status_code,
            code=error[0],
            message=error[1],
            trace_id=get_request_id(request),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            status_code=422,
            code="validation_error",
            message="请求参数无效",
            trace_id=get_request_id(request),
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        trace_id = get_request_id(request)
        logger.error(
            "Unhandled API exception",
            exc_info=exc,
            extra={"request_id": trace_id},
        )
        return error_response(
            status_code=500,
            code="internal_error",
            message="服务器内部错误",
            trace_id=trace_id,
        )

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:  # pyright: ignore[reportUnusedFunction]
        return HealthResponse(version=__version__)

    @application.get("/api/v1", response_model=ApiVersionResponse)
    async def api_version() -> ApiVersionResponse:  # pyright: ignore[reportUnusedFunction]
        return ApiVersionResponse()

    return application


app = create_app()
