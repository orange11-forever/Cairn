from __future__ import annotations

import sys
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Thread, current_thread
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
    LockGate,
    WorkerRole,
    assert_waiting_on_lock,
    install_race_session_deadlines,
    shutdown_race_executor,
    terminate_race_backends,
    wait_for_race_event,
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


class CharacteristicWorkerFailure(RuntimeError):
    pass


@pytest.mark.integration
def test_gate_wait_directly_surfaces_completed_worker_failure() -> None:
    """Break caught: cleanup must not be what reveals a pre-gate worker failure."""
    failed_future: Future[None] = Future()
    failed_future.set_exception(
        CharacteristicWorkerFailure("direct pre-gate worker failure")
    )

    with pytest.raises(
        CharacteristicWorkerFailure,
        match="^direct pre-gate worker failure$",
    ):
        wait_for_race_event(
            Event(),
            [failed_future],
            awaited_condition="the direct test gate",
        )


@pytest.mark.integration
def test_bounded_cleanup_preserves_primary_exception_and_joins_worker() -> None:
    """Break caught: cleanup timeout must not override or leak a race worker."""
    cooperative_cancel = Event()
    cooperative_cancel_observed = Event()
    allow_cooperative_exit = Event()
    worker_started = Event()
    worker_finished = Event()
    force_cancel_called = Event()
    worker_threads: list[Thread] = []
    primary_exception = ValueError("observer failed")

    def wait_for_cancellation() -> None:
        worker_threads.append(current_thread())
        worker_started.set()
        cooperative_cancel.wait()
        cooperative_cancel_observed.set()
        allow_cooperative_exit.wait()
        worker_finished.set()

    def force_worker_cancellation() -> None:
        force_cancel_called.set()
        allow_cooperative_exit.set()
        raise RuntimeError("backend termination failed")

    executor: ThreadPoolExecutor | None = None
    future: Future[None] | None = None
    try:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(wait_for_cancellation)
        assert worker_started.wait(1.0)
        with pytest.raises(ValueError) as exc_info:
            try:
                raise primary_exception
            finally:
                shutdown_race_executor(
                    executor,
                    [future],
                    cancel_signal=cooperative_cancel,
                    force_cancel=force_worker_cancellation,
                    primary_exception=sys.exception(),
                    timeout=0.0,
                    force_timeout=1.0,
                )
    finally:
        cooperative_cancel.set()
        allow_cooperative_exit.set()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    assert cooperative_cancel.is_set()
    assert cooperative_cancel_observed.is_set()
    assert force_cancel_called.is_set()
    assert exc_info.value is primary_exception
    assert str(exc_info.value) == "observer failed"
    assert primary_exception.__notes__ == [
        "force cancellation failed: backend termination failed"
    ]
    assert worker_finished.is_set()
    assert future is not None
    assert future.done()
    assert all(not worker.is_alive() for worker in worker_threads)


@pytest.mark.integration
def test_cleanup_startup_timeout_releases_signals_and_joins_worker() -> None:
    """Break caught: startup timeout must enter protected executor cleanup."""
    allow_worker_start = Event()
    worker_started = Event()
    cooperative_cancel = Event()
    allow_cooperative_exit = Event()
    worker_threads: list[Thread] = []

    def delayed_worker() -> None:
        worker_threads.append(current_thread())
        allow_worker_start.wait()
        worker_started.set()
        cooperative_cancel.wait()
        allow_cooperative_exit.wait()

    executor: ThreadPoolExecutor | None = None
    future: Future[None] | None = None
    try:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(delayed_worker)
        with pytest.raises(AssertionError, match="worker did not start"):
            assert worker_started.wait(0.0), "worker did not start"
    finally:
        cooperative_cancel.set()
        allow_cooperative_exit.set()
        allow_worker_start.set()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    assert cooperative_cancel.is_set()
    assert allow_cooperative_exit.is_set()
    assert future is not None
    assert future.done()
    assert all(not worker.is_alive() for worker in worker_threads)


@pytest.mark.integration
def test_cleanup_submit_failure_releases_signals_and_joins_existing_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: submit failure must enter cleanup for an existing worker."""
    cooperative_cancel = Event()
    allow_cooperative_exit = Event()
    worker_threads: list[Thread] = []
    cleanup_entered = Event()
    executor: ThreadPoolExecutor | None = None
    future: Future[None] | None = None

    def wait_for_cancellation() -> None:
        worker_threads.append(current_thread())
        cooperative_cancel.wait()
        allow_cooperative_exit.wait()

    def fail_submit(*_args: object, **_kwargs: object) -> Future[None]:
        raise CharacteristicWorkerFailure("second submit failed")

    try:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(wait_for_cancellation)
        monkeypatch.setattr(executor, "submit", fail_submit)
        with pytest.raises(
            CharacteristicWorkerFailure,
            match="^second submit failed$",
        ):
            executor.submit(wait_for_cancellation)
    finally:
        cleanup_entered.set()
        cooperative_cancel.set()
        allow_cooperative_exit.set()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    assert cleanup_entered.is_set()
    assert cooperative_cancel.is_set()
    assert allow_cooperative_exit.is_set()
    assert future is not None
    assert future.done()
    assert all(not worker.is_alive() for worker in worker_threads)


@pytest.mark.integration
def test_owner_race_harness_surfaces_worker_failure_before_holder_gate(
    database: Database,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a pre-gate worker failure must not become a gate timeout."""

    def fail_before_holder_gate(*_args: object, **_kwargs: object) -> object:
        raise CharacteristicWorkerFailure("worker failed before holder gate")

    monkeypatch.setattr(
        OrganizationService,
        "update_membership_role",
        fail_before_holder_gate,
    )

    with pytest.raises(
        CharacteristicWorkerFailure,
        match="^worker failed before holder gate$",
    ):
        test_concurrent_owner_demotions_preserve_one_owner(
            database,
            migrated_engine,
            monkeypatch,
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

    executor = ThreadPoolExecutor(max_workers=2)
    futures: list[Future[object | ApiProblem]] = []
    try:
        holder = executor.submit(
            demote,
            "holder",
            other_owner.membership_id,
            "req-concurrent-owner-other",
        )
        futures.append(holder)
        wait_for_race_event(
            gate.holder_locked,
            futures,
            awaited_condition="the holder organization lock",
        )
        waiter = executor.submit(
            demote,
            "waiter",
            actor.membership_id,
            "req-concurrent-owner-actor",
        )
        futures.append(waiter)
        wait_for_race_event(
            gate.waiter_entered,
            futures,
            awaited_condition="the waiter organization lock attempt",
        )
        assert_waiting_on_lock(migrated_engine, gate, futures)
        gate.release_holder.set()
        results = [
            holder.result(timeout=FUTURE_SECONDS),
            waiter.result(timeout=FUTURE_SECONDS),
        ]
    finally:
        shutdown_race_executor(
            executor,
            futures,
            cancel_signal=gate.release_holder,
            force_cancel=lambda: terminate_race_backends(migrated_engine, gate),
            primary_exception=sys.exception(),
        )

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

    executor = ThreadPoolExecutor(max_workers=2)
    futures: list[Future[AclEntryResponse]] = []
    try:
        holder = executor.submit(
            set_acl,
            "holder",
            ProjectPermission.READ,
            "req-concurrent-acl-read",
        )
        futures.append(holder)
        wait_for_race_event(
            gate.holder_locked,
            futures,
            awaited_condition="the holder project lock",
        )
        waiter = executor.submit(
            set_acl,
            "waiter",
            ProjectPermission.WRITE,
            "req-concurrent-acl-write",
        )
        futures.append(waiter)
        wait_for_race_event(
            gate.waiter_entered,
            futures,
            awaited_condition="the waiter project lock attempt",
        )
        assert_waiting_on_lock(migrated_engine, gate, futures)
        gate.release_holder.set()
        results = [
            holder.result(timeout=FUTURE_SECONDS),
            waiter.result(timeout=FUTURE_SECONDS),
        ]
    finally:
        shutdown_race_executor(
            executor,
            futures,
            cancel_signal=gate.release_holder,
            force_cancel=lambda: terminate_race_backends(migrated_engine, gate),
            primary_exception=sys.exception(),
        )

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
