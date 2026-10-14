import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import OpenAIAnswerProvider

from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_conversation_streaming import events
from .test_knowledge_search import SearchEmbedding
from .test_project_conversations import assert_error, create, seed_conversation_boundary


@pytest.mark.integration
def test_allowlisted_selection_routes_requests_and_keeps_historical_model(
    database: Database, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((payload["model"], request.headers["authorization"]))
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
                                    "paragraphs": [{"text": "9月30日交付", "citationIds": ["S1"]}],
                                }
                            ),
                        },
                    }
                ]
            },
        )

    def provider(**kwargs: Any) -> OpenAIAnswerProvider:
        return OpenAIAnswerProvider(
            **kwargs, client=httpx.Client(transport=httpx.MockTransport(respond))
        )

    monkeypatch.setattr("cairn_api.app.OpenAIAnswerProvider", provider)
    settings = knowledge_settings(
        test_database_url,
        answer_models=[
            {
                "id": "fast",
                "name": "快速模型",
                "model": "synthetic-fast",
                "protocol": "openai-compatible",
                "base_url": "https://controlled.example/v1",
                "api_key": "fast-secret",
            },
            {
                "id": "reasoning",
                "name": "推理模型",
                "model": "synthetic-reasoner",
                "protocol": "openai-compatible",
                "base_url": "https://controlled.example/v1",
                "api_key": "reasoning-secret",
            },
        ],
    )
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        settings, database, actor, MemoryObjectStore(), SearchEmbedding()
    ) as client:
        response = client.get(prefix + "/answer-model")
        assert response.status_code == 200
        catalog = response.json()
        assert catalog["configured"] is True
        assert catalog["defaultModelId"] == "fast"
        assert [item["id"] for item in catalog["models"]] == ["fast", "reasoning"]
        assert "secret" not in response.text and "controlled.example" not in response.text
        config: dict[str, object] = {
            "name": "岑宁",
            "instructions": "",
            "enabledSkillIds": [],
            "expectedRevision": 0,
            "modelId": "reasoning",
        }
        saved = client.put(prefix + "/assistant-settings", json=config)
        assert saved.status_code == 200
        assert saved.json()["modelId"] == "reasoning"
        assert client.get(prefix + "/assistant-settings").json() == saved.json()
        cid, tid = create(client, prefix), str(uuid4())
        turn = {
            "id": tid,
            "expectedRevision": 1,
            "assistantRevision": 1,
            "question": "什么时候交付？",
        }
        answered = client.post(f"{prefix}/conversations/{cid}/turns", json=turn)
        assert answered.status_code == 200
        assert answered.json()["turns"][0]["model"] == catalog["models"][1]
        assert calls == [("synthetic-reasoner", "Bearer reasoning-secret")]
        changed = client.put(
            prefix + "/assistant-settings",
            json={**config, "expectedRevision": 1, "modelId": "fast"},
        )
        assert changed.json()["revision"] == 2
        # A saved request remains replayable after switching models.
        assert (
            client.post(f"{prefix}/conversations/{cid}/turns", json=turn).json() == answered.json()
        )
        assert_error(
            client.post(
                f"{prefix}/conversations/{cid}/turns",
                json={**turn, "id": str(uuid4()), "expectedRevision": 2},
            ),
            409,
            "assistant_changed",
        )
        next_turn = client.post(
            f"{prefix}/conversations/{cid}/turns",
            json={**turn, "id": str(uuid4()), "expectedRevision": 2, "assistantRevision": 2},
        )
        assert next_turn.status_code == 200
        assert [item["model"]["id"] for item in next_turn.json()["turns"]] == ["reasoning", "fast"]
        assert calls[-1] == ("synthetic-fast", "Bearer fast-secret")
        assert_error(
            client.put(
                prefix + "/assistant-settings",
                json={**config, "expectedRevision": 2, "modelId": "unlisted"},
            ),
            422,
            "model_not_available",
        )
        assert client.get(prefix + "/assistant-settings").json()["revision"] == 2
        last_detail = next_turn.json()
    # Restart with the selected model removed; retain history and never substitute another model.
    reduced = settings.model_copy(update={"answer_models": settings.answer_models[1:]})
    with knowledge_client(
        reduced, database, actor, MemoryObjectStore(), SearchEmbedding()
    ) as client:
        assert client.get(prefix + "/answer-model").json()["defaultModelId"] == "reasoning"
        assert client.get(prefix + "/assistant-settings").json()["modelId"] == "fast"
        assert client.get(f"{prefix}/conversations/{cid}").json() == last_detail
        before = len(calls)
        for suffix in ("turns", "turns/stream"):
            response = client.post(
                f"{prefix}/conversations/{cid}/{suffix}",
                json={**turn, "id": str(uuid4()), "expectedRevision": 3, "assistantRevision": 2},
            )
            assert_error(response, 503, "model_not_available")
            assert response.headers["content-type"] == "application/json"
        assert len(calls) == before
        assert client.post(f"{prefix}/conversations/{cid}/turns", json=turn).json() == last_detail


@pytest.mark.integration
def test_selected_responses_model_streams_and_saves_its_own_metadata(
    database: Database, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    calls: list[str] = []
    answer = json.dumps(
        {"status": "answered", "paragraphs": [{"text": "9月30日交付", "citationIds": ["S1"]}]}
    )

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload["model"])
        assert request.url.path == "/v1/responses"
        assert payload["stream"] is True
        assert request.headers["authorization"] == "Bearer responses-secret"
        response_body = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": answer}],
                }
            ],
        }
        wire = "".join(
            "data: " + json.dumps(frame) + "\n\n"
            for frame in [
                {"type": "response.output_text.delta", "delta": answer},
                {"type": "response.completed", "response": response_body},
            ]
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=wire,
        )

    def provider(**kwargs: Any) -> OpenAIAnswerProvider:
        return OpenAIAnswerProvider(
            **kwargs, client=httpx.Client(transport=httpx.MockTransport(respond))
        )

    monkeypatch.setattr("cairn_api.app.OpenAIAnswerProvider", provider)
    settings = knowledge_settings(
        test_database_url,
        answer_models=[
            {
                "id": "standard",
                "name": "常规模型",
                "model": "synthetic-standard",
                "protocol": "openai-compatible",
                "base_url": "https://controlled.example/v1",
                "api_key": "standard-secret",
            },
            {
                "id": "responses",
                "name": "流式模型",
                "model": "synthetic-responses",
                "protocol": "openai-responses",
                "base_url": "https://controlled.example/v1",
                "api_key": "responses-secret",
            },
        ],
    )
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        settings, database, actor, MemoryObjectStore(), SearchEmbedding()
    ) as client:
        saved = client.put(
            prefix + "/assistant-settings",
            json={
                "name": "岑宁",
                "instructions": "",
                "enabledSkillIds": [],
                "expectedRevision": 0,
                "modelId": "responses",
            },
        )
        assert saved.status_code == 200
        cid = create(client, prefix)
        body = {
            "id": str(uuid4()),
            "question": "何时交付？",
            "expectedRevision": 1,
            "assistantRevision": 1,
        }
        response = client.post(f"{prefix}/conversations/{cid}/turns/stream", json=body)
        assert response.status_code == 200
        frames = events(response)
        assert [frame["type"] for frame in frames] == ["paragraph", "complete"]
        detail = frames[-1]["conversation"]
        assert detail["turns"][0]["model"] == {
            "id": "responses",
            "name": "流式模型",
            "model": "synthetic-responses",
            "protocol": "openai-responses",
        }
        assert client.get(f"{prefix}/conversations/{cid}").json() == detail
        assert calls == ["synthetic-responses"]
