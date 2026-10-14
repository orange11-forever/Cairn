"""A handled project failure cannot be re-logged; partial/SSE failures still propagate."""

import asyncio

import pytest
from cairn_api.middleware import ProjectErrorBoundary
from starlette.types import Message, Receive, Scope, Send


@pytest.mark.parametrize(
    "path,status,complete,suppressed",
    [
        ("/api/v1/tasks/task", 500, True, True),
        ("/api/v1/projects/project/assignees", 500, True, True),
        ("/api/v1/tasks/task", 200, True, False),
        ("/api/v1/tasks/task", 503, True, False),
        ("/api/v1/tasks/task", 500, False, False),
        ("/api/v1/projects/project/events", 500, True, False),
        ("/api/v1/auth/login", 500, True, False),
    ],
)
def test_error_boundary_only_swallows_completed_project_http_failures(
    path: str, status: int, complete: bool, suppressed: bool
) -> None:
    messages: list[Message] = []

    async def app(_scope: Scope, _receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send(
            {"type": "http.response.body", "body": b"safe response", "more_body": not complete}
        )
        raise RuntimeError("private exception details")

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        messages.append(message)

    async def run() -> None:
        await ProjectErrorBoundary(app)({"type": "http", "path": path}, receive, send)

    if suppressed:
        asyncio.run(run())
    else:
        with pytest.raises(RuntimeError, match="private exception details"):
            asyncio.run(run())
    assert messages[-1]["body"] == b"safe response"
