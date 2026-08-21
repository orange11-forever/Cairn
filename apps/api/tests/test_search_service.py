import hashlib
import hmac
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import httpx
import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.schemas import KnowledgeSearchRequest
from cairn_api.knowledge.search_repository import (
    SearchCitationRecord,
    lexical_statement,
    vector_statement,
)
from cairn_api.knowledge.search_service import (
    EmbeddingConfigurationError,
    EmbeddingUnavailable,
    KnowledgeSearchService,
    OpenAIQueryEmbeddingClient,
    RankedCandidate,
)
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from pydantic import ValidationError
from sqlalchemy import column
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 21, 7, 12, 34, tzinfo=UTC)
AUDIT = RequestAuditContext("req-search", "198.51.100.9", "search-test")


def _identity() -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(id=uuid4(), email="reader@example.com", display_name="Reader"),
        organization=OrganizationResponse(id=uuid4(), slug="readers", name="Readers"),
        membership=MembershipResponse(id=uuid4(), role=MembershipRole.MEMBER),
        csrf_token="csrf",
    )


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        ("  knowledge base  ", "knowledge base"),
        ("ＡＩ知识库", "AI知识库"),
        ("  中文检索  ", "中文检索"),
    ],
)
def test_search_request_normalizes_before_unicode_codepoint_validation(
    value: str, normalized: str
) -> None:
    """Break caught: whitespace or full-width forms bypass the canonical query boundary."""
    assert KnowledgeSearchRequest(query=value).query == normalized


@pytest.mark.parametrize("value", ["ab", "x" * 501, "  ＡＢ  "])
def test_search_request_rejects_normalized_queries_outside_three_to_five_hundred_codepoints(
    value: str,
) -> None:
    """Break caught: length is measured before trim/NFKC normalization or in bytes."""
    with pytest.raises(ValidationError):
        KnowledgeSearchRequest(query=value)


def test_search_request_defaults_to_ten_and_accepts_the_twenty_result_maximum() -> None:
    """Break caught: the public result bound drifts above 20 or away from the default 10."""
    assert KnowledgeSearchRequest(query="valid query").limit == 10
    assert KnowledgeSearchRequest(query="valid query", limit=20).limit == 20
    with pytest.raises(ValidationError):
        KnowledgeSearchRequest(query="valid query", limit=21)


class _Embedding:
    provider_key = "default"
    model = "text-embedding-v4"
    dimensions = 3

    def __init__(self, result: list[float] | Exception) -> None:
        self.result = result
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _citation(chunk_id: UUID) -> SearchCitationRecord:
    return SearchCitationRecord(
        resource_id=uuid4(),
        resource_version_id=uuid4(),
        chunk_id=chunk_id,
        title="年度报告.pdf",
        media_type="application/pdf",
        excerpt="revenue increased",
        locator={"type": "pdf", "page": 2},
    )


def _service(
    monkeypatch: pytest.MonkeyPatch,
    embedding: _Embedding,
    *,
    lexical: list[RankedCandidate] | None = None,
    vector: list[RankedCandidate] | None = None,
) -> tuple[KnowledgeSearchService, MagicMock, IdentityContextResponse, UUID]:
    from cairn_api.knowledge import search_repository

    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    identity = _identity()
    project_id = uuid4()
    policy.project_filter.return_value = Mock()
    monkeypatch.setattr(
        search_repository,
        "get_active_embedding_profile",
        Mock(
            return_value=SimpleNamespace(
                provider_key="default",
                model="text-embedding-v4",
                dimensions=3,
                distance_metric="cosine",
            )
        ),
    )
    monkeypatch.setattr(
        search_repository,
        "lexical_candidates",
        Mock(return_value=lexical or []),
    )
    monkeypatch.setattr(
        search_repository,
        "vector_candidates",
        Mock(return_value=vector or []),
    )
    def citations_for_request(*_args: object, **kwargs: object) -> list[SearchCitationRecord]:
        chunk_ids = cast(list[UUID], kwargs["chunk_ids"])
        return [_citation(chunk_id) for chunk_id in chunk_ids]

    monkeypatch.setattr(
        search_repository,
        "load_citations",
        Mock(side_effect=citations_for_request),
    )
    service = KnowledgeSearchService(
        session,
        embedding,
        policy=policy,
        now=lambda: NOW,
        user_limit=30,
        org_limit=300,
        audit_secret=b"s" * 32,
        reserve_capacity=Mock(),
    )
    return service, session, identity, project_id


def test_search_uses_query_embedding_fuses_results_and_audits_only_safe_query_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: search skips vector retrieval or stores raw query/audit extras."""
    lexical_id = uuid4()
    shared_id = uuid4()
    embedding = _Embedding([0.1, 0.2, 0.3])
    service, session, identity, project_id = _service(
        monkeypatch,
        embedding,
        lexical=[RankedCandidate(lexical_id, 1), RankedCandidate(shared_id, 2)],
        vector=[RankedCandidate(shared_id, 1)],
    )

    response = service.search(
        identity=identity,
        project_id=project_id,
        query="AI knowledge",
        limit=10,
        audit=AUDIT,
    )

    assert response.retrieval_mode == "hybrid"
    assert [item.chunk_id for item in response.results] == [shared_id, lexical_id]
    assert embedding.queries == ["AI knowledge"]
    audit_rows = [
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], AuditLog)
    ]
    assert len(audit_rows) == 1
    assert audit_rows[0].details == {
        "queryLength": 12,
        "queryDigest": hmac.new(b"s" * 32, b"AI knowledge", hashlib.sha256).hexdigest(),
        "retrievalMode": "hybrid",
        "resultCount": 2,
    }
    assert "AI knowledge" not in str(audit_rows[0].details)


def test_service_normalizes_query_before_provider_and_audit_when_called_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a non-HTTP caller bypasses canonicalization and fragments search/audit keys."""
    embedding = _Embedding([0.1, 0.2, 0.3])
    service, session, identity, project_id = _service(monkeypatch, embedding)

    service.search(
        identity=identity,
        project_id=project_id,
        query="  ＡＩ knowledge  ",
        limit=10,
        audit=AUDIT,
    )

    assert embedding.queries == ["AI knowledge"]
    audit_rows = [
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], AuditLog)
    ]
    assert audit_rows[0].details["queryLength"] == 12


def test_transient_embedding_unavailability_returns_explicit_keyword_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a transient provider outage fails closed instead of explicit lexical fallback."""
    chunk_id = uuid4()
    service, _session, identity, project_id = _service(
        monkeypatch,
        _Embedding(EmbeddingUnavailable()),
        lexical=[RankedCandidate(chunk_id, 1)],
    )

    response = service.search(
        identity=identity,
        project_id=project_id,
        query="fallback query",
        limit=10,
        audit=AUDIT,
    )

    assert response.retrieval_mode == "keyword_fallback"
    assert [item.chunk_id for item in response.results] == [chunk_id]


def test_search_returns_an_empty_hybrid_result_list_without_fabricated_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: an empty authorized candidate set is treated as an error or placeholder hit."""
    service, _session, identity, project_id = _service(
        monkeypatch,
        _Embedding([0.1, 0.2, 0.3]),
    )

    response = service.search(
        identity=identity,
        project_id=project_id,
        query="nothing found",
        limit=10,
        audit=AUDIT,
    )

    assert response.retrieval_mode == "hybrid"
    assert response.results == []


def test_permanent_embedding_configuration_failure_returns_503_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: dimension/configuration errors are hidden as keyword fallback."""
    service, _session, identity, project_id = _service(
        monkeypatch,
        _Embedding(EmbeddingConfigurationError()),
    )

    with pytest.raises(ApiProblem) as raised:
        service.search(
            identity=identity,
            project_id=project_id,
            query="broken profile",
            limit=10,
            audit=AUDIT,
        )

    assert raised.value.status_code == 503
    assert raised.value.code == "embedding_unavailable"


def test_active_profile_dimension_mismatch_returns_503_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: incompatible active profile is degraded or sent to the provider."""
    from cairn_api.knowledge import search_repository

    embedding = _Embedding([0.1, 0.2, 0.3])
    service, _session, identity, project_id = _service(monkeypatch, embedding)
    monkeypatch.setattr(
        search_repository,
        "get_active_embedding_profile",
        Mock(
            return_value=SimpleNamespace(
                provider_key="default",
                model="text-embedding-v4",
                dimensions=1024,
                distance_metric="cosine",
                index_config={"strategy": "exact", "candidateLimit": 50},
            )
        ),
    )

    with pytest.raises(ApiProblem) as raised:
        service.search(
            identity=identity,
            project_id=project_id,
            query="profile mismatch",
            limit=10,
            audit=AUDIT,
        )

    assert raised.value.status_code == 503
    assert embedding.queries == []


def test_candidate_sql_filters_tenant_project_current_ready_deleted_and_acl_before_limit() -> None:
    """Break caught: either Top-k query retrieves unauthorized candidates then filters in Python."""
    org_id = UUID("00000000-0000-4000-8000-000000000101")
    project_id = UUID("00000000-0000-4000-8000-000000000102")
    access_filter = column("authorization_policy_project_filter") == 1
    statements = (
        lexical_statement(
            org_id=org_id,
            project_id=project_id,
            query="exact phrase",
            access_filter=access_filter,
        ),
        vector_statement(
            org_id=org_id,
            project_id=project_id,
            query_vector=[0.0, 1.0, 0.0],
            access_filter=access_filter,
        ),
    )

    for statement in statements:
        sql = str(statement.compile(dialect=postgresql.dialect())).lower()
        limit_position = sql.index(" limit ")
        for required in (
            "knowledge_chunks.org_id",
            "knowledge_chunks.project_id",
            "knowledge_resources.deleted_at is null",
            "knowledge_resources.current_version_id = knowledge_resource_versions.id",
            "knowledge_resource_versions.status",
            "authorization_policy_project_filter",
        ):
            assert required in sql[:limit_position]
        assert " limit " in sql
        assert "object_key" not in sql
    lexical_sql = str(statements[0].compile(dialect=postgresql.dialect())).lower()
    assert "websearch_to_tsquery" in lexical_sql
    assert "similarity" in lexical_sql
    assert "like" in lexical_sql
    vector_sql = str(statements[1].compile(dialect=postgresql.dialect())).lower()
    assert "<=>" in vector_sql
    assert "embedding_profiles.status" in vector_sql


def test_query_embedding_rejects_nonfinite_provider_vectors() -> None:
    """Break caught: NaN or infinity crosses the provider boundary and reaches pgvector."""
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=b'{"data":[{"index":0,"embedding":[NaN,0.0,1.0]}]}',
            headers={"Content-Type": "application/json"},
        )
    )
    client = OpenAIQueryEmbeddingClient(
        base_url="https://embedding.example/v1",
        api_key="secret",
        provider_key="test",
        model="test-model",
        dimensions=3,
        timeout_seconds=1,
        client=httpx.Client(transport=transport),
    )

    with pytest.raises(EmbeddingUnavailable):
        client.embed_query("finite vectors only")


def test_query_embedding_treats_provider_authentication_failure_as_permanent_config() -> None:
    """Break caught: provider credentials/configuration faults silently select keyword fallback."""
    transport = httpx.MockTransport(lambda _request: httpx.Response(401, json={"error": "bad key"}))
    client = OpenAIQueryEmbeddingClient(
        base_url="https://embedding.example/v1",
        api_key="wrong-secret",
        provider_key="test",
        model="test-model",
        dimensions=3,
        timeout_seconds=1,
        client=httpx.Client(transport=transport),
    )

    with pytest.raises(EmbeddingConfigurationError):
        client.embed_query("do not degrade configuration errors")


def test_query_embedding_rejects_boolean_record_index() -> None:
    """Break caught: JSON false compares equal to integer zero and accepts a malformed record."""
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"data": [{"index": False, "embedding": [0.0, 0.0, 1.0]}]},
        )
    )
    client = OpenAIQueryEmbeddingClient(
        base_url="https://embedding.example/v1",
        api_key="secret",
        provider_key="test",
        model="test-model",
        dimensions=3,
        timeout_seconds=1,
        client=httpx.Client(transport=transport),
    )

    with pytest.raises(EmbeddingUnavailable):
        client.embed_query("strict record indices")
