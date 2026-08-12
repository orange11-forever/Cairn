from fastapi import Request

from cairn_api.knowledge.object_store import ObjectStore


def get_object_store(request: Request) -> ObjectStore:
    object_store = getattr(request.app.state, "object_store", None)
    if not isinstance(object_store, ObjectStore):
        raise TypeError("object store is not configured")
    return object_store


__all__ = ["get_object_store"]
