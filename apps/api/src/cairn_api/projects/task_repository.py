"""Bounded, scoped task dependency and assignable-member reads."""

import base64
import json
from typing import cast
from uuid import UUID

from sqlalchemy import String, and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.auth.models import User
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import permissions_at_least
from cairn_api.authorization.types import ProjectPermission
from cairn_api.organizations.models import Membership
from cairn_api.pagination import InvalidCursorError, page_by_timestamp
from cairn_api.projects.models import TaskDependency


def unwrap_cursor(cursor: str | None, scope: str) -> str | None:
    if cursor is None:
        return None
    try:
        payload = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(payload, dict):
            raise TypeError("cursor must be an object")
        payload = cast(dict[str, object], payload)
        inner = payload.get("cursor")
        if payload.get("scope") != scope or not isinstance(inner, str):
            raise ValueError("cursor scope mismatch")
        return inner
    except (ValueError, TypeError) as exc:
        raise InvalidCursorError("invalid task cursor") from exc


def wrap_cursor(cursor: str | None, scope: str) -> str | None:
    if cursor is None:
        return None
    return (
        base64.urlsafe_b64encode(
            json.dumps({"scope": scope, "cursor": cursor}, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


def assignable_members(org_id: UUID, project_id: UUID) -> ColumnElement[bool]:
    # READ accepts every project permission; viewers remain assignable readers.
    acl = exists(
        select(ResourceAclEntry.id).where(
            ResourceAclEntry.org_id == org_id,
            ResourceAclEntry.resource_type == "project",
            ResourceAclEntry.resource_id == project_id,
            ResourceAclEntry.revoked_at.is_(None),
            ResourceAclEntry.permission.in_(
                tuple(p.value for p in permissions_at_least(ProjectPermission.READ))
            ),
            or_(
                and_(
                    ResourceAclEntry.principal_type == "org",
                    ResourceAclEntry.principal_id == str(org_id),
                ),
                and_(
                    ResourceAclEntry.principal_type == "role",
                    ResourceAclEntry.principal_id == Membership.role,
                ),
                and_(
                    ResourceAclEntry.principal_type == "user",
                    ResourceAclEntry.principal_id
                    == cast(ColumnElement[str], Membership.user_id).cast(String),
                ),
            ),
        )
    ).correlate(Membership)
    return or_(Membership.role.in_(("owner", "admin")), acl)


def member_statement(org_id: UUID, project_id: UUID):
    return (
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.org_id == org_id,
            User.is_active.is_(True),
            assignable_members(org_id, project_id),
        )
    )


def list_assignees(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    requester_id: UUID,
    cursor: str | None,
    limit: int,
) -> tuple[list[tuple[Membership, User]], str | None]:
    scope = f"assignees:{org_id}:{project_id}:{requester_id}"
    memberships, next_cursor = page_by_timestamp(
        session,
        member_statement(org_id, project_id),
        timestamp_column=Membership.created_at,
        id_column=Membership.id,
        cursor=unwrap_cursor(cursor, scope),
        limit=limit,
    )
    if not memberships:
        return [], wrap_cursor(next_cursor, scope)
    users = {
        user.id: user
        for user in session.scalars(
            select(User).where(User.id.in_([m.user_id for m in memberships]))
        )
    }
    return [(m, users[m.user_id]) for m in memberships], wrap_cursor(next_cursor, scope)


def list_dependencies(
    session: Session, *, org_id: UUID, task_id: UUID, cursor: str | None, limit: int
) -> tuple[list[TaskDependency], str | None]:
    scope = f"dependencies:{org_id}:{task_id}"
    rows, next_cursor = page_by_timestamp(
        session,
        select(TaskDependency).where(
            TaskDependency.org_id == org_id, TaskDependency.successor_task_id == task_id
        ),
        timestamp_column=TaskDependency.created_at,
        id_column=TaskDependency.id,
        cursor=unwrap_cursor(cursor, scope),
        limit=limit,
    )
    return rows, wrap_cursor(next_cursor, scope)
