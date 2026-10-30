from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import AnswerEvidence, AnswerGuidance
from cairn_api.knowledge.models import KnowledgeResource
from cairn_api.knowledge.plan_schemas import ProjectPlanDraft
from cairn_api.projects.models import Task
from sqlalchemy import delete, func, select

from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_search import SearchEmbedding
from .test_project_analysis import AnalysisProvider, seed_structure
from .test_project_conversations import assert_error, seed_conversation_boundary


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


class PlanProvider(AnalysisProvider):
    def __init__(self, change: Callable[[], None] = lambda: None) -> None:
        super().__init__(change)
        self.payload = plan_payload()

    def generate_project_plan(
        self, *, question: str, evidence: list[AnswerEvidence], guidance: AnswerGuidance | None
    ) -> ProjectPlanDraft:
        self.calls.append(evidence)
        self.change()
        return ProjectPlanDraft.model_validate(self.payload)


@pytest.mark.integration
def test_plan_preview_returns_evidence_and_dag_without_creating_project_objects(
    database: Database,
    test_database_url: str,
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    seed_structure(database, actor.organization_id, pid)
    provider = PlanProvider()
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        response = client.post(f"/api/v1/projects/{pid}/plan-preview")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["canApply"] is False
        assert body["plan"]["tasks"][1]["dependsOn"] == ["T1"]
        assert body["plan"]["stages"][0]["id"] == "P1"
        assert body["snapshot"]["project"]["id"] == str(pid)
        assert body["citations"][0]["id"] == "S2"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-request-id"]
        assert len(provider.calls) == 1
    with database.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(Task).where(Task.project_id == pid))
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "project.plan_previewed")
            )
            == 1
        )


@pytest.mark.integration
@pytest.mark.parametrize("change", ["task", "permission", "evidence"])
def test_plan_preview_discards_changed_project_or_evidence(
    database: Database,
    test_database_url: str,
    change: str,
) -> None:
    actor, pid, rid = seed_conversation_boundary(database)
    task_id = seed_structure(database, actor.organization_id, pid)

    def mutate() -> None:
        with database.session_factory.begin() as session:
            if change == "permission":
                session.execute(delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == pid))
            elif change == "task":
                task = session.get(Task, task_id)
                assert task is not None
                task.title = "变化后的任务"
            else:
                resource = session.get(KnowledgeResource, rid)
                assert resource is not None
                resource.deleted_at, resource.deleted_by = datetime.now(UTC), actor.user_id

    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        PlanProvider(mutate),
    ) as client:
        assert_error(
            client.post(f"/api/v1/projects/{pid}/plan-preview"), 409, "project_analysis_changed"
        )


@pytest.mark.integration
def test_plan_preview_enforces_csrf_access_and_rejects_unknown_citations(
    database: Database,
    test_database_url: str,
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    private = seed_project(database, actor, permission=None)
    provider = PlanProvider()
    provider.payload["citationIds"] = ["S6"]
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        assert_error(client.post(f"/api/v1/projects/{private}/plan-preview"), 404, "not_found")
        assert (
            client.post(
                f"/api/v1/projects/{pid}/plan-preview", headers={"X-CSRF-Token": "wrong"}
            ).status_code
            == 403
        )
        assert provider.calls == []
        assert_error(client.post(f"/api/v1/projects/{pid}/plan-preview"), 503, "answer_unavailable")


@pytest.mark.integration
def test_plan_preview_can_report_insufficient_evidence_without_invented_nodes(
    database: Database,
    test_database_url: str,
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    provider = PlanProvider()
    provider.payload.update(
        status="insufficient_evidence",
        summary="请先明确项目目标",
        stages=[],
        milestones=[],
        tasks=[],
        citationIds=[],
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        response = client.post(f"/api/v1/projects/{pid}/plan-preview")
        assert response.status_code == 200
        assert response.json()["plan"]["status"] == "insufficient_evidence"
        assert response.json()["plan"]["tasks"] == []
