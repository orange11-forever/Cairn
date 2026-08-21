import hashlib
import hmac
import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import search_repository
from cairn_api.knowledge.models import KnowledgeResource
from cairn_api.knowledge.schemas import (
    KnowledgeCitation,
    KnowledgeSearchResponse,
    normalize_search_query,
)
from cairn_api.knowledge.search_rate_limit import SearchRateLimiter
from cairn_api.knowledge.search_repository import RankedCandidate


class EmbeddingUnavailable(Exception):
    pass


class EmbeddingConfigurationError(Exception):
    pass


class QueryEmbeddingClient(Protocol):
    provider_key: str
    model: str
    dimensions: int

    def embed_query(self, query: str) -> list[float]: ...


class BatchEmbeddingClient(Protocol):
    provider_key: str
    model: str
    dimensions: int

    def embed(self, inputs: Sequence[str]) -> list[list[float]]: ...


SearchEmbeddingClient = QueryEmbeddingClient | BatchEmbeddingClient


class OpenAIQueryEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        provider_key: str,
        model: str,
        dimensions: int,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        if dimensions < 1 or timeout_seconds <= 0:
            raise ValueError("embedding client limits must be positive")
        self.provider_key = provider_key
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/embeddings"
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        self._owns_client = client is None

    def embed_query(self, query: str) -> list[float]:
        try:
            response = self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "input": [query],
                    "model": self.model,
                    "dimensions": self.dimensions,
                },
            )
            response.raise_for_status()
            payload = cast(object, response.json())
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {408, 429} or status_code >= 500:
                raise EmbeddingUnavailable() from None
            raise EmbeddingConfigurationError() from None
        except (httpx.HTTPError, UnicodeError, ValueError):
            raise EmbeddingUnavailable() from None
        if not isinstance(payload, dict):
            raise EmbeddingUnavailable()
        body = cast(dict[str, object], payload)
        data_value = body.get("data")
        if not isinstance(data_value, list):
            raise EmbeddingUnavailable()
        data = cast(list[object], data_value)
        if len(data) != 1 or not isinstance(data[0], dict):
            raise EmbeddingUnavailable()
        record = cast(dict[str, object], data[0])
        index = record.get("index")
        if isinstance(index, bool) or index != 0:
            raise EmbeddingUnavailable()
        vector_value = record.get("embedding")
        if not isinstance(vector_value, list):
            raise EmbeddingConfigurationError()
        vector = cast(list[object], vector_value)
        if len(vector) != self.dimensions:
            raise EmbeddingConfigurationError()
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            for value in vector
        ):
            raise EmbeddingUnavailable()
        return [float(cast(int | float, value)) for value in vector]

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


ReserveCapacity = Callable[..., None]


def reciprocal_rank_fusion(
    lexical: Sequence[RankedCandidate],
    vector: Sequence[RankedCandidate],
    *,
    limit: int,
    k: int = 60,
) -> list[tuple[UUID, float]]:
    if limit < 0 or k < 0:
        raise ValueError("RRF limit and k must be nonnegative")
    scores: dict[UUID, float] = {}
    best_ranks: dict[UUID, int] = {}
    for candidates in (lexical, vector):
        seen: set[UUID] = set()
        for candidate in candidates:
            if candidate.chunk_id in seen:
                continue
            seen.add(candidate.chunk_id)
            if candidate.rank < 1:
                raise ValueError("RRF ranks must be one-based")
            scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + (
                1 / (k + candidate.rank)
            )
            best_ranks[candidate.chunk_id] = min(
                best_ranks.get(candidate.chunk_id, candidate.rank), candidate.rank
            )
    ordered = sorted(
        scores,
        key=lambda chunk_id: (-scores[chunk_id], best_ranks[chunk_id], str(chunk_id)),
    )
    return [(chunk_id, scores[chunk_id]) for chunk_id in ordered[:limit]]


def _embedding_problem() -> ApiProblem:
    return ApiProblem(
        status_code=503,
        code="embedding_unavailable",
        message="Embedding 服务暂时不可用",
    )


class KnowledgeSearchService:
    def __init__(
        self,
        session: Session,
        embedding_client: SearchEmbeddingClient,
        *,
        policy: AuthorizationPolicy | None = None,
        now: Callable[[], datetime] | None = None,
        user_limit: int = 30,
        org_limit: int = 300,
        audit_secret: str | bytes,
        reserve_capacity: ReserveCapacity | None = None,
        expected_dimensions: int | None = None,
    ) -> None:
        if user_limit < 1 or org_limit < 1:
            raise ValueError("search rate limits must be positive")
        self._session = session
        self._embedding_client = embedding_client
        self._policy = policy or AuthorizationPolicy(session)
        self._now = now or (lambda: datetime.now(UTC))
        self._user_limit = user_limit
        self._org_limit = org_limit
        self._audit_secret = audit_secret.encode() if isinstance(audit_secret, str) else audit_secret
        self._reserve_capacity = reserve_capacity
        self._expected_dimensions = expected_dimensions

    def _reserve(self, *, org_id: UUID, user_id: UUID, now: datetime) -> None:
        if self._reserve_capacity is not None:
            self._reserve_capacity(org_id=org_id, user_id=user_id, now=now)
            return
        SearchRateLimiter(
            self._session,
            user_limit=self._user_limit,
            org_limit=self._org_limit,
        ).reserve(org_id=org_id, user_id=user_id, now=now)

    def _embed_query(self, query: str) -> list[float] | None:
        try:
            embed_query = getattr(self._embedding_client, "embed_query", None)
            if callable(embed_query):
                vector = cast(list[float], embed_query(query))
            else:
                embed = getattr(self._embedding_client, "embed", None)
                if not callable(embed):
                    raise EmbeddingConfigurationError()
                vectors = cast(list[list[float]], embed([query]))
                if len(vectors) != 1:
                    raise EmbeddingConfigurationError()
                vector = vectors[0]
        except EmbeddingUnavailable:
            return None
        except EmbeddingConfigurationError:
            raise _embedding_problem() from None
        except Exception as exc:
            error_code = getattr(exc, "code", None)
            if error_code == "embedding_unavailable" and getattr(exc, "retryable", False):
                return None
            if error_code in {"embedding_unavailable", "embedding_dimension_mismatch"}:
                raise _embedding_problem() from None
            raise
        if self._expected_dimensions is not None and len(vector) != self._expected_dimensions:
            raise _embedding_problem()
        return vector

    def _validate_profile(self, profile: object | None) -> None:
        if profile is None:
            raise _embedding_problem()
        provider_key = getattr(self._embedding_client, "provider_key", None)
        compatible_provider = getattr(profile, "provider_key", None) in {
            "default",
            provider_key,
        }
        if (
            not compatible_provider
            or getattr(profile, "model", None) != getattr(self._embedding_client, "model", None)
            or getattr(profile, "dimensions", None)
            != getattr(self._embedding_client, "dimensions", None)
            or getattr(profile, "distance_metric", None) != "cosine"
        ):
            raise _embedding_problem()
        index_config = getattr(profile, "index_config", None)
        if index_config is not None:
            if not isinstance(index_config, dict):
                raise _embedding_problem()
            typed_index_config = cast(dict[str, object], index_config)
            if (
                typed_index_config.get("strategy") != "exact"
                or typed_index_config.get("candidateLimit")
                != search_repository.SEARCH_CANDIDATE_LIMIT
            ):
                raise _embedding_problem()

    def search(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        query: str,
        limit: int,
        audit: RequestAuditContext,
    ) -> KnowledgeSearchResponse:
        if not 1 <= limit <= 20:
            raise ApiProblem(status_code=422, code="validation_error", message="请求参数无效")
        query = normalize_search_query(query)
        if not 3 <= len(query) <= 500:
            raise ApiProblem(status_code=422, code="validation_error", message="请求参数无效")
        now = self._now()
        with self._session.begin():
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.READ,
                for_update=True,
            )
            self._reserve(
                org_id=identity.organization.id,
                user_id=identity.user.id,
                now=now,
            )
            profile = search_repository.get_active_embedding_profile(
                self._session,
                org_id=identity.organization.id,
            )
            self._validate_profile(profile)

        query_vector = self._embed_query(query)
        retrieval_mode = "hybrid" if query_vector is not None else "keyword_fallback"
        with self._session.begin():
            access_filter = self._policy.project_filter(
                identity,
                ProjectPermission.READ,
                cast(ColumnElement[UUID], KnowledgeResource.project_id),
            )
            lexical = search_repository.lexical_candidates(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                query=query,
                access_filter=access_filter,
            )
            vector = (
                search_repository.vector_candidates(
                    self._session,
                    org_id=identity.organization.id,
                    project_id=project_id,
                    query_vector=query_vector,
                    access_filter=access_filter,
                )
                if query_vector is not None
                else []
            )
            ranked = reciprocal_rank_fusion(lexical, vector, limit=limit)
            records = search_repository.load_citations(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                chunk_ids=[chunk_id for chunk_id, _score in ranked],
                access_filter=access_filter,
            )
            scores = dict(ranked)
            results = [
                KnowledgeCitation.model_validate(
                    {
                        "resource_id": record.resource_id,
                        "resource_version_id": record.resource_version_id,
                        "chunk_id": record.chunk_id,
                        "title": record.title,
                        "media_type": record.media_type,
                        "excerpt": record.excerpt,
                        "locator": record.locator,
                        "score": scores[record.chunk_id],
                    }
                )
                for record in records
            ]
            add_audit_log(
                self._session,
                org_id=identity.organization.id,
                actor_type="user",
                actor_id=identity.user.id,
                action="knowledge.searched",
                resource_type="project",
                resource_id=project_id,
                trace_id=audit.trace_id,
                ip=audit.ip,
                user_agent=audit.user_agent,
                details={
                    "queryLength": len(query),
                    "queryDigest": hmac.new(
                        self._audit_secret,
                        query.encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest(),
                    "retrievalMode": retrieval_mode,
                    "resultCount": len(results),
                },
            )
        return KnowledgeSearchResponse(retrieval_mode=retrieval_mode, results=results)


__all__ = [
    "BatchEmbeddingClient",
    "EmbeddingConfigurationError",
    "EmbeddingUnavailable",
    "KnowledgeSearchService",
    "OpenAIQueryEmbeddingClient",
    "QueryEmbeddingClient",
    "RankedCandidate",
    "SearchEmbeddingClient",
    "reciprocal_rank_fusion",
]
