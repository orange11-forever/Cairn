from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import (
    AnswerEvidence,
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
    ProviderAnswer,
    ProviderParagraph,
)
from cairn_api.knowledge.models import KnowledgeResource
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_search import SearchEmbedding, seed_search_resource


class AnswerStub:
    def __init__(self) -> None:
        self.evidence: list[AnswerEvidence] = []

    def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
        assert question == "什么时候交付?"
        self.evidence = evidence
        return ProviderAnswer(
            status="answered",
            paragraphs=[ProviderParagraph(text="9 月 30 日交付。", citationIds=["S1"])],
        )


class RaisingAnswerStub:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
        del question, evidence
        raise self.error


@pytest.mark.integration
def test_answer_route_returns_authorized_cited_response_with_protected_headers(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.VIEWER)
    project_id = seed_project(database, actor, permission="read")
    chunk_id = UUID("00000000-0000-4000-8000-000000000071")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="项目说明.pdf",
        chunks=[(chunk_id, "项目的交付日期是 9 月 30 日。", [1.0] + [0.0] * 1023)],
    )
    provider = AnswerStub()
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/answers",
            json={"question": "什么时候交付？"},
            headers={"X-Request-ID": "req-answer-integration"},
        )

    with database.session_factory() as session:
        answer_audit = session.scalar(
            select(AuditLog).where(
                AuditLog.trace_id == "req-answer-integration",
                AuditLog.action == "knowledge.answered",
            )
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-answer-integration"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["paragraphs"] == [{"text": "9 月 30 日交付。", "citationIds": ["S1"]}]
    assert response.json()["citations"][0]["id"] == "S1"
    assert response.json()["citations"][0]["chunkId"] == str(chunk_id)
    assert len(provider.evidence) == 1
    assert answer_audit is not None
    assert set(answer_audit.details) == {
        "questionLength",
        "questionDigest",
        "retrievalMode",
        "status",
        "paragraphCount",
        "sourceCount",
    }
    assert "什么时候交付" not in str(answer_audit.details)
    assert "9 月 30 日" not in str(answer_audit.details)


@pytest.mark.integration
def test_answer_route_fails_safely_when_optional_provider_is_disabled(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="项目说明.pdf",
        chunks=[(UUID("00000000-0000-4000-8000-000000000072"), "交付日期", [1.0] + [0.0] * 1023)],
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/answers",
            json={"question": "什么时候交付？"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "answer_unavailable"
    assert response.json()["traceId"] == response.headers["x-request-id"]


class DeleteEvidenceAnswerStub(AnswerStub):
    def __init__(self, database: Database, resource_id: UUID, actor_id: UUID) -> None:
        super().__init__()
        self.database = database
        self.resource_id = resource_id
        self.actor_id = actor_id

    def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
        with self.database.session_factory.begin() as session:
            resource = session.get(KnowledgeResource, self.resource_id)
            assert resource is not None
            resource.deleted_at = datetime.now(UTC)
            resource.deleted_by = self.actor_id
        return super().generate(question=question, evidence=evidence)


@pytest.mark.integration
def test_answer_discards_generation_when_evidence_is_deleted_during_provider_io(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, _ = seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="易变资料.pdf",
        chunks=[(UUID("00000000-0000-4000-8000-000000000072"), "交付日期", [1.0] + [0.0] * 1023)],
    )
    provider = DeleteEvidenceAnswerStub(database, resource_id, actor.user_id)
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/answers",
            json={"question": "什么时候交付?"},
            headers={"X-Request-ID": "req-answer-race"},
        )

    assert response.status_code == 409
    assert response.json() == {
        "message": "项目知识已发生变化，请重新提问",
        "code": "knowledge_changed",
        "traceId": "req-answer-race",
    }
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.integration
def test_answer_http_boundary_conceals_access_and_enforces_validation_session_and_csrf(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    other = seed_actor(database, MembershipRole.MEMBER)
    denied_project = seed_project(database, actor, permission=None)
    cross_tenant_project = seed_project(database, other, permission="read")
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        AnswerStub(),
    ) as client:
        invalid = client.post(
            f"/api/v1/projects/{denied_project}/knowledge/answers",
            json={"question": "xy", "extra": True},
            headers={"X-Request-ID": "req-answer-invalid"},
        )
        csrf = client.post(
            f"/api/v1/projects/{denied_project}/knowledge/answers",
            json={"question": "访问边界"},
            headers={"X-CSRF-Token": "wrong"},
        )
        denied = client.post(
            f"/api/v1/projects/{denied_project}/knowledge/answers",
            json={"question": "访问边界"},
        )
        cross_tenant = client.post(
            f"/api/v1/projects/{cross_tenant_project}/knowledge/answers",
            json={"question": "访问边界"},
        )
        with database.session_factory.begin() as session:
            session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
        unauthenticated = client.post(
            f"/api/v1/projects/{denied_project}/knowledge/answers",
            json={"question": "访问边界"},
        )

    assert (invalid.status_code, invalid.json()["code"]) == (422, "validation_error")
    assert invalid.json()["traceId"] == "req-answer-invalid"
    assert invalid.headers["cache-control"] == "private, no-store"
    assert (csrf.status_code, csrf.json()["code"]) == (403, "csrf_failed")
    assert (denied.status_code, denied.json()["code"]) == (404, "not_found")
    assert (cross_tenant.status_code, cross_tenant.json()["code"]) == (404, "not_found")
    assert (unauthenticated.status_code, unauthenticated.json()["code"]) == (401, "session_invalid")


@pytest.mark.integration
def test_answer_route_shares_search_rate_limit_and_retry_after(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="限流资料.pdf",
        chunks=[(UUID("00000000-0000-4000-8000-000000000073"), "交付日期", [1.0] + [0.0] * 1023)],
    )
    settings = knowledge_settings(test_database_url, search_user_limit_per_minute=1)
    with knowledge_client(
        settings, database, actor, MemoryObjectStore(), SearchEmbedding(), AnswerStub()
    ) as client:
        first = client.post(
            f"/api/v1/projects/{project_id}/knowledge/answers",
            json={"question": "什么时候交付?"},
        )
        limited = client.post(
            f"/api/v1/projects/{project_id}/knowledge/answers",
            json={"question": "什么时候交付?"},
            headers={"X-Request-ID": "req-answer-limited"},
        )

    assert first.status_code == 200
    assert (limited.status_code, limited.json()["code"]) == (429, "search_rate_limited")
    assert int(limited.headers["retry-after"]) >= 1
    assert limited.json()["traceId"] == "req-answer-limited"
    assert limited.headers["cache-control"] == "private, no-store"


PROVIDER_FAILURES: list[tuple[Exception, int, str, str]] = [
    (
        AnswerProviderUnavailable("provider-secret"),
        503,
        "answer_unavailable",
        "生成式回答暂时不可用",
    ),
    (
        AnswerProviderInvalidResponse("invalid-secret"),
        503,
        "answer_unavailable",
        "生成式回答暂时不可用",
    ),
    (RuntimeError("unexpected-secret"), 500, "internal_error", "服务器内部错误"),
]


@pytest.mark.integration
@pytest.mark.parametrize(("error", "status", "code", "message"), PROVIDER_FAILURES)
def test_answer_route_sanitizes_provider_and_unexpected_failures(
    database: Database,
    test_database_url: str,
    error: Exception,
    status: int,
    code: str,
    message: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="错误资料.pdf",
        chunks=[(UUID("00000000-0000-4000-8000-000000000074"), "交付日期", [1.0] + [0.0] * 1023)],
    )
    request_id = f"req-answer-{status}-{type(error).__name__}"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        RaisingAnswerStub(error),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/answers",
            json={"question": "什么时候交付?"},
            headers={"X-Request-ID": request_id},
        )

    assert response.status_code == status
    assert response.json() == {"message": message, "code": code, "traceId": request_id}
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["access-control-allow-origin"]
    assert "secret" not in response.text


@pytest.mark.integration
def test_answer_route_maps_database_failure_to_traced_safe_503(
    database: Database,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    monkeypatch.setattr(
        "cairn_api.knowledge.search_service.KnowledgeSearchService.search",
        Mock(side_effect=OperationalError("database-secret", {}, Exception("driver-secret"))),
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        AnswerStub(),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/answers",
            json={"question": "什么时候交付?"},
            headers={"X-Request-ID": "req-answer-db"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "message": "数据库暂时不可用",
        "code": "database_unavailable",
        "traceId": "req-answer-db",
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert "secret" not in response.text
