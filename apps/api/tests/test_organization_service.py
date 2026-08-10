from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import User
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.types import MembershipRole
from cairn_api.errors import ApiProblem
from cairn_api.organizations.models import Membership, Organization
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.organizations.service import OrganizationService
from cairn_api.projects.models import OutboxEvent
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
org_id = UUID("00000000-0000-4000-8000-000000000601")
target_id = UUID("00000000-0000-4000-8000-000000000602")
AUDIT = RequestAuditContext(
    trace_id="req-membership-role-change",
    ip="198.51.100.61",
    user_agent="membership-service-test",
)


def identity_for(role: str) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(
            id=UUID("00000000-0000-4000-8000-000000000603"),
            email="actor@example.com",
            display_name="Actor",
        ),
        organization=OrganizationResponse(
            id=org_id,
            slug="membership-service",
            name="Membership service",
        ),
        membership=MembershipResponse(
            id=UUID("00000000-0000-4000-8000-000000000604"),
            role=MembershipRole(role),
        ),
        csrf_token="csrf-token",
    )


def _configured_service(
    actor_role: str,
    target_role: str,
    *,
    owner_count: int = 2,
    organization: Organization | None = None,
    actor: Membership | None = None,
    target: Membership | None = None,
) -> tuple[OrganizationService, MagicMock, Membership]:
    session = MagicMock(spec=Session)
    current_organization = organization or Organization(
        id=org_id,
        slug="membership-service",
        name="Membership service",
        created_at=NOW,
    )
    current_actor = actor or Membership(
        id=identity_for(actor_role).membership.id,
        org_id=org_id,
        user_id=identity_for(actor_role).user.id,
        role=actor_role,
        created_at=NOW,
    )
    current_target = target or Membership(
        id=target_id,
        org_id=org_id,
        user_id=UUID("00000000-0000-4000-8000-000000000605"),
        role=target_role,
        created_at=NOW,
    )
    target_user = User(
        id=current_target.user_id,
        email="target@example.com",
        normalized_email="target@example.com",
        display_name="Target user",
        password_hash="not-used",
        created_at=NOW,
    )
    session.scalar.side_effect = [current_organization, current_actor, owner_count]
    session.execute.return_value.one_or_none.return_value = (current_target, target_user)
    return OrganizationService(session), session, current_target


def service_for(actor_role: str, target_role: str) -> OrganizationService:
    return _configured_service(actor_role, target_role)[0]


@pytest.mark.parametrize(
    ("actor", "current", "requested", "allowed"),
    [
        ("owner", "owner", "admin", True),
        ("owner", "viewer", "owner", True),
        ("admin", "member", "viewer", True),
        ("admin", "viewer", "member", True),
        ("admin", "admin", "member", False),
        ("admin", "owner", "viewer", False),
        ("admin", "member", "admin", False),
        ("member", "viewer", "member", False),
        ("viewer", "viewer", "member", False),
    ],
)
def test_membership_role_change_matrix(
    actor: str, current: str, requested: str, allowed: bool
) -> None:
    if allowed:
        result = service_for(actor, current).update_membership_role(
            identity=identity_for(actor),
            organization_id=org_id,
            membership_id=target_id,
            requested_role=MembershipRole(requested),
            audit=AUDIT,
        )
        assert result.role == requested
    else:
        with pytest.raises(ApiProblem) as error:
            service_for(actor, current).update_membership_role(
                identity=identity_for(actor),
                organization_id=org_id,
                membership_id=target_id,
                requested_role=MembershipRole(requested),
                audit=AUDIT,
            )
        assert (error.value.status_code, error.value.code) == (403, "forbidden")


def test_role_change_rejects_path_organization_mismatch_before_database_access() -> None:
    service, session, _target = _configured_service("owner", "viewer")

    with pytest.raises(ApiProblem) as error:
        service.update_membership_role(
            identity=identity_for("owner"),
            organization_id=uuid4(),
            membership_id=target_id,
            requested_role=MembershipRole.MEMBER,
            audit=AUDIT,
        )

    assert (error.value.status_code, error.value.code) == (404, "not_found")
    session.begin.assert_not_called()


@pytest.mark.parametrize("missing", ["organization", "actor", "target"])
def test_role_change_conceals_missing_or_cross_organization_records(missing: str) -> None:
    service, session, _target = _configured_service("owner", "viewer")
    if missing == "organization":
        session.scalar.side_effect = [None]
    elif missing == "actor":
        session.scalar.side_effect = [
            Organization(id=org_id, slug="membership-service", name="Membership service"),
            None,
        ]
    else:
        session.execute.return_value.one_or_none.return_value = None

    with pytest.raises(ApiProblem) as error:
        service.update_membership_role(
            identity=identity_for("owner"),
            organization_id=org_id,
            membership_id=target_id,
            requested_role=MembershipRole.MEMBER,
            audit=AUDIT,
        )

    assert (error.value.status_code, error.value.code) == (404, "not_found")


def test_last_owner_cannot_be_demoted() -> None:
    service, session, target = _configured_service("owner", "owner", owner_count=1)

    with pytest.raises(ApiProblem) as error:
        service.update_membership_role(
            identity=identity_for("owner"),
            organization_id=org_id,
            membership_id=target_id,
            requested_role=MembershipRole.ADMIN,
            audit=AUDIT,
        )

    assert (error.value.status_code, error.value.code) == (409, "last_owner_required")
    assert target.role == "owner"
    session.flush.assert_not_called()
    assert _added(session, AuditLog) == []
    assert _added(session, OutboxEvent) == []


def test_authorized_same_role_patch_has_no_update_audit_or_event() -> None:
    service, session, target = _configured_service("owner", "viewer")

    result = service.update_membership_role(
        identity=identity_for("owner"),
        organization_id=org_id,
        membership_id=target_id,
        requested_role=MembershipRole.VIEWER,
        audit=AUDIT,
    )

    assert result.role is MembershipRole.VIEWER
    assert target.role == "viewer"
    session.flush.assert_not_called()
    assert _added(session, AuditLog) == []
    assert _added(session, OutboxEvent) == []


@pytest.mark.parametrize("role", [MembershipRole.OWNER, MembershipRole.ADMIN])
def test_admin_targeting_privileged_role_is_forbidden_even_for_noop(
    role: MembershipRole,
) -> None:
    service, session, _target = _configured_service("admin", role.value)

    with pytest.raises(ApiProblem) as error:
        service.update_membership_role(
            identity=identity_for("admin"),
            organization_id=org_id,
            membership_id=target_id,
            requested_role=role,
            audit=AUDIT,
        )

    assert (error.value.status_code, error.value.code) == (403, "forbidden")
    session.flush.assert_not_called()


def test_effective_change_records_exact_audit_and_organization_event() -> None:
    service, session, target = _configured_service("owner", "viewer")

    result = service.update_membership_role(
        identity=identity_for("owner"),
        organization_id=org_id,
        membership_id=target_id,
        requested_role=MembershipRole.MEMBER,
        audit=AUDIT,
    )

    assert result.role is MembershipRole.MEMBER
    assert target.role == "member"
    audits = _added(session, AuditLog)
    events = _added(session, OutboxEvent)
    assert len(audits) == len(events) == 1
    expected_details = {
        "organizationId": str(org_id),
        "membershipId": str(target_id),
        "oldRole": "viewer",
        "newRole": "member",
    }
    assert audits[0].action == "membership.role_changed"
    assert audits[0].resource_type == "membership"
    assert audits[0].resource_id == target_id
    assert audits[0].details == expected_details
    assert events[0].event_type == "membership.role_changed"
    assert events[0].aggregate_type == "organization"
    assert events[0].aggregate_id == org_id
    assert events[0].payload == expected_details
    session.begin.assert_called_once_with()


@pytest.mark.parametrize("limit", [0, 101])
def test_list_memberships_rejects_invalid_service_page_limit(limit: int) -> None:
    service = OrganizationService(MagicMock(spec=Session))

    with pytest.raises(ApiProblem) as error:
        service.list_memberships(
            identity=identity_for("owner"),
            organization_id=org_id,
            cursor=None,
            limit=limit,
        )

    assert (error.value.status_code, error.value.code) == (422, "invalid_page_limit")


@pytest.mark.parametrize("role", [MembershipRole.MEMBER, MembershipRole.VIEWER])
def test_list_memberships_forbids_non_managers(role: MembershipRole) -> None:
    with pytest.raises(ApiProblem) as error:
        OrganizationService(MagicMock(spec=Session)).list_memberships(
            identity=identity_for(role.value),
            organization_id=org_id,
            cursor=None,
            limit=50,
        )

    assert (error.value.status_code, error.value.code) == (403, "forbidden")


def _added[Model](session: MagicMock, model_type: type[Model]) -> list[Model]:
    return [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], model_type)
    ]
