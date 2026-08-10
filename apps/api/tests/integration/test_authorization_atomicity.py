from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization import service as authorization_service
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.organizations import service as organization_service
from cairn_api.organizations.models import Membership
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects.models import OutboxEvent, Project
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .authorization_helpers import SeededActor, seed_actor


def _identity(actor: SeededActor) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(
            id=actor.user_id,
            email=actor.email,
            display_name=f"Test {actor.role.value}",
        ),
        organization=OrganizationResponse(
            id=actor.organization_id,
            slug=f"actor-{actor.organization_id}",
            name="Authorization test organization",
        ),
        membership=MembershipResponse(id=actor.membership_id, role=actor.role),
        csrf_token="not-used-by-service-test",
    )


def _audit(trace_id: str) -> RequestAuditContext:
    return RequestAuditContext(
        trace_id=trace_id,
        ip="198.51.100.28",
        user_agent="authorization-atomicity-test",
    )


def _raise_audit_unavailable(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("audit unavailable")


def _install_outbox_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    real_add = Session.add

    def fail_outbox_add(
        session: Session,
        instance: object,
        _warn: bool = True,
    ) -> None:
        if isinstance(instance, OutboxEvent):
            raise RuntimeError("outbox unavailable")  # noqa: TRY004 - injected outage
        real_add(session, instance, _warn=_warn)

    monkeypatch.setattr(Session, "add", fail_outbox_add)


def _assert_membership_change_absent(
    database: Database,
    *,
    org_id: UUID,
    membership_id: UUID,
    trace_id: str,
) -> None:
    with database.session_factory() as session:
        membership = session.get(Membership, membership_id)
        assert membership is not None
        assert membership.role == MembershipRole.VIEWER.value
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.org_id == org_id,
                AuditLog.trace_id == trace_id,
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.org_id == org_id,
                OutboxEvent.event_type == "membership.role_changed",
            )
        ) == 0


def _seed_acl_replacement(database: Database) -> tuple[SeededActor, UUID, UUID]:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = uuid4()
    entry_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            Project(
                id=project_id,
                org_id=actor.organization_id,
                name="Atomic ACL replacement",
            )
        )
        session.add(
            ResourceAclEntry(
                id=entry_id,
                org_id=actor.organization_id,
                resource_type="project",
                resource_id=project_id,
                principal_type="role",
                principal_id="member",
                permission="read",
                granted_by_type="system",
            )
        )
    return actor, project_id, entry_id


def _assert_acl_replacement_absent(
    database: Database,
    *,
    project_id: UUID,
    entry_id: UUID,
    trace_id: str,
) -> None:
    with database.session_factory() as session:
        history = session.scalars(
            select(ResourceAclEntry).where(
                ResourceAclEntry.resource_id == project_id,
                ResourceAclEntry.principal_type == "role",
                ResourceAclEntry.principal_id == "member",
            )
        ).all()
        assert len(history) == 1
        assert history[0].id == entry_id
        assert history[0].permission == ProjectPermission.READ.value
        assert history[0].revoked_at is None
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.resource_id == project_id,
                AuditLog.trace_id == trace_id,
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.aggregate_id == project_id,
                OutboxEvent.event_type == "project.acl_granted",
            )
        ) == 0


@pytest.mark.integration
def test_membership_role_update_rolls_back_when_audit_write_fails(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: audit failure must not commit a membership role change."""
    actor = seed_actor(database, MembershipRole.OWNER)
    target = seed_actor(database, MembershipRole.VIEWER, actor.organization_id)
    trace_id = "req-membership-audit-failure"
    monkeypatch.setattr(
        organization_service,
        "add_audit_log",
        _raise_audit_unavailable,
    )

    with (
        database.session_factory() as session,
        pytest.raises(RuntimeError, match="^audit unavailable$"),
    ):
        organization_service.OrganizationService(session).update_membership_role(
            identity=_identity(actor),
            organization_id=actor.organization_id,
            membership_id=target.membership_id,
            requested_role=MembershipRole.MEMBER,
            audit=_audit(trace_id),
        )

    _assert_membership_change_absent(
        database,
        org_id=actor.organization_id,
        membership_id=target.membership_id,
        trace_id=trace_id,
    )


@pytest.mark.integration
def test_membership_role_update_rolls_back_when_outbox_write_fails(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: Outbox failure must roll back membership and pending audit."""
    actor = seed_actor(database, MembershipRole.OWNER)
    target = seed_actor(database, MembershipRole.VIEWER, actor.organization_id)
    trace_id = "req-membership-outbox-failure"
    _install_outbox_failure(monkeypatch)

    with (
        database.session_factory() as session,
        pytest.raises(RuntimeError, match="^outbox unavailable$"),
    ):
        organization_service.OrganizationService(session).update_membership_role(
            identity=_identity(actor),
            organization_id=actor.organization_id,
            membership_id=target.membership_id,
            requested_role=MembershipRole.MEMBER,
            audit=_audit(trace_id),
        )

    _assert_membership_change_absent(
        database,
        org_id=actor.organization_id,
        membership_id=target.membership_id,
        trace_id=trace_id,
    )


@pytest.mark.integration
def test_acl_replacement_rolls_back_when_audit_write_fails(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: audit failure must restore ACL history and active grant."""
    actor, project_id, entry_id = _seed_acl_replacement(database)
    trace_id = "req-acl-audit-failure"
    monkeypatch.setattr(
        authorization_service,
        "add_audit_log",
        _raise_audit_unavailable,
    )

    with (
        database.session_factory() as session,
        pytest.raises(RuntimeError, match="^audit unavailable$"),
    ):
        authorization_service.ProjectAclService(session).set_acl(
            identity=_identity(actor),
            project_id=project_id,
            principal_type="role",
            principal_id="member",
            permission=ProjectPermission.WRITE,
            audit=_audit(trace_id),
        )

    _assert_acl_replacement_absent(
        database,
        project_id=project_id,
        entry_id=entry_id,
        trace_id=trace_id,
    )


@pytest.mark.integration
def test_acl_replacement_rolls_back_when_outbox_write_fails(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: Outbox failure must restore ACL history and pending audit."""
    actor, project_id, entry_id = _seed_acl_replacement(database)
    trace_id = "req-acl-outbox-failure"
    _install_outbox_failure(monkeypatch)

    with (
        database.session_factory() as session,
        pytest.raises(RuntimeError, match="^outbox unavailable$"),
    ):
        authorization_service.ProjectAclService(session).set_acl(
            identity=_identity(actor),
            project_id=project_id,
            principal_type="role",
            principal_id="member",
            permission=ProjectPermission.WRITE,
            audit=_audit(trace_id),
        )

    _assert_acl_replacement_absent(
        database,
        project_id=project_id,
        entry_id=entry_id,
        trace_id=trace_id,
    )
