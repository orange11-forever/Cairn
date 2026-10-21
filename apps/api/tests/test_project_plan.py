from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from cairn_api.knowledge.answer_provider import AnswerEvidence, OpenAIAnswerProvider
from cairn_api.knowledge.plan_schemas import ProjectPlanDraft
from pydantic import ValidationError


def plan_payload() -> dict[str, object]:
    return {
        "status": "planned",
        "summary": "补齐发布验收",
        "assumptions": ["部署窗口由成员确认"],
        "citationIds": ["S1"],
        "stages": [{"id": "P1", "name": "发布准备", "goal": "满足发布条件", "citationIds": ["S1"]}],
        "milestones": [
            {
                "id": "M1",
                "stageId": "P1",
                "name": "发布就绪",
                "acceptanceCriteria": "关键检查通过",
                "citationIds": ["S1"],
            }
        ],
        "tasks": [
            {
                "id": "T1",
                "stageId": "P1",
                "milestoneId": "M1",
                "title": "确认窗口",
                "description": "与负责人确认部署时间",
                "acceptanceCriteria": "记录部署窗口",
                "priority": "high",
                "dependsOn": [],
                "citationIds": ["S1"],
            },
            {
                "id": "T2",
                "stageId": "P1",
                "milestoneId": "M1",
                "title": "执行检查",
                "description": "按验收说明检查",
                "acceptanceCriteria": "保存检查结果",
                "priority": "high",
                "dependsOn": ["T1"],
                "citationIds": ["S1"],
            },
        ],
    }


def test_valid_plan_keeps_stage_milestone_task_relationships() -> None:
    plan = ProjectPlanDraft.model_validate(plan_payload())
    assert plan.tasks[1].depends_on == ["T1"]
    assert plan.milestones[0].stage_id == plan.stages[0].id


@pytest.mark.parametrize(
    "invalid",
    ["cycle", "self", "unknown", "duplicate", "stage", "milestone", "empty", "insufficient"],
)
def test_plan_rejects_invalid_graphs_and_status(invalid: str) -> None:
    payload = deepcopy(plan_payload())
    tasks = payload["tasks"]
    assert isinstance(tasks, list)
    if invalid == "cycle":
        tasks[0]["dependsOn"] = ["T2"]
    elif invalid == "self":
        tasks[0]["dependsOn"] = ["T1"]
    elif invalid == "unknown":
        tasks[0]["dependsOn"] = ["T9"]
    elif invalid == "duplicate":
        tasks[1]["id"] = "T1"
    elif invalid == "stage":
        tasks[0]["stageId"] = "P5"
    elif invalid == "milestone":
        tasks[0]["milestoneId"] = "M8"
    elif invalid == "empty":
        payload["tasks"] = []
    elif invalid == "insufficient":
        payload["status"] = "insufficient_evidence"
    with pytest.raises(ValidationError):
        ProjectPlanDraft.model_validate(payload)


@pytest.mark.parametrize(
    "protocol", ["openai-compatible", "openai-responses", "anthropic", "gemini"]
)
def test_plan_provider_uses_selected_protocol_and_validates_output(protocol: str) -> None:
    import json

    calls: list[httpx.Request] = []
    content = json.dumps(plan_payload())

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if protocol == "openai-compatible":
            body = {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        elif protocol == "openai-responses":
            body = {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                ],
            }
        elif protocol == "anthropic":
            body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": content}]}
        else:
            body = {
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}]
            }
        return httpx.Response(200, json=body)

    provider = OpenAIAnswerProvider(
        base_url="https://controlled.example/v1",
        api_key="synthetic",
        model="planner",
        timeout_seconds=10,
        protocol=protocol,  # pyright: ignore[reportArgumentType]
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    plan = provider.generate_project_plan(
        question="生成后续规划",
        evidence=[
            AnswerEvidence(
                id="S1", chunk_id=uuid4(), title="项目", locator={}, text="已完成基础建设"
            )
        ],
        guidance=None,
    )
    assert plan.tasks[1].depends_on == ["T1"]
    assert len(calls) == 1
    assert b"8192" in calls[0].content
