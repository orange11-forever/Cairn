from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, exists, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.knowledge.models import (
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceSourceType,
)
from cairn_api.knowledge.source_models import KnowledgeSource


def is_canonical_feishu_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and len(value) <= 255
        and str(int(value)) == value
    )


def source_access_filter(
    *,
    org_id: UUID,
    project_id: UUID,
    resource: Any = KnowledgeResource,
    version: Any = KnowledgeResourceVersion,
) -> ColumnElement[bool]:
    """Authorize trusted resource/version provenance against current source state."""
    source = aliased(KnowledgeSource)
    matching_provenance = and_(
        resource.source_type == version.source_type,
        resource.source_id == version.source_id,
        resource.external_id == version.external_id,
    )
    local_source = and_(
        resource.source_type.in_([ResourceSourceType.UPLOAD, ResourceSourceType.ZIP_ENTRY]),
        or_(version.id.is_(None), matching_provenance),
    )
    configured_feishu_source = and_(
        resource.source_type == ResourceSourceType.FEISHU,
        version.id.is_not(None),
        matching_provenance,
        exists(
            select(1).where(
                source.org_id == org_id,
                source.project_id == project_id,
                source.provider == "feishu",
                source.status == "configured",
                source.access_state == "available",
                source.access_policy == "project_members",
                source.id.cast(String) == resource.source_id,
                source.external_id == resource.external_id,
            )
        ),
    )
    return or_(local_source, configured_feishu_source)


def validate_index_source(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    version_id: UUID,
    lock_source: bool,
) -> bool:
    """Read current database facts and optionally serialize with source disable."""
    row = session.execute(
        select(
            KnowledgeResource.source_type,
            KnowledgeResource.source_id,
            KnowledgeResource.external_id,
            KnowledgeResourceVersion.source_type,
            KnowledgeResourceVersion.source_id,
            KnowledgeResourceVersion.external_id,
        )
        .join(
            KnowledgeResourceVersion,
            (KnowledgeResourceVersion.org_id == KnowledgeResource.org_id)
            & (KnowledgeResourceVersion.project_id == KnowledgeResource.project_id)
            & (KnowledgeResourceVersion.resource_id == KnowledgeResource.id),
        )
        .where(
            KnowledgeResource.org_id == org_id,
            KnowledgeResource.project_id == project_id,
            KnowledgeResource.id == resource_id,
            KnowledgeResource.deleted_at.is_(None),
            KnowledgeResourceVersion.id == version_id,
        )
    ).one_or_none()
    if row is None:
        return False
    (
        resource_type,
        resource_source_id,
        resource_external_id,
        version_type,
        version_source_id,
        version_external_id,
    ) = row
    if (
        resource_type != version_type
        or resource_source_id != version_source_id
        or resource_external_id != version_external_id
    ):
        return False
    if resource_type in {ResourceSourceType.UPLOAD, ResourceSourceType.ZIP_ENTRY}:
        return True
    if resource_type != ResourceSourceType.FEISHU:
        return False

    statement = select(KnowledgeSource.id).where(
        KnowledgeSource.org_id == org_id,
        KnowledgeSource.project_id == project_id,
        KnowledgeSource.provider == "feishu",
        KnowledgeSource.status == "configured",
        KnowledgeSource.access_state == "available",
        KnowledgeSource.access_policy == "project_members",
        KnowledgeSource.id.cast(String) == resource_source_id,
        KnowledgeSource.external_id == resource_external_id,
    )
    if lock_source:
        statement = statement.with_for_update()
    return session.scalar(statement) is not None


__all__ = [
    "is_canonical_feishu_revision",
    "source_access_filter",
    "validate_index_source",
]
