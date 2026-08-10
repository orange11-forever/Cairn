from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import (
    ActorType,
    MembershipRole,
    PrincipalRef,
    ProjectPermission,
    ResourceType,
)
from cairn_api.organizations.models import Membership
from cairn_api.pagination import page_by_timestamp


def get_active_entry(
    session: Session,
    *,
    org_id: UUID,
    resource_type: ResourceType,
    resource_id: UUID,
    principal: PrincipalRef,
    for_update: bool = False,
) -> ResourceAclEntry | None:
    statement = select(ResourceAclEntry).where(
        ResourceAclEntry.org_id == org_id,
        ResourceAclEntry.resource_type == resource_type.value,
        ResourceAclEntry.resource_id == resource_id,
        ResourceAclEntry.principal_type == principal.principal_type.value,
        ResourceAclEntry.principal_id == principal.principal_id,
        ResourceAclEntry.revoked_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def list_active_entries(
    session: Session,
    *,
    org_id: UUID,
    resource_type: ResourceType,
    resource_id: UUID,
    cursor: str | None,
    limit: int,
) -> tuple[list[ResourceAclEntry], str | None]:
    statement = select(ResourceAclEntry).where(
        ResourceAclEntry.org_id == org_id,
        ResourceAclEntry.resource_type == resource_type.value,
        ResourceAclEntry.resource_id == resource_id,
        ResourceAclEntry.revoked_at.is_(None),
    )
    return page_by_timestamp(
        session,
        statement,
        timestamp_column=ResourceAclEntry.granted_at,
        id_column=ResourceAclEntry.id,
        cursor=cursor,
        limit=limit,
    )


def create_entry(
    session: Session,
    *,
    org_id: UUID,
    resource_type: ResourceType,
    resource_id: UUID,
    principal: PrincipalRef,
    permission: ProjectPermission,
    actor_type: ActorType,
    actor_id: UUID | None,
) -> ResourceAclEntry:
    entry = ResourceAclEntry(
        org_id=org_id,
        resource_type=resource_type.value,
        resource_id=resource_id,
        principal_type=principal.principal_type.value,
        principal_id=principal.principal_id,
        permission=permission.value,
        granted_by_type=actor_type.value,
        granted_by_id=actor_id,
    )
    session.add(entry)
    session.flush()
    return entry


def revoke_entry(
    session: Session,
    *,
    entry: ResourceAclEntry,
    actor_type: ActorType,
    actor_id: UUID | None,
) -> None:
    entry.revoked_at = cast(datetime, func.now())
    entry.revoked_by_type = actor_type.value
    entry.revoked_by_id = actor_id
    session.flush()


def is_current_org_member(session: Session, *, org_id: UUID, user_id: UUID) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    Membership.org_id == org_id,
                    Membership.user_id == user_id,
                )
            )
        )
    )


def get_current_membership_role(
    session: Session,
    *,
    org_id: UUID,
    membership_id: UUID,
    user_id: UUID,
    for_update: bool = False,
) -> MembershipRole | None:
    statement = select(Membership.role).where(
        Membership.org_id == org_id,
        Membership.id == membership_id,
        Membership.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update(of=Membership)
    role = session.scalar(statement)
    return None if role is None else MembershipRole(role)


def active_acl_exists_clause(
    *,
    org_id: UUID,
    resource_type: ResourceType,
    resource_id: ColumnElement[UUID],
    principals: tuple[PrincipalRef, ...],
    allowed_permissions: tuple[ProjectPermission, ...],
) -> ColumnElement[bool]:
    principal_predicate = or_(
        *(
            and_(
                ResourceAclEntry.principal_type == principal.principal_type.value,
                ResourceAclEntry.principal_id == principal.principal_id,
            )
            for principal in principals
        )
    )
    return (
        exists(
            select(ResourceAclEntry.id).where(
                ResourceAclEntry.org_id == org_id,
                ResourceAclEntry.resource_type == resource_type.value,
                ResourceAclEntry.resource_id == resource_id,
                ResourceAclEntry.revoked_at.is_(None),
                ResourceAclEntry.permission.in_(
                    tuple(permission.value for permission in allowed_permissions)
                ),
                principal_predicate,
            )
        )
        .correlate_except(ResourceAclEntry)
    )


__all__ = [
    "active_acl_exists_clause",
    "create_entry",
    "get_active_entry",
    "get_current_membership_role",
    "is_current_org_member",
    "list_active_entries",
    "revoke_entry",
]
