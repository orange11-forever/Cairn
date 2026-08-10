from collections.abc import Iterable

from cairn_api.authorization.types import MembershipRole, ProjectPermission

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
