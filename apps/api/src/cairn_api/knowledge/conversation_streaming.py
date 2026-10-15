"""Bounded SSE transport; each generation owns its database session."""

import asyncio
from collections.abc import AsyncIterable, Callable, Mapping
from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Thread

from fastapi import Request
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from cairn_api.db.errors import DATABASE_UNAVAILABLE_ERRORS
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.answer_schemas import KnowledgeAnswerParagraph
from cairn_api.knowledge.conversation_schemas import (
    KnowledgeConversationCompleteEvent,
    KnowledgeConversationErrorEvent,
    KnowledgeConversationParagraphEvent,
)
from cairn_api.knowledge.conversation_service import KnowledgeConversationService

# Bound the same long-lived network work that the synchronous API threadpool bounds.
STREAM_WORKERS = BoundedSemaphore(16)


class CancellableConversationResponse(StreamingResponse):
    def __init__(
        self,
        content: AsyncIterable[str],
        *,
        cancelled: Event,
        headers: Mapping[str, str],
    ) -> None:
        super().__init__(content, media_type="text/event-stream", headers=headers)
        self._cancelled = cancelled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # ASGI can finish or fail during response.start before body() is first
        # iterated. An unstarted generator never executes its finally block.
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._cancelled.set()


class GenerationCancelled(Exception):
    pass


type StreamItem = (
    KnowledgeConversationParagraphEvent | KnowledgeConversationCompleteEvent | ApiProblem
)


async def conversation_stream(
    request: Request,
    *,
    build_service: Callable[[], KnowledgeConversationService],
    append: Callable[..., object],
    conversation_id: object,
    turn_id: object,
    trace_id: str,
) -> StreamingResponse:
    if not STREAM_WORKERS.acquire(blocking=False):
        raise ApiProblem(
            status_code=503,
            code="answer_unavailable",
            message="生成式回答暂时不可用",
            headers={"Retry-After": "1"},
        )
    queue: Queue[StreamItem] = Queue(maxsize=1)
    cancelled = Event()

    def check_cancelled() -> None:
        if cancelled.is_set():
            raise GenerationCancelled()

    def wait_for_delivery() -> None:
        while queue.full():
            if cancelled.wait(0.025):
                raise GenerationCancelled()
        check_cancelled()

    def send(item: StreamItem) -> None:
        try:
            wait_for_delivery()
        except GenerationCancelled:
            return
        queue.put_nowait(item)

    def worker() -> None:
        index = 0

        def paragraph(value: KnowledgeAnswerParagraph) -> None:
            nonlocal index
            check_cancelled()
            # append reserves capacity and performs fresh guards immediately before this.
            queue.put_nowait(
                KnowledgeConversationParagraphEvent.model_validate(
                    {
                        "conversationId": conversation_id,
                        "turnId": turn_id,
                        "type": "paragraph",
                        "index": index,
                        "paragraph": value,
                    }
                )
            )
            index += 1

        service = None
        try:
            check_cancelled()
            service = build_service()
            result = append(
                service,
                on_paragraph=paragraph,
                check_cancelled=check_cancelled,
                wait_for_delivery=wait_for_delivery,
            )
            send(
                KnowledgeConversationCompleteEvent.model_validate(
                    {
                        "conversationId": conversation_id,
                        "turnId": turn_id,
                        "type": "complete",
                        "conversation": result,
                    }
                )
            )
        except GenerationCancelled:
            pass
        except DATABASE_UNAVAILABLE_ERRORS:
            if not cancelled.is_set():
                send(
                    ApiProblem(
                        status_code=503, code="database_unavailable", message="数据库暂时不可用"
                    )
                )
        except ApiProblem as problem:
            if not cancelled.is_set():
                send(problem)
        except Exception:  # noqa: BLE001
            if not cancelled.is_set():
                send(ApiProblem(status_code=500, code="internal_error", message="服务器内部错误"))
        finally:
            try:
                if service is not None:
                    service.close()
            finally:
                STREAM_WORKERS.release()

    try:
        Thread(target=worker, name="conversation-stream", daemon=True).start()
    except BaseException:
        STREAM_WORKERS.release()
        raise

    async def next_item() -> StreamItem:
        while True:
            if await request.is_disconnected():
                cancelled.set()
                raise asyncio.CancelledError()
            try:
                return queue.get_nowait()
            except Empty:
                await asyncio.sleep(0.025)

    try:
        first = await next_item()
    except BaseException:
        cancelled.set()
        raise
    if isinstance(first, ApiProblem):
        cancelled.set()
        raise first

    async def body():
        item = first
        try:
            while True:
                if isinstance(item, ApiProblem):
                    error = KnowledgeConversationErrorEvent.model_validate(
                        {
                            "conversationId": conversation_id,
                            "turnId": turn_id,
                            "type": "error",
                            "status": item.status_code,
                            "code": item.code,
                            "message": item.message,
                            "traceId": trace_id,
                            "retryAfter": next(
                                (v for k, v in item.headers.items() if k.lower() == "retry-after"),
                                None,
                            ),
                        }
                    )
                    yield "data: " + error.model_dump_json(by_alias=True) + "\n\n"
                    return
                yield "data: " + item.model_dump_json(by_alias=True) + "\n\n"
                if isinstance(item, KnowledgeConversationCompleteEvent):
                    return
                item = await next_item()
        finally:
            cancelled.set()

    return CancellableConversationResponse(
        body(),
        cancelled=cancelled,
        headers={
            "Cache-Control": "private, no-store",
            "X-Accel-Buffering": "no",
            "X-Request-ID": trace_id,
        },
    )
