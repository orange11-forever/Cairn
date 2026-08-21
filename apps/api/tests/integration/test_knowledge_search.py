import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.models import (
    ChunkEmbedding,
    EmbeddingProfile,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
)
from cairn_api.knowledge.search_service import (
    EmbeddingConfigurationError,
    EmbeddingUnavailable,
)
from sqlalchemy import select

from .authorization_helpers import seed_actor
from .knowledge_helpers import (
    MemoryObjectStore,
    knowledge_client,
    knowledge_settings,
    seed_project,
)

NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


class SearchEmbedding:
    provider_key = "local-fake"
    model = "text-embedding-v4"
    dimensions = 1024

    def __init__(self, vector: list[float] | Exception | None = None) -> None:
        self.vector = vector or [1.0] + [0.0] * 1023

    def embed_query(self, query: str) -> list[float]:
        del query
        if isinstance(self.vector, Exception):
            raise self.vector
        return self.vector


def seed_search_resource(
    database: Database,
    *,
    org_id: UUID,
    project_id: UUID,
    title: str,
    chunks: list[tuple[UUID, str, list[float]]],
    current: bool = True,
    ready: bool = True,
    deleted: bool = False,
    deleted_by: UUID | None = None,
) -> tuple[UUID, UUID]:
    resource_id = uuid4()
    version_id = uuid4()
    with database.session_factory.begin() as session:
        profile = session.scalar(
            select(EmbeddingProfile).where(
                EmbeddingProfile.org_id.is_(None), EmbeddingProfile.status == "active"
            )
        )
        assert profile is not None
        resource = KnowledgeResource(
            id=resource_id,
            org_id=org_id,
            project_id=project_id,
            title=title,
            source_type="upload",
            source_id=str(uuid4()),
            external_id=title,
            created_by=None,
            created_at=NOW,
            updated_at=NOW,
            deleted_at=NOW if deleted else None,
            deleted_by=deleted_by if deleted else None,
        )
        if deleted and deleted_by is None:
            raise ValueError("deleted search fixtures require an actor")
        session.add(resource)
        session.flush()
        version = KnowledgeResourceVersion(
            id=version_id,
            org_id=org_id,
            project_id=project_id,
            resource_id=resource_id,
            source_type="upload",
            source_id=resource.source_id,
            external_id=title,
            source_version=uuid4().hex,
            object_key=f"orgs/{org_id}/projects/{project_id}/{version_id}",
            media_type="application/pdf",
            size_bytes=100,
            sha256="a" * 64,
            parser_profile="default-v1",
            chunking_profile="default-v1",
            status=ResourceVersionStatus.READY if ready else ResourceVersionStatus.PROCESSING,
            created_at=NOW,
            processing_started_at=NOW,
            ready_at=NOW if ready else None,
        )
        session.add(version)
        session.flush()
        if current:
            resource.current_version_id = version_id
        for ordinal, (chunk_id, text, vector) in enumerate(chunks):
            chunk = KnowledgeChunk(
                id=chunk_id,
                org_id=org_id,
                project_id=project_id,
                resource_id=resource_id,
                resource_version_id=version_id,
                ordinal=ordinal,
                kind="text",
                text=text,
                normalized_text=text,
                locator={"type": "pdf", "page": ordinal + 1},
            )
            session.add(chunk)
            session.flush()
            session.add(
                ChunkEmbedding(
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    resource_version_id=version_id,
                    chunk_id=chunk_id,
                    embedding_profile_scope_org_id=profile.scope_org_id,
                    embedding_profile_id=profile.id,
                    embedding=vector,
                )
            )
        session.flush()
    return resource_id, version_id


@pytest.mark.integration
def test_search_returns_multilingual_hybrid_citations_and_safe_audit(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    shared_id = UUID("00000000-0000-4000-8000-000000000011")
    semantic_id = UUID("00000000-0000-4000-8000-000000000012")
    chinese_id = UUID("00000000-0000-4000-8000-000000000013")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="Annual Report.pdf",
        chunks=[
            (shared_id, "the exact phrase revenue increased", [0.99, 0.01] + [0.0] * 1022),
            (semantic_id, "financial performance improved", [1.0, 0.0] + [0.0] * 1022),
            (chinese_id, "企业人工智能知识库", [0.0, 1.0] + [0.0] * 1022),
        ],
    )
    settings = knowledge_settings(
        test_database_url,
        search_audit_secret="test-search-audit-secret-with-at-least-32-bytes",
    )
    with knowledge_client(settings, database, actor, MemoryObjectStore(), SearchEmbedding()) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "  revenue increased  ", "limit": 2},
            headers={"X-Request-ID": "req-hybrid-search"},
        )
        chinese = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "人工智能"},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-hybrid-search"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["retrievalMode"] == "hybrid"
    assert response.json()["results"][0]["chunkId"] == str(shared_id)
    assert len(response.json()["results"]) == 2
    assert response.json()["results"][0]["locator"] == {"type": "pdf", "page": 1}
    assert "objectKey" not in str(response.json())
    assert chinese.status_code == 200
    assert chinese.json()["results"][0]["chunkId"] == str(chinese_id)
    with database.session_factory() as session:
        audit = session.scalar(
            select(AuditLog)
            .where(AuditLog.trace_id == "req-hybrid-search")
            .order_by(AuditLog.created_at.desc())
        )
        assert audit is not None
        assert audit.details == {
            "queryLength": 17,
            "queryDigest": hmac.new(
                b"test-search-audit-secret-with-at-least-32-bytes",
                b"revenue increased",
                hashlib.sha256,
            ).hexdigest(),
            "retrievalMode": "hybrid",
            "resultCount": 2,
        }


@pytest.mark.integration
def test_keyword_fallback_covers_english_fts_chinese_trigram_and_exact_phrase(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    exact_id = UUID("00000000-0000-4000-8000-000000000031")
    fts_id = UUID("00000000-0000-4000-8000-000000000032")
    chinese_id = UUID("00000000-0000-4000-8000-000000000033")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="Lexical.pdf",
        chunks=[
            (exact_id, "revenue increased", [0.0] * 1024),
            (
                fts_id,
                "revenue " + "unrelated filler words " * 20 + "increased",
                [0.0] * 1024,
            ),
            (chinese_id, "企业人工智能知识库", [0.0] * 1024),
        ],
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(EmbeddingUnavailable()),
    ) as client:
        exact = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": '"revenue increased"', "limit": 20},
        )
        english_fts = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "revenue increased", "limit": 20},
        )
        chinese_trigram = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "企业智能知识库", "limit": 20},
        )

    assert exact.status_code == english_fts.status_code == chinese_trigram.status_code == 200
    assert exact.json()["retrievalMode"] == "keyword_fallback"
    assert exact.json()["results"][0]["chunkId"] == str(exact_id)
    assert str(fts_id) in [item["chunkId"] for item in english_fts.json()["results"]]
    assert str(chinese_id) in [item["chunkId"] for item in chinese_trigram.json()["results"]]


@pytest.mark.integration
def test_search_validation_csrf_and_openapi_contract(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        invalid = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "  ＡＢ  "},
            headers={"X-Request-ID": "req-search-invalid"},
        )
        no_csrf = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "valid query"},
            headers={"X-CSRF-Token": ""},
        )
        operation = client.get("/openapi.json").json()["paths"][
            "/api/v1/projects/{project_id}/knowledge/search"
        ]["post"]

    assert invalid.status_code == 422
    assert invalid.json() == {
        "message": "请求参数无效",
        "code": "validation_error",
        "traceId": "req-search-invalid",
    }
    assert invalid.headers["cache-control"] == "private, no-store"
    assert no_csrf.status_code == 403
    assert set(operation["responses"]) >= {"200", "401", "403", "404", "422", "429", "500", "503"}
    assert "Retry-After" in operation["responses"]["429"]["headers"]
    csrf = next(
        parameter for parameter in operation["parameters"] if parameter["name"] == "X-CSRF-Token"
    )
    assert csrf["required"] is True


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure", "status_code", "code", "retrieval_mode"),
    [
        (EmbeddingUnavailable(), 200, None, "keyword_fallback"),
        (EmbeddingConfigurationError(), 503, "embedding_unavailable", None),
        (RuntimeError("unexpected provider break"), 500, "internal_error", None),
    ],
)
def test_search_provider_failure_classification_preserves_safe_http_contract(
    database: Database,
    test_database_url: str,
    failure: Exception,
    status_code: int,
    code: str | None,
    retrieval_mode: str | None,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(failure),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "provider failure"},
            headers={"X-Request-ID": "req-provider-failure"},
        )

    assert response.status_code == status_code
    assert response.headers["x-request-id"] == "req-provider-failure"
    assert response.headers["cache-control"] == "private, no-store"
    if code is not None:
        assert response.json() == {
            "message": "Embedding 服务暂时不可用" if status_code == 503 else "服务器内部错误",
            "code": code,
            "traceId": "req-provider-failure",
        }
    else:
        assert response.json()["retrievalMode"] == retrieval_mode


__all__ = ["SearchEmbedding", "seed_search_resource"]
