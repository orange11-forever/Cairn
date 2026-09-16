import json
from uuid import UUID

import httpx
import pytest
from cairn_api.knowledge.answer_provider import (
    AnswerEvidence,
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
    OpenAIAnswerProvider,
)

EVIDENCE = [
    AnswerEvidence(
        id="S1",
        chunk_id=UUID("00000000-0000-4000-8000-000000000001"),
        title="项目说明.txt",
        locator={"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 2},
        text="项目的交付日期是 9 月 30 日。",
    )
]


def _provider(handler: httpx.MockTransport) -> OpenAIAnswerProvider:
    return OpenAIAnswerProvider(
        base_url="https://answers.example/v1",
        api_key="secret",
        model="answer-model",
        timeout_seconds=5,
        client=httpx.Client(transport=handler),
    )


def test_provider_sends_bounded_json_mode_request_and_accepts_cited_paragraphs() -> None:
    """Break caught: provider receives unstructured evidence or output bypasses citation parsing."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://answers.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        body = json.loads(request.content)
        assert body["model"] == "answer-model"
        assert body["stream"] is False
        assert body["response_format"] == {"type": "json_object"}
        assert body["max_tokens"] == 2048
        assert "tools" not in body
        user = json.loads(body["messages"][1]["content"])
        assert user == {
            "question": "什么时候交付？",
            "evidence": [
                {
                    "id": "S1",
                    "title": "项目说明.txt",
                    "locator": {"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 2},
                    "text": "项目的交付日期是 9 月 30 日。",
                }
            ],
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "status": "answered",
                                    "paragraphs": [
                                        {"text": "交付日期是 9 月 30 日。", "citationIds": ["S1"]}
                                    ],
                                }
                            ),
                        },
                    }
                ],
            },
        )

    answer = _provider(httpx.MockTransport(handle)).generate(
        question="什么时候交付？", evidence=EVIDENCE
    )

    assert answer.status == "answered"
    assert answer.paragraphs[0].citation_ids == ["S1"]


MALFORMED_OUTPUTS: list[object] = [
    {"status": "answered", "paragraphs": [{"text": "无引用", "citationIds": []}]},
    {"status": "answered", "paragraphs": [{"text": "未知引用", "citationIds": ["S2"]}]},
    {
        "status": "insufficient_evidence",
        "paragraphs": [{"text": "不应有正文", "citationIds": ["S1"]}],
    },
    {"status": "answered", "paragraphs": [{"text": "重复", "citationIds": ["S1", "S1"]}]},
]


@pytest.mark.parametrize("payload", MALFORMED_OUTPUTS)
def test_provider_rejects_outputs_that_break_answer_and_citation_invariants(
    payload: object,
) -> None:
    """Break caught: malformed model output is exposed as a trusted answer."""
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(payload),
                        },
                    }
                ],
            },
        )
    )

    with pytest.raises(AnswerProviderInvalidResponse):
        _provider(transport).generate(question="什么时候交付？", evidence=EVIDENCE)


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_provider_maps_all_http_failures_to_safe_unavailable(status: int) -> None:
    """Break caught: provider status or response body leaks through the public boundary."""
    provider = _provider(
        httpx.MockTransport(
            lambda _request: httpx.Response(status, text="sensitive provider details")
        )
    )

    with pytest.raises(AnswerProviderUnavailable) as raised:
        provider.generate(question="什么时候交付？", evidence=EVIDENCE)
    assert str(raised.value) == ""


def test_provider_rejects_truncation_tool_calls_and_oversized_bodies() -> None:
    """Break caught: partial/tool/oversized provider output is treated as a complete answer."""
    cases: list[dict[str, object]] = [
        {
            "choices": [
                {"finish_reason": "length", "message": {"role": "assistant", "content": "{}"}}
            ]
        },
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {"role": "assistant", "content": "{}", "tool_calls": [{}]},
                }
            ]
        },
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "{}", "refusal": "no"},
                }
            ]
        },
    ]
    for body in cases:

        def handle(
            _request: httpx.Request, response_body: dict[str, object] = body
        ) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        with pytest.raises(AnswerProviderInvalidResponse):
            _provider(httpx.MockTransport(handle)).generate(
                question="什么时候交付？", evidence=EVIDENCE
            )

    with pytest.raises(AnswerProviderInvalidResponse):
        _provider(
            httpx.MockTransport(
                lambda _request: httpx.Response(200, content=b"x" * (256 * 1024 + 1))
            )
        ).generate(question="什么时候交付？", evidence=EVIDENCE)
