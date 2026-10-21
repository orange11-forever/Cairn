import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_models import AnswerModelOption, ConfiguredAnswerModel
from cairn_api.knowledge.answer_provider import (
    AnswerEvidence,
    AnswerGuidance,
    AnswerHistoryTurn,
    AnswerProviderUnavailable,
    ProviderAnswer,
    ProviderParagraph,
)
from cairn_api.knowledge.models import KnowledgeResource
from cairn_api.knowledge.search_service import KnowledgeSearchService
from cairn_api.projects.models import Milestone, Project, ProjectStage, Task, TaskDependency
from sqlalchemy import delete, select

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_search import SearchEmbedding
from .test_project_conversations import assert_error, seed_conversation_boundary


class AnalysisProvider:
    def __init__(self, change: Callable[[], None] = lambda: None) -> None:
        self.calls: list[list[AnswerEvidence]] = []
        self.questions: list[str] = []
        self.change = change
        self.citation_ids = ["S1"]

    def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
        self.calls.append(evidence)
        self.questions.append(question)
        self.change()
        return ProviderAnswer(
            status="answered",
            paragraphs=[
                ProviderParagraph(
                    text="进展：项目已建立。风险：验收资料待补充。", citationIds=self.citation_ids
                )
            ],
        )

    def generate_with_guidance(
        self,
        *,
        question: str,
        evidence: list[AnswerEvidence],
        history: list[AnswerHistoryTurn],
        guidance: AnswerGuidance,
    ) -> ProviderAnswer:
        assert history == []
        return self.generate(question=question, evidence=evidence)


def seed_structure(database: Database, org_id: UUID, project_id: UUID) -> UUID:
    stage_id, milestone_id, first, second = uuid4(), uuid4(), uuid4(), uuid4()
    with database.session_factory.begin() as session:
        project = session.get(Project, project_id)
        assert project is not None
        project.name = "交付项目"
        project.description = "交付可验收的版本"
        session.add(
            ProjectStage(id=stage_id, org_id=org_id, project_id=project_id, name="交付阶段")
        )
        session.flush()
        session.add(
            Milestone(
                id=milestone_id,
                org_id=org_id,
                project_id=project_id,
                stage_id=stage_id,
                name="发布验收",
                acceptance_criteria="全部关键检查通过",
            )
        )
        session.flush()
        session.add_all(
            [
                Task(
                    id=first, org_id=org_id, project_id=project_id, title="准备验收", status="done"
                ),
                Task(
                    id=second,
                    org_id=org_id,
                    project_id=project_id,
                    title="发布版本",
                    status="blocked",
                    stage_id=stage_id,
                    milestone_id=milestone_id,
                    description="等待部署窗口",
                    acceptance_criteria="生产可访问",
                    due_at=datetime(2026, 10, 20, tzinfo=UTC),
                ),
            ]
        )
        session.flush()
        session.add(
            TaskDependency(
                org_id=org_id,
                project_id=project_id,
                predecessor_task_id=first,
                successor_task_id=second,
            )
        )
    return second


@pytest.mark.integration
def test_analysis_reads_real_structure_and_authorized_knowledge_without_project_writes(
    database: Database,
    test_database_url: str,
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    task_id = seed_structure(database, actor.organization_id, pid)
    other = seed_project(database, actor, permission=None)
    with database.session_factory.begin() as session:
        session.add(Task(org_id=actor.organization_id, project_id=other, title="不可见任务"))
    provider = AnalysisProvider()
    provider.citation_ids = ["S1", "S2"]
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        response = client.post(f"/api/v1/projects/{pid}/analysis")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["projectId"] == str(pid)
        assert body["status"] == "answered"
        assert body["snapshot"]["project"]["description"] == "交付可验收的版本"
        assert len(body["snapshot"]["tasks"]) == 2
        assert len(body["snapshot"]["dependencies"]) == 1
        assert body["snapshot"]["stages"][0]["name"] == "交付阶段"
        assert body["snapshot"]["milestones"][0]["acceptanceCriteria"] == "全部关键检查通过"
        assert body["citations"][0]["id"] == "S2"
        assert body["citations"][0]["title"] == "私有证据标题"
        assert body["assistantName"] == "岑宁"
        assert body["model"]["id"] == "default"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-request-id"]
    evidence = provider.calls[0]
    assert body["generatedAt"][:10] in provider.questions[0]
    snapshot = json.loads(evidence[0].text)
    assert snapshot["project"]["name"] == "交付项目"
    assert str(task_id) in evidence[0].text
    assert "不可见任务" not in response.text + str(evidence)
    assert evidence[1].id == "S2"
    with database.session_factory() as session:
        task = session.get(Task, task_id)
        assert task is not None and task.status == "blocked" and task.revision == 1
        audits = list(
            session.scalars(select(AuditLog).where(AuditLog.action == "project.analyzed"))
        )
        assert len(audits) == 1
        assert "等待部署窗口" not in str(audits[0].details)


@pytest.mark.integration
def test_analysis_works_without_knowledge_and_honors_selected_model(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.VIEWER)
    pid = seed_project(database, actor, permission="read")
    first, selected = AnalysisProvider(), AnalysisProvider()
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        first,
    ) as client:
        client.app.state.answer_models["selected"] = ConfiguredAnswerModel(  # type: ignore[union-attr]
            info=AnswerModelOption(
                id="selected", name="分析模型", model="synthetic", protocol="openai-compatible"
            ),
            provider=selected,
        )
        settings = client.put(
            f"/api/v1/projects/{pid}/knowledge/assistant-settings",
            json={
                "name": "项目顾问",
                "instructions": "明确标出推断",
                "enabledSkillIds": [],
                "expectedRevision": 0,
                "modelId": "selected",
            },
        )
        assert settings.status_code == 200
        response = client.post(f"/api/v1/projects/{pid}/analysis")
        assert response.status_code == 200, response.text
        assert response.json()["citations"] == []
        assert response.json()["snapshot"]["tasks"] == []
        assert response.json()["assistantName"] == "项目顾问"
        assert response.json()["model"]["id"] == "selected"
        assert first.calls == [] and len(selected.calls) == 1


@pytest.mark.integration
@pytest.mark.parametrize("change", ["task", "project", "permission", "evidence", "logout"])
def test_analysis_discards_result_if_inputs_or_access_change_during_generation(
    database: Database,
    test_database_url: str,
    change: str,
) -> None:
    actor, pid, rid = seed_conversation_boundary(database)
    task_id = seed_structure(database, actor.organization_id, pid)

    def mutate() -> None:
        with database.session_factory.begin() as session:
            if change == "task":
                row = session.get(Task, task_id)
                assert row is not None
                row.status = "done"
            elif change == "project":
                project = session.get(Project, pid)
                assert project is not None
                project.description = "已更新的目标"
            elif change == "permission":
                session.execute(delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == pid))
            elif change == "logout":
                session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
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
        AnalysisProvider(mutate),
    ) as client:
        response = client.post(f"/api/v1/projects/{pid}/analysis")
        if change == "logout":
            assert_error(response, 401, "session_invalid")
        else:
            assert_error(response, 409, "project_analysis_changed")
        assert "进展" not in response.text and "私有证据标题" not in response.text


@pytest.mark.integration
def test_analysis_rejects_inaccessible_projects_csrf_and_missing_model(
    database: Database,
    test_database_url: str,
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    inaccessible = seed_project(database, actor, permission=None)
    foreign_actor = seed_actor(database, MembershipRole.OWNER)
    foreign = seed_project(database, foreign_actor, permission="read")
    provider = AnalysisProvider()
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        for target in (inaccessible, foreign, uuid4()):
            assert_error(client.post(f"/api/v1/projects/{target}/analysis"), 404, "not_found")
        response = client.post(
            f"/api/v1/projects/{pid}/analysis", headers={"X-CSRF-Token": "invalid"}
        )
        assert response.status_code == 403
        assert provider.calls == []
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        assert_error(client.post(f"/api/v1/projects/{pid}/analysis"), 503, "answer_unavailable")


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["unknown_citation", "unavailable"])
def test_analysis_provider_failures_do_not_publish_content(
    database: Database,
    test_database_url: str,
    failure: str,
) -> None:
    actor = seed_actor(database, MembershipRole.VIEWER)
    pid = seed_project(database, actor, permission="read")

    def fail() -> None:
        if failure == "unavailable":
            raise AnswerProviderUnavailable("secret-upstream")

    provider = AnalysisProvider(fail)
    provider.citation_ids = ["S6"]
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        response = client.post(f"/api/v1/projects/{pid}/analysis")
        assert_error(response, 503, "answer_unavailable")
        assert "secret-upstream" not in response.text


@pytest.mark.integration
def test_analysis_rejects_oversized_project_instead_of_silently_omitting_tasks(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.VIEWER)
    pid = seed_project(database, actor, permission="read")
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Task(org_id=actor.organization_id, project_id=pid, title=f"任务{i}")
                for i in range(101)
            ]
        )
    provider = AnalysisProvider()
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        assert_error(
            client.post(f"/api/v1/projects/{pid}/analysis"), 422, "project_analysis_too_large"
        )
        assert provider.calls == []


@pytest.mark.integration
@pytest.mark.parametrize("change", ["permission", "evidence", "logout"])
def test_analysis_rechecks_inputs_after_search_before_sending_data_to_model(
    database: Database,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from cairn_api.knowledge.schemas import KnowledgeSearchResponse

    actor, pid, rid = seed_conversation_boundary(database)
    original = KnowledgeSearchService.search

    def changed_search(self: KnowledgeSearchService, **kwargs: object) -> KnowledgeSearchResponse:
        result = original(self, **kwargs)  # pyright: ignore[reportArgumentType]
        with database.session_factory.begin() as session:
            if change == "permission":
                session.execute(delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == pid))
            elif change == "logout":
                session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
            else:
                resource = session.get(KnowledgeResource, rid)
                assert resource is not None
                resource.deleted_at, resource.deleted_by = datetime.now(UTC), actor.user_id
        return result

    monkeypatch.setattr(KnowledgeSearchService, "search", changed_search)
    provider = AnalysisProvider()
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        response = client.post(f"/api/v1/projects/{pid}/analysis")
        assert_error(
            response,
            401 if change == "logout" else 409,
            "session_invalid" if change == "logout" else "project_analysis_changed",
        )
        assert provider.calls == []
