from uuid import UUID

import pytest
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.authorization.policy import (
    AuthorizationPolicy,
    can_change_membership_role,
    can_create_project,
    effective_project_permission,
    permission_allows,
)
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from sqlalchemy.orm import Session


def _identity(role: MembershipRole) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(
            id=UUID("00000000-0000-4000-8000-000000000101"),
            email="policy@example.test",
            display_name=None,
        ),
        organization=OrganizationResponse(
            id=UUID("00000000-0000-4000-8000-000000000201"),
            slug="policy",
            name="Policy",
        ),
        membership=MembershipResponse(
            id=UUID("00000000-0000-4000-8000-000000000301"),
            role=role,
        ),
        csrf_token="test-csrf",
    )


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


def test_database_policy_rejects_viewer_project_creation_with_forbidden_problem() -> None:
    # Break caught: route callers can bypass the project-creation role matrix.
    policy = AuthorizationPolicy(Session())

    with pytest.raises(ApiProblem) as exc_info:
        policy.require_project_creation(_identity(MembershipRole.VIEWER))

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "forbidden"
    assert exc_info.value.message == "没有执行该操作的权限"


def test_database_policy_allows_member_project_creation() -> None:
    # Break caught: ordinary members are incorrectly denied project creation.
    AuthorizationPolicy(Session()).require_project_creation(_identity(MembershipRole.MEMBER))
