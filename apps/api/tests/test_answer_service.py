from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.answer_provider import ProviderAnswer, ProviderParagraph
from cairn_api.knowledge.answer_service import KnowledgeAnswerService
from cairn_api.knowledge.schemas import KnowledgeCitation, KnowledgeSearchResponse
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from sqlalchemy.orm import Session

AUDIT = RequestAuditContext("req-answer", "198.51.100.9", "answer-test")


def _identity() -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(id=uuid4(), email="reader@example.com", display_name="Reader"),
        organization=OrganizationResponse(id=uuid4(), slug="readers", name="Readers"),
        membership=MembershipResponse(id=uuid4(), role=MembershipRole.MEMBER),
        csrf_token="csrf",
    )


def _citation() -> KnowledgeCitation:
    return KnowledgeCitation.model_validate(
        {
            "resource_id": uuid4(),
            "resource_version_id": uuid4(),
            "chunk_id": uuid4(),
            "title": "项目说明.txt",
            "media_type": "text/plain",
            "excerpt": "项目的交付日期是 9 月 30 日。",
            "locator": {"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 2},
            "score": 0.5,
        }
    )


def _service(search_results: list[KnowledgeCitation]) -> tuple[KnowledgeAnswerService, Mock, Mock]:
    session = MagicMock(spec=Session)
    search = Mock()
    search.search.return_value = KnowledgeSearchResponse(
        retrieval_mode="hybrid", results=search_results
    )
    provider = Mock()
    provider.generate.return_value = ProviderAnswer(
        status="answered",
        paragraphs=[ProviderParagraph(text="交付日期是 9 月 30 日。", citationIds=["S1"])],
    )
    policy = MagicMock(spec=AuthorizationPolicy)
    return (
        KnowledgeAnswerService(session, search, provider, policy=policy, audit_secret=b"a" * 32),
        provider,
        policy,
    )


def test_empty_retrieval_returns_insufficient_without_calling_provider() -> None:
    """Break caught: empty evidence is sent to the generation provider."""
    service, provider, _policy = _service([])

    response = service.answer(
        identity=_identity(), project_id=uuid4(), question="什么时候交付？", audit=AUDIT
    )

    assert response.status == "insufficient_evidence"
    assert response.paragraphs == []
    assert response.citations == []
    provider.generate.assert_not_called()


def test_answer_revalidates_all_evidence_before_and_after_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: deleted or unauthorized evidence remains trusted across provider I/O."""
    citation = _citation()
    service, provider, policy = _service([citation])
    records = Mock(
        return_value=[
            SimpleNamespace(
                resource_id=citation.resource_id,
                resource_version_id=citation.resource_version_id,
                chunk_id=citation.chunk_id,
            )
        ]
    )
    monkeypatch.setattr(
        "cairn_api.knowledge.answer_service.search_repository.load_citations", records
    )

    response = service.answer(
        identity=_identity(), project_id=uuid4(), question="什么时候交付？", audit=AUDIT
    )

    assert records.call_count == 2
    assert policy.require_project.call_count == 2
    provider.generate.assert_called_once()
    assert response.paragraphs[0].citation_ids == ["S1"]
    assert response.citations[0].id == "S1"


def test_changed_evidence_fails_closed_before_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Break caught: missing current evidence is sent to the provider."""
    citation = _citation()
    service, provider, _policy = _service([citation])
    monkeypatch.setattr(
        "cairn_api.knowledge.answer_service.search_repository.load_citations", Mock(return_value=[])
    )

    with pytest.raises(ApiProblem) as raised:
        service.answer(
            identity=_identity(), project_id=uuid4(), question="什么时候交付？", audit=AUDIT
        )
    assert (raised.value.status_code, raised.value.code) == (409, "knowledge_changed")
    provider.generate.assert_not_called()


def test_changed_evidence_discards_generated_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Break caught: an answer is returned after its source is deleted during generation."""
    citation = _citation()
    service, _provider, _policy = _service([citation])
    valid = SimpleNamespace(
        resource_id=citation.resource_id,
        resource_version_id=citation.resource_version_id,
        chunk_id=citation.chunk_id,
    )
    monkeypatch.setattr(
        "cairn_api.knowledge.answer_service.search_repository.load_citations",
        Mock(side_effect=[[valid], []]),
    )

    with pytest.raises(ApiProblem) as raised:
        service.answer(
            identity=_identity(), project_id=uuid4(), question="什么时候交付？", audit=AUDIT
        )
    assert (raised.value.status_code, raised.value.code) == (409, "knowledge_changed")


def test_permission_revoked_after_search_is_reported_as_knowledge_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: post-search revocation leaks project existence via a late 404."""
    citation = _citation()
    service, _provider, policy = _service([citation])
    policy.require_project.side_effect = ApiProblem(
        status_code=404, code="not_found", message="资源不存在"
    )
    monkeypatch.setattr(
        "cairn_api.knowledge.answer_service.search_repository.load_citations", Mock()
    )

    with pytest.raises(ApiProblem) as raised:
        service.answer(
            identity=_identity(), project_id=uuid4(), question="什么时候交付？", audit=AUDIT
        )
    assert (raised.value.status_code, raised.value.code) == (409, "knowledge_changed")
