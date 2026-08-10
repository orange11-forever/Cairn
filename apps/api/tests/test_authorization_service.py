from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization import repository
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.service import ProjectAclService
from cairn_api.authorization.types import (
    ActorType,
    MembershipRole,
    PrincipalRef,
    PrincipalType,
    ProjectPermission,
    ResourceType,
)
from cairn_api.errors import ApiProblem
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects.models import OutboxEvent, Project
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
OTHER_ORG_ID = uuid4()
NON_MEMBER_USER_ID = uuid4()
AUDIT = RequestAuditContext(
    trace_id="req-acl-service",
    ip="198.51.100.25",
    user_agent="acl-service-test",
)


def _identity(
    org_id: UUID,
    *,
    user_id: UUID | None = None,
    role: MembershipRole = MembershipRole.OWNER,
) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(
            id=user_id or uuid4(),
            email="owner@example.com",
            display_name="Owner",
        ),
        organization=OrganizationResponse(
            id=org_id,
            slug=f"org-{org_id}",
            name="Organization",
        ),
        membership=MembershipResponse(id=uuid4(), role=role),
        csrf_token="csrf-token",
    )


def _project(org_id: UUID) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id,
        name="ACL project",
        description=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _entry(
    *,
    org_id: UUID,
    project_id: UUID,
    principal_type: PrincipalType = PrincipalType.ROLE,
    principal_id: str = MembershipRole.MEMBER.value,
    permission: ProjectPermission = ProjectPermission.READ,
    actor_id: UUID | None = None,
) -> ResourceAclEntry:
    return ResourceAclEntry(
        id=uuid4(),
        org_id=org_id,
        resource_type=ResourceType.PROJECT.value,
        resource_id=project_id,
        principal_type=principal_type.value,
        principal_id=principal_id,
        permission=permission.value,
        granted_by_type=ActorType.USER.value,
        granted_by_id=actor_id or uuid4(),
        granted_at=NOW,
    )


def _added[Model](session: MagicMock, model_type: type[Model]) -> list[Model]:
    return [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], model_type)
    ]


def added_audits(session: MagicMock) -> list[AuditLog]:
    return _added(session, AuditLog)


def added_outbox_events(session: MagicMock) -> list[OutboxEvent]:
    return _added(session, OutboxEvent)


def test_list_acl_requires_manage_and_preserves_repository_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    owner_identity = _identity(uuid4())
    project = _project(owner_identity.organization.id)
    entries = [
        _entry(org_id=project.org_id, project_id=project.id),
        _entry(
            org_id=project.org_id,
            project_id=project.id,
            principal_type=PrincipalType.USER,
            principal_id=str(uuid4()),
            permission=ProjectPermission.WRITE,
        ),
    ]
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.return_value = project

    def list_active_entries(
        db: Session,
        *,
        org_id: UUID,
        resource_type: ResourceType,
        resource_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[ResourceAclEntry], str | None]:
        assert db is session
        assert (org_id, resource_type, resource_id) == (
            owner_identity.organization.id,
            ResourceType.PROJECT,
            project.id,
        )
        assert (cursor, limit) == ("current-page", 2)
        return entries, "next-page"

    monkeypatch.setattr(repository, "list_active_entries", list_active_entries)

    page = ProjectAclService(session, policy=policy).list_acl(
        identity=owner_identity,
        project_id=project.id,
        cursor="current-page",
        limit=2,
    )

    assert [item.id for item in page.items] == [entry.id for entry in entries]
    assert page.next_cursor == "next-page"
    policy.require_project.assert_called_once_with(
        owner_identity,
        project.id,
        ProjectPermission.MANAGE,
    )


@pytest.mark.parametrize("limit", [0, 101])
def test_list_acl_rejects_invalid_service_page_limits(limit: int) -> None:
    service = ProjectAclService(
        MagicMock(spec=Session),
        policy=MagicMock(spec=AuthorizationPolicy),
    )

    with pytest.raises(ApiProblem) as error:
        service.list_acl(
            identity=_identity(uuid4()),
            project_id=uuid4(),
            cursor=None,
            limit=limit,
        )

    assert (error.value.status_code, error.value.code) == (422, "invalid_page_limit")


def test_setting_same_active_acl_is_a_side_effect_free_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    owner_identity = _identity(uuid4())
    project = _project(owner_identity.organization.id)
    existing = _entry(
        org_id=project.org_id,
        project_id=project.id,
        permission=ProjectPermission.WRITE,
    )
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.return_value = project
    monkeypatch.setattr(repository, "get_active_entry", MagicMock(return_value=existing))
    revoke_entry = MagicMock()
    create_entry = MagicMock()
    monkeypatch.setattr(repository, "revoke_entry", revoke_entry)
    monkeypatch.setattr(repository, "create_entry", create_entry)
    service = ProjectAclService(session, policy=policy)

    result = service.set_acl(
        identity=owner_identity,
        project_id=project.id,
        principal_type="role",
        principal_id="member",
        permission=ProjectPermission.WRITE,
        audit=AUDIT,
    )

    assert result.id == existing.id
    assert added_audits(session) == []
    assert added_outbox_events(session) == []
    revoke_entry.assert_not_called()
    create_entry.assert_not_called()


def test_first_grant_inserts_entry_and_one_transactional_change_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    owner_identity = _identity(uuid4())
    project = _project(owner_identity.organization.id)
    created = _entry(
        org_id=project.org_id,
        project_id=project.id,
        permission=ProjectPermission.READ,
        actor_id=owner_identity.user.id,
    )
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.return_value = project
    monkeypatch.setattr(repository, "get_active_entry", MagicMock(return_value=None))
    create_entry = MagicMock(return_value=created)
    revoke_entry = MagicMock()
    monkeypatch.setattr(repository, "create_entry", create_entry)
    monkeypatch.setattr(repository, "revoke_entry", revoke_entry)

    result = ProjectAclService(session, policy=policy).set_acl(
        identity=owner_identity,
        project_id=project.id,
        principal_type="role",
        principal_id="member",
        permission=ProjectPermission.READ,
        audit=AUDIT,
    )

    assert result.id == created.id
    revoke_entry.assert_not_called()
    create_entry.assert_called_once_with(
        session,
        org_id=project.org_id,
        resource_type=ResourceType.PROJECT,
        resource_id=project.id,
        principal=PrincipalRef(PrincipalType.ROLE, MembershipRole.MEMBER.value),
        permission=ProjectPermission.READ,
        actor_type=ActorType.USER,
        actor_id=owner_identity.user.id,
    )
    audits = added_audits(session)
    events = added_outbox_events(session)
    assert len(audits) == len(events) == 1
    expected_change = {
        "projectId": str(project.id),
        "principalType": "role",
        "principalId": "member",
        "oldPermission": None,
        "newPermission": "read",
    }
    assert audits[0].action == "project.acl_granted"
    assert audits[0].details == expected_change
    assert events[0].event_type == "project.acl_granted"
    assert events[0].payload == expected_change
    session.begin.assert_called_once_with()


def test_replacing_acl_revokes_old_and_inserts_new_with_one_change_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    owner_identity = _identity(uuid4())
    project = _project(owner_identity.organization.id)
    existing = _entry(org_id=project.org_id, project_id=project.id)
    replacement = _entry(
        org_id=project.org_id,
        project_id=project.id,
        permission=ProjectPermission.WRITE,
        actor_id=owner_identity.user.id,
    )
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.return_value = project
    monkeypatch.setattr(repository, "get_active_entry", MagicMock(return_value=existing))
    revoke_entry = MagicMock()
    create_entry = MagicMock(return_value=replacement)
    monkeypatch.setattr(repository, "revoke_entry", revoke_entry)
    monkeypatch.setattr(repository, "create_entry", create_entry)

    result = ProjectAclService(session, policy=policy).set_acl(
        identity=owner_identity,
        project_id=project.id,
        principal_type="role",
        principal_id="member",
        permission=ProjectPermission.WRITE,
        audit=AUDIT,
    )

    assert result.id == replacement.id
    revoke_entry.assert_called_once_with(
        session,
        entry=existing,
        actor_type=ActorType.USER,
        actor_id=owner_identity.user.id,
    )
    assert added_audits(session)[0].details["oldPermission"] == "read"
    assert added_audits(session)[0].details["newPermission"] == "write"
    assert len(added_audits(session)) == len(added_outbox_events(session)) == 1


def test_existing_revoke_records_exactly_one_revoke_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    owner_identity = _identity(uuid4())
    project = _project(owner_identity.organization.id)
    existing = _entry(
        org_id=project.org_id,
        project_id=project.id,
        permission=ProjectPermission.MANAGE,
    )
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.return_value = project
    monkeypatch.setattr(repository, "get_active_entry", MagicMock(return_value=existing))
    revoke_entry = MagicMock()
    monkeypatch.setattr(repository, "revoke_entry", revoke_entry)

    ProjectAclService(session, policy=policy).revoke_acl(
        identity=owner_identity,
        project_id=project.id,
        principal_type="role",
        principal_id="member",
        audit=AUDIT,
    )

    revoke_entry.assert_called_once_with(
        session,
        entry=existing,
        actor_type=ActorType.USER,
        actor_id=owner_identity.user.id,
    )
    audits = added_audits(session)
    events = added_outbox_events(session)
    assert len(audits) == len(events) == 1
    assert audits[0].action == events[0].event_type == "project.acl_revoked"
    assert audits[0].details == events[0].payload == {
        "projectId": str(project.id),
        "principalType": "role",
        "principalId": "member",
        "oldPermission": "manage",
        "newPermission": None,
    }


def test_missing_revoke_is_a_side_effect_free_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    owner_identity = _identity(uuid4())
    project = _project(owner_identity.organization.id)
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.return_value = project
    monkeypatch.setattr(repository, "get_active_entry", MagicMock(return_value=None))
    revoke_entry = MagicMock()
    monkeypatch.setattr(repository, "revoke_entry", revoke_entry)

    ProjectAclService(session, policy=policy).revoke_acl(
        identity=owner_identity,
        project_id=project.id,
        principal_type="role",
        principal_id="member",
        audit=AUDIT,
    )

    revoke_entry.assert_not_called()
    assert added_audits(session) == []
    assert added_outbox_events(session) == []


def test_valid_user_principal_is_canonicalized_after_current_membership_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    owner_identity = _identity(uuid4())
    project = _project(owner_identity.organization.id)
    target_id = uuid4()
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.return_value = project
    membership_check = MagicMock(return_value=True)
    monkeypatch.setattr(repository, "is_current_org_member", membership_check)
    monkeypatch.setattr(repository, "get_active_entry", MagicMock(return_value=None))
    created = _entry(
        org_id=project.org_id,
        project_id=project.id,
        principal_type=PrincipalType.USER,
        principal_id=str(target_id),
    )
    create_entry = MagicMock(return_value=created)
    monkeypatch.setattr(repository, "create_entry", create_entry)

    ProjectAclService(session, policy=policy).set_acl(
        identity=owner_identity,
        project_id=project.id,
        principal_type="user",
        principal_id=str(target_id).upper(),
        permission=ProjectPermission.READ,
        audit=AUDIT,
    )

    membership_check.assert_called_once_with(
        session,
        org_id=owner_identity.organization.id,
        user_id=target_id,
    )
    assert create_entry.call_args.kwargs["principal"] == PrincipalRef(
        PrincipalType.USER,
        str(target_id),
    )


@pytest.mark.parametrize(
    ("principal_type", "principal_id"),
    [
        ("group", "engineering"),
        ("unknown", "value"),
        ("org", "not-a-uuid"),
        ("org", str(OTHER_ORG_ID)),
        ("role", "super-admin"),
        ("user", str(NON_MEMBER_USER_ID)),
    ],
)
def test_invalid_principal_cases_are_indistinguishable(
    principal_type: str,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    owner_identity = _identity(uuid4())
    project = _project(owner_identity.organization.id)
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.return_value = project
    monkeypatch.setattr(repository, "is_current_org_member", MagicMock(return_value=False))
    get_active_entry = MagicMock()
    monkeypatch.setattr(repository, "get_active_entry", get_active_entry)
    service = ProjectAclService(session, policy=policy)

    with pytest.raises(ApiProblem) as error:
        service.set_acl(
            identity=owner_identity,
            project_id=project.id,
            principal_type=principal_type,
            principal_id=principal_id,
            permission=ProjectPermission.READ,
            audit=AUDIT,
        )

    assert (error.value.status_code, error.value.code) == (422, "invalid_principal")
    assert error.value.message == "授权主体无效"
    get_active_entry.assert_not_called()
    assert added_audits(session) == []
    assert added_outbox_events(session) == []


@pytest.mark.parametrize("operation", ["list", "set", "revoke"])
def test_acl_management_conceals_project_without_manage_permission(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    identity = _identity(uuid4(), role=MembershipRole.MEMBER)
    policy = MagicMock(spec=AuthorizationPolicy)
    policy.require_project.side_effect = ApiProblem(
        status_code=404,
        code="not_found",
        message="资源不存在",
    )
    get_active_entry = MagicMock()
    list_active_entries = MagicMock()
    monkeypatch.setattr(repository, "get_active_entry", get_active_entry)
    monkeypatch.setattr(repository, "list_active_entries", list_active_entries)
    service = ProjectAclService(session, policy=policy)

    with pytest.raises(ApiProblem) as error:
        if operation == "list":
            service.list_acl(
                identity=identity,
                project_id=uuid4(),
                cursor=None,
                limit=50,
            )
        elif operation == "set":
            service.set_acl(
                identity=identity,
                project_id=uuid4(),
                principal_type="role",
                principal_id="member",
                permission=ProjectPermission.READ,
                audit=AUDIT,
            )
        else:
            service.revoke_acl(
                identity=identity,
                project_id=uuid4(),
                principal_type="role",
                principal_id="member",
                audit=AUDIT,
            )

    assert (error.value.status_code, error.value.code) == (404, "not_found")
    get_active_entry.assert_not_called()
    list_active_entries.assert_not_called()
    assert added_audits(session) == []
    assert added_outbox_events(session) == []
