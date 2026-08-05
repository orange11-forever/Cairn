from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse


class ApiProblem(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = dict(headers or {})


class ErrorBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str
    code: str
    trace_id: str = Field(serialization_alias="traceId")


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    trace_id: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorBody(message=message, code=code, trace_id=trace_id)
    response_headers = {"X-Request-ID": trace_id}
    for name, value in (headers or {}).items():
        if name.lower() == "retry-after":
            response_headers["Retry-After"] = value
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
        headers=response_headers,
    )
