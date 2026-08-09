from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from cairn_api import __version__
from cairn_api.auth.router import clear_session_cookie
from cairn_api.auth.router import router as auth_router
from cairn_api.db.errors import DATABASE_UNAVAILABLE_ERRORS
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem, error_response
from cairn_api.logging import configure_app_logging
from cairn_api.middleware import RequestIdMiddleware, new_request_id
from cairn_api.organizations.router import router as organizations_router
from cairn_api.projects.router import router as projects_router
from cairn_api.settings import Settings


class HealthResponse(BaseModel):
    service: Literal["cairn-api"] = "cairn-api"
    version: str
    status: Literal["ok"] = "ok"


class ApiVersionResponse(BaseModel):
    version: Literal["v1"] = "v1"
    service: Literal["cairn-api"] = "cairn-api"


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else new_request_id()


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    current_settings = settings or Settings()
    current_database = database or Database(current_settings.database_url)
    logger = configure_app_logging(current_settings.log_level)

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            current_database.dispose()

    application = FastAPI(title="Cairn API", version=__version__, lifespan=lifespan)
    application.state.settings = current_settings
    application.state.database = current_database
    if current_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=current_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
        )
    application.add_middleware(RequestIdMiddleware)

    @application.exception_handler(ApiProblem)
    async def api_problem_handler(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        exc: ApiProblem,
    ) -> JSONResponse:
        response = error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            trace_id=get_request_id(request),
            headers=exc.headers,
        )
        if exc.code == "session_invalid":
            clear_session_cookie(response, current_settings)
        return response

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

    async def database_unavailable_exception_handler(
        request: Request,
        _exc: Exception,
    ) -> JSONResponse:
        return error_response(
            status_code=503,
            code="database_unavailable",
            message="数据库暂时不可用",
            trace_id=get_request_id(request),
        )

    for exception_type in DATABASE_UNAVAILABLE_ERRORS:
        application.add_exception_handler(
            exception_type,
            database_unavailable_exception_handler,
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

    @application.get("/ready", response_model=ReadyResponse)
    def ready(request: Request) -> ReadyResponse | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            current_database.check_ready()
        except DATABASE_UNAVAILABLE_ERRORS:
            return error_response(
                status_code=503,
                code="database_unavailable",
                message="数据库暂时不可用",
                trace_id=get_request_id(request),
            )
        return ReadyResponse()

    @application.get("/api/v1", response_model=ApiVersionResponse)
    async def api_version() -> ApiVersionResponse:  # pyright: ignore[reportUnusedFunction]
        return ApiVersionResponse()

    application.include_router(auth_router)
    application.include_router(organizations_router)
    application.include_router(projects_router)

    return application


app = create_app()
