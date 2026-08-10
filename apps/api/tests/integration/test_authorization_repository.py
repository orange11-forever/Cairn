from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from cairn_api.auth.models import User
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.authorization import repository
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import (
    ActorType,
    MembershipRole,
    PrincipalRef,
    PrincipalType,
    ProjectPermission,
    ResourceType,
)
from cairn_api.errors import ApiProblem
from cairn_api.organizations.models import Membership, Organization
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects.models import Project
from sqlalchemy import Connection, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

ORG_ID = UUID("00000000-0000-4000-8000-000000003001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000003101")
OWNER_ID = UUID("00000000-0000-4000-8000-000000003201")
MEMBER_ID = UUID("00000000-0000-4000-8000-000000003202")
VIEWER_ID = UUID("00000000-0000-4000-8000-000000003203")
UNRELATED_ID = UUID("00000000-0000-4000-8000-000000003204")


def _identity(user_id: UUID, role: MembershipRole) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(id=user_id, email=f"{role.value}@example.test", display_name=None),
        organization=OrganizationResponse(id=ORG_ID, slug="acl-policy", name="ACL Policy"),
        membership=MembershipResponse(id=UUID(int=user_id.int + 1000), role=role),
        csrf_token="test-csrf",
    )


def _seed_policy_graph(session: Session) -> Project:
    session.add(Organization(id=ORG_ID, slug="acl-policy", name="ACL Policy"))
    memberships: list[Membership] = []
    for user_id, role in (
        (OWNER_ID, MembershipRole.OWNER),
        (MEMBER_ID, MembershipRole.MEMBER),
        (VIEWER_ID, MembershipRole.VIEWER),
    ):
        session.add(
            User(
                id=user_id,
                email=f"{role.value}@example.test",
                normalized_email=f"{role.value}@example.test",
                password_hash="not-used",
            )
        )
        memberships.append(Membership(org_id=ORG_ID, user_id=user_id, role=role.value))
    session.flush()
    session.add_all(memberships)
    project = Project(id=PROJECT_ID, org_id=ORG_ID, name="ACL project")
    session.add(project)
    session.flush()
    for principal, permission in (
        (PrincipalRef(PrincipalType.ORG, str(ORG_ID)), ProjectPermission.READ),
        (PrincipalRef(PrincipalType.ROLE, MembershipRole.VIEWER.value), ProjectPermission.WRITE),
        (PrincipalRef(PrincipalType.USER, str(UNRELATED_ID)), ProjectPermission.MANAGE),
    ):
        repository.create_entry(
            session,
            org_id=ORG_ID,
            resource_type=ResourceType.PROJECT,
            resource_id=PROJECT_ID,
            principal=principal,
            permission=permission,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
    return project


@pytest.mark.integration
def test_database_policy_resolves_org_role_user_grants_and_role_ceiling(
    migrated_connection: Connection,
) -> None:
    # Break caught: the SQL authorization predicate grants too much or ignores a principal.
    with Session(bind=migrated_connection) as session:
        project = _seed_policy_graph(session)
        policy = AuthorizationPolicy(session)
        member_identity = _identity(MEMBER_ID, MembershipRole.MEMBER)
        viewer_identity = _identity(VIEWER_ID, MembershipRole.VIEWER)
        owner_identity = _identity(OWNER_ID, MembershipRole.OWNER)

        assert policy.find_project(member_identity, project.id, ProjectPermission.READ) == project
        assert policy.find_project(member_identity, project.id, ProjectPermission.WRITE) is None
        assert policy.find_project(viewer_identity, project.id, ProjectPermission.WRITE) is None
        assert policy.find_project(owner_identity, project.id, ProjectPermission.MANAGE) == project
        assert policy.require_project(
            member_identity,
            project.id,
            ProjectPermission.READ,
        ) == project
        with pytest.raises(ApiProblem) as exc_info:
            policy.require_project(
                member_identity,
                project.id,
                ProjectPermission.WRITE,
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "not_found"
        assert exc_info.value.message == "资源不存在"


@pytest.mark.integration
def test_locked_project_check_conceals_missing_cross_org_or_cross_user_membership(
    migrated_connection: Connection,
) -> None:
    """Break caught: locked authorization must bind membership to org and user."""
    other_org_id = UUID("00000000-0000-4000-8000-000000003002")
    with Session(bind=migrated_connection) as session:
        project = _seed_policy_graph(session)
        owner_membership = session.scalars(
            select(Membership).where(
                Membership.org_id == ORG_ID,
                Membership.user_id == OWNER_ID,
            )
        ).one()
        member_membership = session.scalars(
            select(Membership).where(
                Membership.org_id == ORG_ID,
                Membership.user_id == MEMBER_ID,
            )
        ).one()
        session.add(Organization(id=other_org_id, slug="other-policy", name="Other"))
        session.flush()
        cross_org_membership = Membership(
            org_id=other_org_id,
            user_id=OWNER_ID,
            role=MembershipRole.OWNER.value,
        )
        session.add(cross_org_membership)
        session.flush()

        policy = AuthorizationPolicy(session)
        base_identity = _identity(OWNER_ID, MembershipRole.OWNER)

        def identity_with_membership(membership_id: UUID) -> IdentityContextResponse:
            return base_identity.model_copy(
                update={
                    "membership": MembershipResponse(
                        id=membership_id,
                        role=MembershipRole.OWNER,
                    )
                }
            )

        assert policy.find_project(
            identity_with_membership(owner_membership.id),
            project.id,
            ProjectPermission.MANAGE,
            for_update=True,
        ) == project
        for invalid_membership_id in (
            uuid4(),
            member_membership.id,
            cross_org_membership.id,
        ):
            assert (
                policy.find_project(
                    identity_with_membership(invalid_membership_id),
                    project.id,
                    ProjectPermission.MANAGE,
                    for_update=True,
                )
                is None
            )


@pytest.mark.integration
def test_acl_repository_preserves_history_and_pages_active_rows_stably(
    migrated_connection: Connection,
) -> None:
    # Break caught: revocation deletes history or active paging skips equal timestamps.
    granted_at = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)
    principals = (
        PrincipalRef(PrincipalType.ORG, str(ORG_ID)),
        PrincipalRef(PrincipalType.ROLE, MembershipRole.MEMBER.value),
        PrincipalRef(PrincipalType.USER, str(MEMBER_ID)),
    )
    with Session(bind=migrated_connection) as session:
        session.add(Organization(id=ORG_ID, slug="acl-history", name="ACL History"))
        project = Project(id=PROJECT_ID, org_id=ORG_ID, name="ACL history project")
        session.add(project)
        session.flush()
        entries = [
            repository.create_entry(
                session,
                org_id=ORG_ID,
                resource_type=ResourceType.PROJECT,
                resource_id=PROJECT_ID,
                principal=principal,
                permission=ProjectPermission.READ,
                actor_type=ActorType.SYSTEM,
                actor_id=None,
            )
            for principal in principals
        ]
        for index, entry in enumerate(entries, start=1):
            entry.id = UUID(int=index)
            entry.granted_at = granted_at
        session.flush()
        repository.revoke_entry(
            session,
            entry=entries[0],
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )

        assert repository.get_active_entry(
            session,
            org_id=ORG_ID,
            resource_type=ResourceType.PROJECT,
            resource_id=PROJECT_ID,
            principal=principals[0],
        ) is None
        first_page, cursor = repository.list_active_entries(
            session,
            org_id=ORG_ID,
            resource_type=ResourceType.PROJECT,
            resource_id=PROJECT_ID,
            cursor=None,
            limit=1,
        )
        second_page, final_cursor = repository.list_active_entries(
            session,
            org_id=ORG_ID,
            resource_type=ResourceType.PROJECT,
            resource_id=PROJECT_ID,
            cursor=cursor,
            limit=1,
        )
        all_rows = list(session.scalars(select(ResourceAclEntry)).all())

    assert [entry.id for entry in first_page] == [UUID(int=2)]
    assert [entry.id for entry in second_page] == [UUID(int=3)]
    assert cursor is not None
    assert final_cursor is None
    assert len(all_rows) == 3
    history_by_id = {entry.id: entry for entry in all_rows}
    assert history_by_id[UUID(int=1)].revoked_at is not None
    assert history_by_id[UUID(int=1)].revoked_by_type == ActorType.SYSTEM.value


@pytest.mark.integration
def test_current_org_member_is_scoped_to_both_org_and_user(
    migrated_connection: Connection,
) -> None:
    # Break caught: membership validation accepts a user from another organization.
    with Session(bind=migrated_connection) as session:
        _seed_policy_graph(session)
        assert repository.is_current_org_member(session, org_id=ORG_ID, user_id=MEMBER_ID)
        assert not repository.is_current_org_member(session, org_id=ORG_ID, user_id=UNRELATED_ID)


def test_member_project_predicate_compiles_complete_tenant_scoped_acl_exists() -> None:
    # Break caught: the correlated EXISTS omits tenant, resource, principal, or active filters.
    identity = _identity(MEMBER_ID, MembershipRole.MEMBER)
    policy = AuthorizationPolicy(Session())
    statement = select(Project).where(
        policy.project_filter(
            identity,
            ProjectPermission.WRITE,
            cast(ColumnElement[UUID], Project.id),
        )
    )

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    for fragment in (
        "resource_acl_entries.org_id",
        "resource_acl_entries.resource_type",
        "resource_acl_entries.resource_id",
        "resource_acl_entries.principal_type",
        "resource_acl_entries.principal_id",
        "resource_acl_entries.permission",
        "resource_acl_entries.revoked_at IS NULL",
    ):
        assert fragment in sql
