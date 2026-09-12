import hashlib
import hmac
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.errors import DATABASE_UNAVAILABLE_ERRORS
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import search_repository
from cairn_api.knowledge.answer_provider import (
    AnswerEvidence,
    AnswerProvider,
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
)
from cairn_api.knowledge.answer_schemas import (
    KnowledgeAnswerCitation,
    KnowledgeAnswerParagraph,
    KnowledgeAnswerResponse,
)
from cairn_api.knowledge.models import KnowledgeResource
from cairn_api.knowledge.schemas import KnowledgeCitation, normalize_search_query
from cairn_api.knowledge.search_service import KnowledgeSearchService


def _knowledge_changed() -> ApiProblem:
    return ApiProblem(
        status_code=409,
        code="knowledge_changed",
        message="项目知识已发生变化，请重新提问",
    )


class KnowledgeAnswerService:
    def __init__(
        self,
        session: Session,
        search_service: KnowledgeSearchService,
        provider: AnswerProvider | None,
        *,
        policy: AuthorizationPolicy | None = None,
        audit_secret: str | bytes,
    ) -> None:
        self._session = session
        self._search_service = search_service
        self._provider = provider
        self._policy = policy or AuthorizationPolicy(session)
        self._audit_secret = (
            audit_secret.encode() if isinstance(audit_secret, str) else audit_secret
        )

    def answer(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        question: str,
        audit: RequestAuditContext,
    ) -> KnowledgeAnswerResponse:
        try:
            return self._answer(
                identity=identity, project_id=project_id, question=question, audit=audit
            )
        except ApiProblem:
            raise
        except DATABASE_UNAVAILABLE_ERRORS:
            raise
        except (AnswerProviderUnavailable, AnswerProviderInvalidResponse):
            raise ApiProblem(
                status_code=503,
                code="answer_unavailable",
                message="生成式回答暂时不可用",
            ) from None
        # This trust boundary must discard provider/driver exception text and parameters.
        except Exception:  # noqa: BLE001
            raise ApiProblem(
                status_code=500, code="internal_error", message="服务器内部错误"
            ) from None

    def _answer(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        question: str,
        audit: RequestAuditContext,
    ) -> KnowledgeAnswerResponse:
        question = normalize_search_query(question)
        if not 3 <= len(question) <= 500:
            raise ApiProblem(status_code=422, code="validation_error", message="请求参数无效")
        search = self._search_service.search(
            identity=identity,
            project_id=project_id,
            query=question,
            limit=6,
            audit=audit,
        )
        if self._provider is None:
            raise AnswerProviderUnavailable()
        citations = search.results[:6]
        if not citations:
            response = KnowledgeAnswerResponse(
                status="insufficient_evidence",
                retrievalMode=search.retrieval_mode,
                paragraphs=[],
                citations=[],
            )
            self._audit(identity, project_id, question, response, audit)
            return response

        self._revalidate(identity, project_id, citations)
        evidence = [
            AnswerEvidence(
                id=f"S{index}",
                chunk_id=citation.chunk_id,
                title=citation.title,
                locator=citation.locator.model_dump(by_alias=True),
                text=citation.excerpt[:1800],
            )
            for index, citation in enumerate(citations, 1)
        ]
        generated = self._provider.generate(question=question, evidence=evidence)
        self._revalidate(identity, project_id, citations)

        if generated.status == "insufficient_evidence":
            response = KnowledgeAnswerResponse(
                status="insufficient_evidence",
                retrievalMode=search.retrieval_mode,
                paragraphs=[],
                citations=[],
            )
        else:
            used_ids = {
                citation_id
                for paragraph in generated.paragraphs
                for citation_id in paragraph.citation_ids
            }
            answer_citations = [
                KnowledgeAnswerCitation.model_validate(
                    {
                        "id": evidence_item.id,
                        "resource_id": citation.resource_id,
                        "resource_version_id": citation.resource_version_id,
                        "chunk_id": citation.chunk_id,
                        "title": citation.title,
                        "media_type": citation.media_type,
                        "excerpt": citation.excerpt,
                        "locator": citation.locator.model_dump(by_alias=True),
                        "score": citation.score,
                    }
                )
                for evidence_item, citation in zip(evidence, citations, strict=True)
                if evidence_item.id in used_ids
            ]
            response = KnowledgeAnswerResponse(
                status="answered",
                retrievalMode=search.retrieval_mode,
                paragraphs=[
                    KnowledgeAnswerParagraph(
                        text=paragraph.text.strip(), citationIds=paragraph.citation_ids
                    )
                    for paragraph in generated.paragraphs
                ],
                citations=answer_citations,
            )
        self._audit(identity, project_id, question, response, audit)
        return response

    def _revalidate(
        self,
        identity: IdentityContextResponse,
        project_id: UUID,
        citations: list[KnowledgeCitation],
    ) -> None:
        expected = [
            (citation.resource_id, citation.resource_version_id, citation.chunk_id)
            for citation in citations
        ]
        with self._session.begin():
            try:
                self._policy.require_project(
                    identity, project_id, ProjectPermission.READ, for_update=True
                )
            except ApiProblem as exc:
                if exc.status_code == 404:
                    raise _knowledge_changed() from None
                raise
            access_filter = self._policy.project_filter(
                identity,
                ProjectPermission.READ,
                cast(ColumnElement[UUID], KnowledgeResource.project_id),
            )
            records = search_repository.load_citations(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                chunk_ids=[citation.chunk_id for citation in citations],
                access_filter=access_filter,
            )
            current = [
                (record.resource_id, record.resource_version_id, record.chunk_id)
                for record in records
            ]
            if current != expected:
                raise _knowledge_changed()

    def _audit(
        self,
        identity: IdentityContextResponse,
        project_id: UUID,
        question: str,
        response: KnowledgeAnswerResponse,
        audit: RequestAuditContext,
    ) -> None:
        with self._session.begin():
            add_audit_log(
                self._session,
                org_id=identity.organization.id,
                actor_type="user",
                actor_id=identity.user.id,
                action="knowledge.answered",
                resource_type="project",
                resource_id=project_id,
                trace_id=audit.trace_id,
                ip=audit.ip,
                user_agent=audit.user_agent,
                details={
                    "questionLength": len(question),
                    "questionDigest": hmac.new(
                        self._audit_secret, question.encode("utf-8"), hashlib.sha256
                    ).hexdigest(),
                    "retrievalMode": response.retrieval_mode,
                    "status": response.status,
                    "paragraphCount": len(response.paragraphs),
                    "sourceCount": len(response.citations),
                },
            )


__all__ = ["KnowledgeAnswerService"]
