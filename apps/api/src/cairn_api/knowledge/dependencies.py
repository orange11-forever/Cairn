from typing import Annotated, cast

from fastapi import Depends, Request

from cairn_api.knowledge.answer_provider import AnswerProvider
from cairn_api.knowledge.object_store import ObjectStore
from cairn_api.knowledge.search_service import SearchEmbeddingClient


def get_object_store(request: Request) -> ObjectStore:
    object_store = getattr(request.app.state, "object_store", None)
    if not isinstance(object_store, ObjectStore):
        raise TypeError("object store is not configured")
    return object_store


def get_embedding_client(request: Request) -> SearchEmbeddingClient:
    configured = getattr(request.app.state, "embedding_client", None)
    if configured is None:
        raise TypeError("embedding client is not configured")
    return cast(SearchEmbeddingClient, configured)


EmbeddingClientDependency = Annotated[SearchEmbeddingClient, Depends(get_embedding_client)]


def get_answer_provider(request: Request) -> AnswerProvider | None:
    return cast(AnswerProvider | None, getattr(request.app.state, "answer_provider", None))


AnswerProviderDependency = Annotated[AnswerProvider | None, Depends(get_answer_provider)]


__all__ = [
    "AnswerProviderDependency",
    "EmbeddingClientDependency",
    "get_answer_provider",
    "get_embedding_client",
    "get_object_store",
]
