from importlib import import_module

from sqlalchemy import MetaData

from cairn_api.db.base import Base

MODEL_MODULES = (
    "cairn_api.audit.models",
    "cairn_api.auth.models",
    "cairn_api.authorization.models",
    "cairn_api.knowledge.models",
    "cairn_api.knowledge.source_models",
    "cairn_api.organizations.models",
    "cairn_api.projects.models",
)


def load_model_metadata() -> MetaData:
    """Register every API ORM table for standalone processes that flush shared models."""
    for module in MODEL_MODULES:
        import_module(module)
    return Base.metadata


__all__ = ["load_model_metadata"]
