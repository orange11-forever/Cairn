from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.schemas import AclEntryResponse
from cairn_api.authorization.service import ProjectAclService
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem
from cairn_api.organizations import repository as organization_repository
from cairn_api.organizations.models import Membership, Organization
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.organizations.service import OrganizationService
from cairn_api.projects.models import OutboxEvent, Project
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from .authorization_helpers import SeededActor, seed_actor
from .concurrency_helpers import (
    FUTURE_SECONDS,
    WAIT_SECONDS,
    LockGate,
    WorkerRole,
    assert_waiting_on_lock,
    install_race_session_deadlines,
)


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
        ip="198.51.100.27",
        user_agent="authorization-concurrency-test",
    )


@pytest.mark.integration
def test_concurrent_owner_demotions_preserve_one_owner(
    database: Database,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: counting owners without the organization lock loses all owners."""
    actor = seed_actor(database, MembershipRole.OWNER)
    other_owner = seed_actor(database, MembershipRole.OWNER, actor.organization_id)
    identity = _identity(actor)
    gate = LockGate()
    real_get_organization = organization_repository.get_organization

    def gated_get_organization(
        session: Session,
        org_id: UUID,
        *,
        for_update: bool = False,
    ) -> Organization | None:
        if not for_update or org_id != actor.organization_id:
            return real_get_organization(session, org_id, for_update=for_update)
        role = gate.before_locked_read(session)
        organization = real_get_organization(session, org_id, for_update=for_update)
        gate.after_locked_read(role)
        return organization

    monkeypatch.setattr(
        organization_repository,
        "get_organization",
        gated_get_organization,
    )

    def demote(
        worker_role: WorkerRole,
        membership_id: UUID,
        trace_id: str,
    ) -> object | ApiProblem:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, worker_role)
            try:
                return OrganizationService(session).update_membership_role(
                    identity=identity,
                    organization_id=actor.organization_id,
                    membership_id=membership_id,
                    requested_role=MembershipRole.MEMBER,
                    audit=_audit(trace_id),
                )
            except ApiProblem as problem:
                return problem

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            holder = executor.submit(
                demote,
                "holder",
                other_owner.membership_id,
                "req-concurrent-owner-other",
            )
            assert gate.holder_locked.wait(WAIT_SECONDS)
            waiter = executor.submit(
                demote,
                "waiter",
                actor.membership_id,
                "req-concurrent-owner-actor",
            )
            assert gate.waiter_entered.wait(WAIT_SECONDS)
            assert_waiting_on_lock(migrated_engine, gate)
            gate.release_holder.set()
            results = [
                holder.result(timeout=FUTURE_SECONDS),
                waiter.result(timeout=FUTURE_SECONDS),
            ]
        finally:
            gate.release_holder.set()

    assert sorted(
        result.code if isinstance(result, ApiProblem) else "success"
        for result in results
    ) == ["last_owner_required", "success"]
    with database.session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.org_id == actor.organization_id,
                Membership.role == MembershipRole.OWNER.value,
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.org_id == actor.organization_id,
                AuditLog.action == "membership.role_changed",
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.org_id == actor.organization_id,
                OutboxEvent.event_type == "membership.role_changed",
            )
        ) == 1


@pytest.mark.integration
def test_competing_acl_puts_leave_one_active_grant_and_complete_history(
    database: Database,
    migrated_engine: Engine,
) -> None:
    """Break caught: unlocked ACL replacement can violate active-principal uniqueness."""
    actor = seed_actor(database, MembershipRole.OWNER)
    identity = _identity(actor)
    project_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            Project(
                id=project_id,
                org_id=actor.organization_id,
                name="Concurrent ACL replacement",
            )
        )

    gate = LockGate()

    class GatedAuthorizationPolicy(AuthorizationPolicy):
        def __init__(self, session: Session) -> None:
            super().__init__(session)
            self._gate_session = session

        def find_project(
            self,
            identity: IdentityContextResponse,
            project_id: UUID,
            required: ProjectPermission,
            *,
            for_update: bool = False,
        ) -> Project | None:
            if not for_update:
                return super().find_project(
                    identity,
                    project_id,
                    required,
                    for_update=for_update,
                )
            role = gate.before_locked_read(self._gate_session)
            project = super().find_project(
                identity,
                project_id,
                required,
                for_update=for_update,
            )
            gate.after_locked_read(role)
            return project

    def set_acl(
        worker_role: WorkerRole,
        permission: ProjectPermission,
        trace_id: str,
    ) -> AclEntryResponse:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, worker_role)
            return ProjectAclService(
                session,
                policy=GatedAuthorizationPolicy(session),
            ).set_acl(
                identity=identity,
                project_id=project_id,
                principal_type="role",
                principal_id="member",
                permission=permission,
                audit=_audit(trace_id),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            holder = executor.submit(
                set_acl,
                "holder",
                ProjectPermission.READ,
                "req-concurrent-acl-read",
            )
            assert gate.holder_locked.wait(WAIT_SECONDS)
            waiter = executor.submit(
                set_acl,
                "waiter",
                ProjectPermission.WRITE,
                "req-concurrent-acl-write",
            )
            assert gate.waiter_entered.wait(WAIT_SECONDS)
            assert_waiting_on_lock(migrated_engine, gate)
            gate.release_holder.set()
            results = [
                holder.result(timeout=FUTURE_SECONDS),
                waiter.result(timeout=FUTURE_SECONDS),
            ]
        finally:
            gate.release_holder.set()

    assert all(isinstance(result, AclEntryResponse) for result in results)
    with database.session_factory() as session:
        history = session.scalars(
            select(ResourceAclEntry).where(
                ResourceAclEntry.org_id == actor.organization_id,
                ResourceAclEntry.resource_id == project_id,
                ResourceAclEntry.principal_type == "role",
                ResourceAclEntry.principal_id == "member",
            )
        ).all()
        active = [entry for entry in history if entry.revoked_at is None]
        audits = session.scalars(
            select(AuditLog).where(
                AuditLog.resource_id == project_id,
                AuditLog.action == "project.acl_granted",
            )
        ).all()
        events = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == project_id,
                OutboxEvent.event_type == "project.acl_granted",
            )
        ).all()

    assert len(active) == 1
    assert len(history) == 2
    assert {entry.permission for entry in history} == {"read", "write"}
    assert active[0].permission in {"read", "write"}
    assert len(audits) == 2
    assert len(events) == 2
