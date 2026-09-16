from typing import cast

import pytest
from cairn_api.knowledge.answer_protocols import (
    AnswerProtocolError,
    build_answer_request,
    extract_answer_text,
)

SCHEMA: dict[str, object] = {"type": "object"}


@pytest.mark.parametrize(
    ("protocol", "endpoint", "header"),
    [
        ("openai-compatible", "/v1/chat/completions", "Authorization"),
        ("openai-responses", "/v1/responses", "Authorization"),
        ("anthropic", "/v1/messages", "x-api-key"),
        ("gemini", "/v1/models/model%2Fpath:generateContent", "x-goog-api-key"),
    ],
)
def test_protocol_builders_use_exact_endpoint_auth_and_bounded_shape(
    protocol: str,
    endpoint: str,
    header: str,
) -> None:
    request = build_answer_request(
        protocol=protocol,
        base_url="https://provider.test/v1",
        api_key="key",
        model="model/path" if protocol == "gemini" else "model",
        system_prompt="system",
        user_content="user",
        answer_schema=SCHEMA,
    )
    assert request.endpoint == f"https://provider.test{endpoint}"
    assert header in request.headers
    assert "tools" not in request.body
    if protocol == "openai-responses":
        assert request.body["store"] is False
        assert cast(dict[str, object], request.body["text"])["format"] == {
            "type": "json_schema",
            "name": "cairn_answer",
            "strict": True,
            "schema": SCHEMA,
        }
    if protocol == "anthropic":
        assert "output_config" in request.body and "output_format" not in request.body
    if protocol == "gemini":
        assert "responseFormat" in cast(dict[str, object], request.body["generationConfig"])


VALID: list[tuple[str, object, str]] = [
    (
        "openai-compatible",
        {"choices": [{"finish_reason": "stop", "message": {"content": "chat"}}]},
        "chat",
    ),
    (
        "openai-responses",
        {
            "status": "completed",
            "output": [
                {"type": "reasoning"},
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "responses"}],
                },
            ],
        },
        "responses",
    ),
    (
        "anthropic",
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "anthropic"}]},
        "anthropic",
    ),
    (
        "gemini",
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "gemini"}]}}]},
        "gemini",
    ),
]


@pytest.mark.parametrize(("protocol", "payload", "expected"), VALID)
def test_protocol_extractors_accept_only_completed_text(
    protocol: str,
    payload: object,
    expected: str,
) -> None:
    assert extract_answer_text(protocol=protocol, payload=payload) == expected


INVALID: list[tuple[str, object]] = [
    (
        "openai-compatible",
        {"choices": [{"finish_reason": "stop", "message": {"content": "{}", "refusal": "no"}}]},
    ),
    (
        "openai-responses",
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "refusal": "no",
                    "content": [{"type": "output_text", "text": "{}"}],
                }
            ],
        },
    ),
    ("openai-responses", {"status": "completed", "output": [{"type": "function_call"}]}),
    ("anthropic", {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "{}"}]}),
    ("anthropic", {"stop_reason": "end_turn", "content": [{"type": "tool_use"}]}),
    ("gemini", {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}),
    (
        "gemini",
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"functionCall": {}}]}}]},
    ),
]


@pytest.mark.parametrize(("protocol", "payload"), INVALID)
def test_protocol_extractors_reject_refusal_tools_safety_and_truncation(
    protocol: str,
    payload: object,
) -> None:
    with pytest.raises(AnswerProtocolError):
        extract_answer_text(protocol=protocol, payload=payload)
