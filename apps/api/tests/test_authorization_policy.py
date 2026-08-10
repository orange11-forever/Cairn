import pytest
from cairn_api.authorization.policy import (
    can_change_membership_role,
    can_create_project,
    effective_project_permission,
    permission_allows,
)
from cairn_api.authorization.types import MembershipRole, ProjectPermission


@pytest.mark.parametrize(
    ("role", "grants", "expected"),
    [
        (MembershipRole.OWNER, (), ProjectPermission.MANAGE),
        (MembershipRole.ADMIN, (), ProjectPermission.MANAGE),
        (MembershipRole.MEMBER, (), None),
        (MembershipRole.MEMBER, (ProjectPermission.READ,), ProjectPermission.READ),
        (MembershipRole.MEMBER, (ProjectPermission.WRITE,), ProjectPermission.WRITE),
        (MembershipRole.MEMBER, (ProjectPermission.MANAGE,), ProjectPermission.MANAGE),
        (MembershipRole.VIEWER, (), None),
        (MembershipRole.VIEWER, (ProjectPermission.READ,), ProjectPermission.READ),
        (MembershipRole.VIEWER, (ProjectPermission.WRITE,), ProjectPermission.READ),
        (MembershipRole.VIEWER, (ProjectPermission.MANAGE,), ProjectPermission.READ),
    ],
)
def test_effective_project_permission_applies_global_grants_and_role_ceiling(
    role: MembershipRole,
    grants: tuple[ProjectPermission, ...],
    expected: ProjectPermission | None,
) -> None:
    assert effective_project_permission(role, grants) == expected


def test_permission_hierarchy_is_monotonic() -> None:
    assert permission_allows(ProjectPermission.MANAGE, ProjectPermission.READ)
    assert permission_allows(ProjectPermission.WRITE, ProjectPermission.READ)
    assert not permission_allows(ProjectPermission.READ, ProjectPermission.WRITE)
    assert not permission_allows(None, ProjectPermission.READ)


def test_project_creation_and_membership_role_matrix_are_explicit() -> None:
    assert all(
        can_create_project(role)
        for role in (
            MembershipRole.OWNER,
            MembershipRole.ADMIN,
            MembershipRole.MEMBER,
        )
    )
    assert not can_create_project(MembershipRole.VIEWER)
    assert can_change_membership_role(
        MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.OWNER
    )
    assert can_change_membership_role(
        MembershipRole.ADMIN, MembershipRole.MEMBER, MembershipRole.VIEWER
    )
    assert not can_change_membership_role(
        MembershipRole.ADMIN, MembershipRole.ADMIN, MembershipRole.MEMBER
    )
    assert not can_change_membership_role(
        MembershipRole.ADMIN, MembershipRole.MEMBER, MembershipRole.ADMIN
    )
    assert not can_change_membership_role(
        MembershipRole.MEMBER, MembershipRole.VIEWER, MembershipRole.MEMBER
    )
