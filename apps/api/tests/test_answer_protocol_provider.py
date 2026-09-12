import json
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from cairn_api.app import create_app
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import AnswerEvidence, OpenAIAnswerProvider
from cairn_api.knowledge.object_store import ObjectStore
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from pydantic import ValidationError

OUTPUT = json.dumps(
    {"status": "answered", "paragraphs": [{"text": "grounded", "citationIds": ["S1"]}]}
)
RESPONSES: list[tuple[str, str, str, object]] = [
    (
        "openai-compatible",
        "/v1/chat/completions",
        "authorization",
        {"choices": [{"finish_reason": "stop", "message": {"content": OUTPUT}}]},
    ),
    (
        "openai-responses",
        "/v1/responses",
        "authorization",
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": OUTPUT}],
                }
            ],
        },
    ),
    (
        "anthropic",
        "/v1/messages",
        "x-api-key",
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": OUTPUT}]},
    ),
    (
        "gemini",
        "/v1/models/configured-model:generateContent",
        "x-goog-api-key",
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": OUTPUT}]}}]},
    ),
]


@pytest.mark.parametrize(("protocol", "path", "auth_header", "body"), RESPONSES)
def test_protocol_runs_through_bounded_http_provider(
    protocol: str,
    path: str,
    auth_header: str,
    body: object,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        assert request.headers[auth_header] in {"key", "Bearer key"}
        assert "tools" not in json.loads(request.content)
        return httpx.Response(200, json=body)

    provider = OpenAIAnswerProvider(
        protocol=protocol,  # pyright: ignore[reportArgumentType]
        base_url="https://provider.example/v1",
        api_key="key",
        model="configured-model",
        timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    answer = provider.generate(
        question="question",
        evidence=[
            AnswerEvidence(
                id="S1",
                chunk_id=UUID("00000000-0000-4000-8000-000000000001"),
                title="source",
                locator={"type": "text"},
                text="grounded",
            )
        ],
    )
    assert answer.paragraphs[0].text == "grounded"


def test_answer_protocol_setting_defaults_and_rejects_unknown() -> None:
    assert Settings().answer_protocol == "openai-compatible"
    with pytest.raises(ValidationError):
        Settings.model_validate({"answer_protocol": "unknown"})


def test_app_forwards_configured_protocol_and_closes_owned_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api import app as app_module

    owned = Mock()
    factory = Mock(return_value=owned)
    monkeypatch.setattr(app_module, "OpenAIAnswerProvider", factory)
    settings = Settings.model_validate(
        {
            "answer_base_url": "https://provider.example/v1",
            "answer_api_key": "key",
            "answer_model": "model",
            "answer_protocol": "anthropic",
        }
    )
    with TestClient(
        create_app(
            settings=settings, database=Mock(spec=Database), object_store=Mock(spec=ObjectStore)
        )
    ):
        pass
    assert factory.call_args.kwargs["protocol"] == "anthropic"
    owned.close.assert_called_once_with()


def test_anthropic_outgoing_schema_uses_supported_subset_and_local_limits_remain() -> None:
    from cairn_api.knowledge.answer_protocols import build_answer_request
    from cairn_api.knowledge.answer_provider import ANSWER_JSON_SCHEMA, ProviderAnswer
    from pydantic import ValidationError

    request = build_answer_request(
        protocol="anthropic",
        base_url="https://provider.test/v1",
        api_key="test-key",
        model="test-model",
        system_prompt="JSON",
        user_content="{}",
        answer_schema=ANSWER_JSON_SCHEMA,
    )
    encoded = json.dumps(request.body["output_config"])
    for unsupported in ["minLength", "maxLength", "maxItems"]:
        assert unsupported not in encoded
    with pytest.raises(ValidationError):
        ProviderAnswer.model_validate(
            {
                "status": "answered",
                "paragraphs": [{"text": "x" * 1001, "citationIds": ["S1"]}],
            }
        )


@pytest.mark.parametrize(
    "parts",
    [
        [{"text": OUTPUT, "thoughtSignature": "opaque-signature"}],
        [
            {"text": "PRIVATE-SUMMARY", "thought": True, "thoughtSignature": "hidden"},
            {"text": OUTPUT, "thought": False, "thoughtSignature": "opaque-signature"},
        ],
    ],
)
def test_gemini_provider_accepts_signed_answer_without_exposing_thoughts(
    parts: list[dict[str, object]],
) -> None:
    body = {"candidates": [{"finishReason": "STOP", "content": {"parts": parts}}]}
    test_protocol_runs_through_bounded_http_provider(
        "gemini",
        "/v1/models/configured-model:generateContent",
        "x-goog-api-key",
        body,
    )


@pytest.mark.parametrize(
    "part",
    [
        {"text": OUTPUT, "functionCall": {"name": "unsafe"}, "thoughtSignature": "signed"},
        {"text": OUTPUT, "thought": "false"},
        {"text": OUTPUT, "thoughtSignature": 42},
        {"text": "PRIVATE-SUMMARY", "thought": True},
    ],
)
def test_gemini_metadata_does_not_allow_tools_invalid_types_or_thought_only_answers(
    part: dict[str, object],
) -> None:
    from cairn_api.knowledge.answer_provider import AnswerProviderInvalidResponse

    with pytest.raises(AnswerProviderInvalidResponse):
        test_protocol_runs_through_bounded_http_provider(
            "gemini",
            "/v1/models/configured-model:generateContent",
            "x-goog-api-key",
            {"candidates": [{"finishReason": "STOP", "content": {"parts": [part]}}]},
        )
