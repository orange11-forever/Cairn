"""Exercise response lifetime cleanup before the async body generator starts."""

import asyncio
from collections.abc import Callable
from threading import BoundedSemaphore, Event
from typing import cast
from uuid import uuid4

import anyio
import pytest
from cairn_api.knowledge import conversation_streaming
from cairn_api.knowledge.answer_schemas import KnowledgeAnswerParagraph
from cairn_api.knowledge.conversation_service import KnowledgeConversationService
from fastapi import Request
from starlette.types import Message, Scope


@pytest.mark.parametrize(
    ("failure", "version"),
    [("disconnect", "2.3"), ("send-failure", "2.3"), ("send-failure", "2.4")],
)
def test_pre_iterator_disconnect_or_start_send_failure_closes_worker_and_releases_admission(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    version: str,
) -> None:
    """Removing response-level cleanup leaves a full queue and occupied worker forever."""
    capacity = BoundedSemaphore(1)
    monkeypatch.setattr(conversation_streaming, "STREAM_WORKERS", capacity)
    closed, third_started = Event(), Event()

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    class Service:
        def close(self) -> None:
            closed.set()

    def append(
        service: KnowledgeConversationService,
        *,
        on_paragraph: Callable[[KnowledgeAnswerParagraph], None],
        check_cancelled: Callable[[], None],
        wait_for_delivery: Callable[[], None],
    ) -> object:
        for index in range(3):
            if index == 2:
                third_started.set()
            wait_for_delivery()
            check_cancelled()
            on_paragraph(KnowledgeAnswerParagraph(text=f"第{index}段", citationIds=["S1"]))
        raise AssertionError("disconnected worker must never complete")

    async def scenario() -> None:
        messages: list[str] = []
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": version},
            "method": "POST",
            "path": "/",
            "headers": [],
        }

        async def until(predicate: Callable[[], bool]) -> bool:
            for _ in range(200):
                if predicate():
                    return True
                await asyncio.sleep(0.005)
            return False

        async def receive() -> Message:
            if failure == "disconnect":
                await asyncio.sleep(0)
                return {"type": "http.disconnect"}
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

        async def send(message: Message) -> None:
            messages.append(message["type"])
            if failure == "send-failure":
                raise RuntimeError("response start failed")
            await asyncio.sleep(0.1)

        response = await conversation_streaming.conversation_stream(
            cast(Request, ConnectedRequest()),
            build_service=lambda: cast(KnowledgeConversationService, Service()),
            append=append,
            conversation_id=uuid4(),
            turn_id=uuid4(),
            trace_id="cleanup-test",
        )
        assert await until(third_started.is_set), (
            "worker must be blocked on full queue before ASGI starts"
        )
        with anyio.fail_after(2):
            if failure == "send-failure":
                with pytest.raises(RuntimeError, match="response start failed"):
                    await response(scope, receive, send)
            else:
                await response(scope, receive, send)
        assert messages == ["http.response.start"], "body must remain unstarted in this regression"
        assert await until(closed.is_set), "worker service must close even with unstarted body"
        assert await until(lambda: capacity.acquire(blocking=False)), (
            "worker admission must be released"
        )
        capacity.release()

    asyncio.run(scenario())
