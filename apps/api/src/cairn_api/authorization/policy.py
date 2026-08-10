from collections.abc import Iterable
from typing import cast
from uuid import UUID

from sqlalchemy import false, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization import repository
from cairn_api.authorization.types import (
    MembershipRole,
    PrincipalRef,
    PrincipalType,
    ProjectPermission,
    ResourceType,
)
from cairn_api.errors import ApiProblem
from cairn_api.projects.models import Project

_PERMISSION_RANK = {
    ProjectPermission.READ: 1,
    ProjectPermission.WRITE: 2,
    ProjectPermission.MANAGE: 3,
}


def effective_project_permission(
    role: MembershipRole,
    acl_permissions: Iterable[ProjectPermission],
) -> ProjectPermission | None:
    if role in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        return ProjectPermission.MANAGE
    maximum = max(acl_permissions, key=_PERMISSION_RANK.__getitem__, default=None)
    if maximum is None:
        return None
    if role is MembershipRole.VIEWER:
        return ProjectPermission.READ
    return maximum


def permission_allows(
    effective: ProjectPermission | None,
    required: ProjectPermission,
) -> bool:
    return effective is not None and _PERMISSION_RANK[effective] >= _PERMISSION_RANK[required]


def can_create_project(role: MembershipRole) -> bool:
    return role is not MembershipRole.VIEWER


def can_change_membership_role(
    actor: MembershipRole,
    current: MembershipRole,
    requested: MembershipRole,
) -> bool:
    if actor is MembershipRole.OWNER:
        return True
    mutable_by_admin = {MembershipRole.MEMBER, MembershipRole.VIEWER}
    return (
        actor is MembershipRole.ADMIN
        and current in mutable_by_admin
        and requested in mutable_by_admin
    )


def permissions_at_least(required: ProjectPermission) -> tuple[ProjectPermission, ...]:
    return tuple(
        permission
        for permission, rank in _PERMISSION_RANK.items()
        if rank >= _PERMISSION_RANK[required]
    )


class AuthorizationPolicy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def project_filter(
        self,
        identity: IdentityContextResponse,
        required: ProjectPermission,
        resource_id: ColumnElement[UUID],
    ) -> ColumnElement[bool]:
        role = MembershipRole(identity.membership.role)
        if role in {MembershipRole.OWNER, MembershipRole.ADMIN}:
            return true()
        if role is MembershipRole.VIEWER and required is not ProjectPermission.READ:
            return false()
        principals = (
            PrincipalRef(PrincipalType.ORG, str(identity.organization.id)),
            PrincipalRef(PrincipalType.ROLE, role.value),
            PrincipalRef(PrincipalType.USER, str(identity.user.id)),
        )
        return repository.active_acl_exists_clause(
            org_id=identity.organization.id,
            resource_type=ResourceType.PROJECT,
            resource_id=resource_id,
            principals=principals,
            allowed_permissions=permissions_at_least(required),
        )

    def find_project(
        self,
        identity: IdentityContextResponse,
        project_id: UUID,
        required: ProjectPermission,
        *,
        for_update: bool = False,
    ) -> Project | None:
        statement = select(Project).where(
            Project.org_id == identity.organization.id,
            Project.id == project_id,
            self.project_filter(
                identity,
                required,
                cast(ColumnElement[UUID], Project.id),
            ),
        )
        if for_update:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def require_project(
        self,
        identity: IdentityContextResponse,
        project_id: UUID,
        required: ProjectPermission,
        *,
        for_update: bool = False,
    ) -> Project:
        project = self.find_project(identity, project_id, required, for_update=for_update)
        if project is None:
            raise ApiProblem(status_code=404, code="not_found", message="资源不存在")
        return project

    def require_project_creation(self, identity: IdentityContextResponse) -> None:
        if not can_create_project(MembershipRole(identity.membership.role)):
            raise ApiProblem(
                status_code=403,
                code="forbidden",
                message="没有执行该操作的权限",
            )
