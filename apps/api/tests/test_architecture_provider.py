import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from cairn_api.knowledge.answer_protocols import AnswerProtocol
from cairn_api.knowledge.answer_provider import (
    AnswerEvidence,
    AnswerGuidance,
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
    OpenAIAnswerProvider,
)


def architecture_answer() -> dict[str, Any]:
    return {
        "status": "answered",
        "paragraphs": [{"text": "入口调用存储模块。", "citationIds": ["S1"]}],
        "graph": {
            "nodes": [
                {"id": "entry", "label": "入口", "description": "处理请求", "citationIds": ["S1"]},
                {"id": "store", "label": "存储", "description": "保存记录", "citationIds": ["S2"]},
            ],
            "edges": [
                {"source": "entry", "target": "store", "label": "写入记录", "basis": "inferred", "citationIds": ["S1", "S2"]},
                {"source": "store", "target": "entry", "label": "返回结果", "basis": "direct", "citationIds": ["S2"]},
            ],
        },
    }


def evidence() -> list[AnswerEvidence]:
    return [AnswerEvidence(id=id_, chunk_id=uuid4(), title=path, locator={"type": "code"}, text=text)
            for id_, path, text in [("S1", "main.py", "store.save(request)"), ("S2", "store.py", "return result")]]


@pytest.mark.parametrize("protocol", ["openai-compatible", "openai-responses", "anthropic", "gemini"])
def test_architecture_returns_cited_nodes_and_directed_cycles_in_one_model_call(protocol: AnswerProtocol) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        text = json.dumps(architecture_answer())
        if protocol == "openai-compatible":
            body = {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}
        elif protocol == "openai-responses":
            body = {"status": "completed", "output": [{"type": "message", "status": "completed", "content": [{"type": "output_text", "text": text}]}]}
        elif protocol == "anthropic":
            body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}
        else:
            body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}
        return httpx.Response(200, json=body)

    provider = OpenAIAnswerProvider(base_url="https://model.example/v1", api_key="secret", model="chosen-model",
        timeout_seconds=5, protocol=protocol, client=httpx.Client(transport=httpx.MockTransport(handle)))
    result = provider.generate_architecture(question="解析架构", evidence=evidence(), guidance=AnswerGuidance(
        assistant_name="架构助手", instructions="关注存储", skill_id=None, skill_instructions="", resources=[]))
    assert result.graph.nodes[0].label == "入口"
    assert result.graph.edges[0].basis == "inferred"
    assert result.graph.edges[1].target == "entry"
    assert len(requests) == 1
    sent = json.loads(requests[0].content)
    serialized = json.dumps(sent, ensure_ascii=False)
    assert "store.save(request)" in serialized and "关注存储" in serialized
    assert "chunk_id" not in serialized
    if protocol == "openai-responses":
        schema = sent["text"]["format"]["schema"]
        assert "graph" in schema["required"]
        assert sent["store"] is False


@pytest.mark.parametrize("invalid", ["unknown-source", "unknown-target", "duplicate-node", "duplicate-edge", "empty-node", "missing-graph", "false-insufficient", "too-many-nodes", "truncated"])
def test_invalid_architecture_graph_is_rejected(invalid: str) -> None:
    answer = architecture_answer()
    if invalid == "unknown-source":
        answer["graph"]["edges"][0]["citationIds"] = ["missing"]
    elif invalid == "unknown-target":
        answer["graph"]["edges"][0]["target"] = "missing"
    elif invalid == "duplicate-node":
        answer["graph"]["nodes"][1]["id"] = "entry"
    elif invalid == "duplicate-edge":
        answer["graph"]["edges"].append(answer["graph"]["edges"][0])
    elif invalid == "empty-node":
        answer["graph"]["nodes"][0]["label"] = "   "
    elif invalid == "missing-graph":
        del answer["graph"]
    elif invalid == "false-insufficient":
        answer["status"] = "insufficient_evidence"
        answer["paragraphs"] = []
    elif invalid == "too-many-nodes":
        answer["graph"]["nodes"] = [{**answer["graph"]["nodes"][0], "id": f"n{i}"} for i in range(13)]
    provider = OpenAIAnswerProvider(base_url="https://model.example/v1", api_key="secret", model="model", timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{
            "finish_reason": "length" if invalid == "truncated" else "stop", "message": {"content": json.dumps(answer)},
        }]}))))
    with pytest.raises(AnswerProviderInvalidResponse):
        provider.generate_architecture(question="架构", evidence=evidence(), guidance=None)


def test_architecture_unavailable_is_reported_without_retry() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503)

    provider = OpenAIAnswerProvider(base_url="https://model.example/v1", api_key="secret", model="model", timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(AnswerProviderUnavailable):
        provider.generate_architecture(question="架构", evidence=evidence(), guidance=None)
    assert len(requests) == 1
