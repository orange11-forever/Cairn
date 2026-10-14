import json
from threading import Event

import httpx
import pytest
from cairn_api.knowledge.answer_provider import (
    AnswerProviderInvalidResponse,
    OpenAIAnswerProvider,
    ProviderParagraph,
)

from .test_answer_provider import EVIDENCE


def event(kind: str, **data: object) -> bytes:
    return ("data: " + json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n\n").encode()


def completed(text: str) -> bytes:
    return event(
        "response.completed",
        response={
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        },
    )


def provider(stream: httpx.SyncByteStream) -> OpenAIAnswerProvider:
    def handle(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=stream)

    return OpenAIAnswerProvider(
        base_url="https://controlled.test/v1",
        api_key="synthetic",
        model="test",
        timeout_seconds=5,
        protocol="openai-responses",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )


def test_completed_paragraph_arrives_before_upstream_completion() -> None:
    """Removing the incremental callback fails before the second network read."""
    observed = Event()
    first = '{"status":"answered","paragraphs":[{"text":"早到的 \\"中文\\"。","citationIds":["S1"]}'
    tail = ',{"text":"第二段。","citationIds":["S1"]}]}'

    class Upstream(httpx.SyncByteStream):
        def __iter__(self):
            wire = event("response.output_text.delta", delta=first)
            for byte in wire:
                yield bytes([byte])
            assert observed.is_set(), "paragraph must arrive before reading completion"
            yield event("response.output_text.delta", delta=tail)
            yield completed(first + tail)

    seen: list[ProviderParagraph] = []

    def receive(paragraph: ProviderParagraph) -> None:
        seen.append(paragraph)
        observed.set()

    answer = provider(Upstream()).generate_stream(
        question="何时交付？",
        evidence=EVIDENCE,
        history=[],
        guidance=None,
        on_paragraph=receive,
        check_cancelled=lambda: None,
    )
    assert len(seen) == 2 and answer.paragraphs == seen


@pytest.mark.parametrize(
    "ending",
    [
        b"",
        event("response.failed"),
        event("response.incomplete"),
        event("response.refusal.delta", delta="secret"),
        event("error", message="secret"),
    ],
)
def test_stream_requires_completed_and_never_accepts_failure(ending: bytes) -> None:
    class Upstream(httpx.SyncByteStream):
        def __iter__(self):
            yield event(
                "response.output_text.delta",
                delta='{"status":"answered","paragraphs":[{"text":"早到","citationIds":["S1"]}]}',
            )
            yield ending

    with pytest.raises(AnswerProviderInvalidResponse):
        provider(Upstream()).generate_stream(
            question="何时交付？",
            evidence=EVIDENCE,
            history=[],
            guidance=None,
            on_paragraph=lambda _: None,
            check_cancelled=lambda: None,
        )


@pytest.mark.parametrize(
    "paragraphs",
    [
        [{"text": "未知", "citationIds": ["S9"]}],
        [{"text": "重复", "citationIds": ["S1", "S1"]}],
        [{"text": "x" * 1001, "citationIds": ["S1"]}],
        [{"text": "x", "citationIds": ["S1"]}] * 9,
        [{"text": "x" * 1000, "citationIds": ["S1"]}] * 7,
    ],
)
def test_stream_enforces_known_citations_and_all_answer_limits(
    paragraphs: list[dict[str, object]],
) -> None:
    text = json.dumps({"status": "answered", "paragraphs": paragraphs})

    class Upstream(httpx.SyncByteStream):
        def __iter__(self):
            yield event("response.output_text.delta", delta=text)
            yield completed(text)

    with pytest.raises(AnswerProviderInvalidResponse):
        provider(Upstream()).generate_stream(
            question="何时交付？",
            evidence=EVIDENCE,
            history=[],
            guidance=None,
            on_paragraph=lambda _: None,
            check_cancelled=lambda: None,
        )


@pytest.mark.parametrize(
    "wire", [b"data: " + b"x" * (256 * 1024), b"data: \xff\n\n", b"data: {invalid}\n\n"]
)
def test_stream_rejects_oversized_invalid_utf8_and_malformed_frames(wire: bytes) -> None:
    class Upstream(httpx.SyncByteStream):
        def __iter__(self):
            yield wire

    with pytest.raises(AnswerProviderInvalidResponse):
        provider(Upstream()).generate_stream(
            question="何时交付？",
            evidence=EVIDENCE,
            history=[],
            guidance=None,
            on_paragraph=lambda _: None,
            check_cancelled=lambda: None,
        )


def test_stream_final_response_must_agree_with_emitted_text_and_closes_upstream() -> None:
    closed = Event()
    original = '{"status":"answered","paragraphs":[{"text":"先到","citationIds":["S1"]}]}'

    class Upstream(httpx.SyncByteStream):
        def __iter__(self):
            yield event("response.output_text.delta", delta=original)
            yield completed(original.replace("先到", "篡改"))

        def close(self) -> None:
            closed.set()

    with pytest.raises(AnswerProviderInvalidResponse):
        provider(Upstream()).generate_stream(
            question="何时交付？",
            evidence=EVIDENCE,
            history=[],
            guidance=None,
            on_paragraph=lambda _: None,
            check_cancelled=lambda: None,
        )
    assert closed.is_set()
