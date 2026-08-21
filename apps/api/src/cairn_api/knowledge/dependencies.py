from typing import Annotated, cast

from fastapi import Depends, Request

from cairn_api.knowledge.object_store import ObjectStore
from cairn_api.knowledge.search_service import (
    OpenAIQueryEmbeddingClient,
    SearchEmbeddingClient,
)
from cairn_api.settings import Settings


def get_object_store(request: Request) -> ObjectStore:
    object_store = getattr(request.app.state, "object_store", None)
    if not isinstance(object_store, ObjectStore):
        raise TypeError("object store is not configured")
    return object_store


def get_embedding_client(request: Request) -> SearchEmbeddingClient:
    configured = getattr(request.app.state, "embedding_client", None)
    if configured is None:
        settings = cast(Settings, request.app.state.settings)
        configured = OpenAIQueryEmbeddingClient(
            base_url=str(settings.embedding_base_url),
            api_key=settings.embedding_api_key.get_secret_value(),
            provider_key=settings.embedding_provider_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
        request.app.state.embedding_client = configured
    return cast(SearchEmbeddingClient, configured)


EmbeddingClientDependency = Annotated[SearchEmbeddingClient, Depends(get_embedding_client)]


__all__ = ["EmbeddingClientDependency", "get_embedding_client", "get_object_store"]
