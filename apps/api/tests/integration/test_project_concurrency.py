from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import User
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem
from cairn_api.organizations.models import Membership, Organization
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects import repository
from cairn_api.projects.models import OutboxEvent, Project, Task, TaskDependency
from cairn_api.projects.schemas import DependencyResponse, TaskResponse
from cairn_api.projects.service import ProjectService
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from .concurrency_helpers import (
    FUTURE_SECONDS,
    LOCK_TIMEOUT_MILLISECONDS,
    STATEMENT_TIMEOUT_MILLISECONDS,
    WAIT_SECONDS,
    LockGate,
    WorkerRole,
    assert_waiting_on_lock,
    install_race_session_deadlines,
)


def _audit(trace_id: str) -> RequestAuditContext:
    return RequestAuditContext(
        trace_id=trace_id,
        ip="198.51.100.7",
        user_agent="project-race-integration-test",
    )


@pytest.mark.integration
def test_race_transaction_deadlines_are_active(database: Database) -> None:
    with database.session_factory() as session:
        install_race_session_deadlines(session)
        lock_timeout_ms, statement_timeout_ms = session.execute(
            text(
                """
                SELECT EXTRACT(
                           EPOCH FROM current_setting('lock_timeout')::interval
                       ) * 1000,
                       EXTRACT(
                           EPOCH FROM current_setting('statement_timeout')::interval
                       ) * 1000
                """
            )
        ).one()

    assert int(lock_timeout_ms) == LOCK_TIMEOUT_MILLISECONDS
    assert int(statement_timeout_ms) == STATEMENT_TIMEOUT_MILLISECONDS


def _seed_identity(database: Database) -> IdentityContextResponse:
    suffix = uuid4().hex
    with database.session_factory.begin() as session:
        organization = Organization(slug=f"race-{suffix}", name="Race Test Organization")
        user = User(
            email=f"race-{suffix}@example.test",
            normalized_email=f"race-{suffix}@example.test",
            display_name="Race Test User",
            password_hash="unused-in-service-test",
        )
        session.add_all((organization, user))
        session.flush()
        membership = Membership(
            org_id=organization.id,
            user_id=user.id,
            role="owner",
        )
        session.add(membership)
        session.flush()
        return IdentityContextResponse(
            user=UserResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
            ),
            organization=OrganizationResponse(
                id=organization.id,
                slug=organization.slug,
                name=organization.name,
            ),
            membership=MembershipResponse(
                id=membership.id,
                role=MembershipRole(membership.role),
            ),
            csrf_token="not-used-by-service-tests",
        )


def _create_project_with_tasks(
    database: Database,
    identity: IdentityContextResponse,
    *titles: str,
) -> tuple[UUID, list[UUID]]:
    with database.session_factory() as session:
        service = ProjectService(session)
        project = service.create_project(
            identity=identity,
            name=f"Race Project {uuid4().hex}",
            description="PostgreSQL concurrency regression",
            audit=_audit("req-race-project-created"),
        )
        tasks = [
            service.create_task(
                identity=identity,
                project_id=project.id,
                title=title,
                stage_id=None,
                parent_task_id=None,
                priority="medium",
                due_at=None,
                acceptance_criteria=None,
                audit=_audit(f"req-race-task-created-{index}"),
            )
            for index, title in enumerate(titles)
        ]
    return project.id, [task.id for task in tasks]


@pytest.mark.integration
def test_competing_task_transitions_serialize_with_single_side_effect(
    database: Database,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _seed_identity(database)
    project_id, [task_id] = _create_project_with_tasks(database, identity, "Contended Task")

    with database.session_factory() as session:
        service = ProjectService(session)
        service.transition_task(
            identity=identity,
            task_id=task_id,
            requested_status="todo",
            audit=_audit("req-race-transition-todo"),
        )
        service.transition_task(
            identity=identity,
            task_id=task_id,
            requested_status="in_progress",
            audit=_audit("req-race-transition-in-progress"),
        )

    with database.session_factory() as session:
        baseline_audits = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "task.status_changed",
                AuditLog.resource_id == task_id,
            )
        )
        baseline_events = len(
            [
                event
                for event in session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == "task.status_changed",
                        OutboxEvent.aggregate_id == project_id,
                    )
                )
                if event.payload.get("taskId") == str(task_id)
            ]
        )
    assert isinstance(baseline_audits, int)

    gate = LockGate()
    real_get_task = repository.get_task

    def gated_get_task(
        session: Session,
        *,
        org_id: UUID,
        task_id: UUID,
        for_update: bool = False,
    ) -> Task | None:
        if not for_update or task_id != target_task_id:
            return real_get_task(
                session,
                org_id=org_id,
                task_id=task_id,
                for_update=for_update,
            )
        role = gate.before_locked_read(session)
        task = real_get_task(
            session,
            org_id=org_id,
            task_id=task_id,
            for_update=for_update,
        )
        gate.after_locked_read(role)
        return task

    target_task_id = task_id
    monkeypatch.setattr(repository, "get_task", gated_get_task)

    def transition(
        role: WorkerRole,
        requested_status: str,
        trace_id: str,
    ) -> TaskResponse | ApiProblem:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, role)
            try:
                return ProjectService(session).transition_task(
                    identity=identity,
                    task_id=task_id,
                    requested_status=requested_status,
                    audit=_audit(trace_id),
                )
            except ApiProblem as problem:
                return problem

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            holder = executor.submit(transition, "holder", "done", "req-race-transition-done")
            assert gate.holder_locked.wait(WAIT_SECONDS)
            waiter = executor.submit(
                transition,
                "waiter",
                "cancelled",
                "req-race-transition-cancelled",
            )
            assert gate.waiter_entered.wait(WAIT_SECONDS)
            assert_waiting_on_lock(migrated_engine, gate)
            gate.release_holder.set()
            holder_result = holder.result(timeout=FUTURE_SECONDS)
            waiter_result = waiter.result(timeout=FUTURE_SECONDS)
        finally:
            gate.release_holder.set()

    assert isinstance(holder_result, TaskResponse)
    assert holder_result.status == "done"
    assert isinstance(waiter_result, ApiProblem)
    assert waiter_result.status_code == 409
    assert waiter_result.code == "invalid_state_transition"

    with database.session_factory() as session:
        stored_task = session.get(Task, task_id)
        audits = session.scalars(
            select(AuditLog).where(
                AuditLog.action == "task.status_changed",
                AuditLog.resource_id == task_id,
            )
        ).all()
        events = [
            event
            for event in session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "task.status_changed",
                    OutboxEvent.aggregate_id == project_id,
                )
            )
            if event.payload.get("taskId") == str(task_id)
        ]

    assert stored_task is not None and stored_task.status == "done"
    assert len(audits) == baseline_audits + 1
    assert len(events) == baseline_events + 1
    assert [audit.trace_id for audit in audits].count("req-race-transition-done") == 1
    assert "req-race-transition-cancelled" not in {audit.trace_id for audit in audits}
    committed_events = [event for event in events if event.payload.get("status") == "done"]
    assert len(committed_events) == 1


@pytest.mark.integration
def test_concurrent_dependency_additions_cannot_close_cycle(
    database: Database,
    migrated_engine: Engine,
) -> None:
    identity = _seed_identity(database)
    project_id, task_ids = _create_project_with_tasks(
        database,
        identity,
        "Task A",
        "Task B",
        "Task C",
        "Task D",
    )
    task_a, task_b, task_c, task_d = task_ids

    with database.session_factory() as session:
        service = ProjectService(session)
        service.add_dependency(
            identity=identity,
            predecessor_task_id=task_b,
            successor_task_id=task_c,
            audit=_audit("req-race-dependency-b-c"),
        )
        service.add_dependency(
            identity=identity,
            predecessor_task_id=task_d,
            successor_task_id=task_a,
            audit=_audit("req-race-dependency-d-a"),
        )

    with database.session_factory() as session:
        baseline_audits = session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.org_id == identity.organization.id,
                AuditLog.action == "task.dependency_added",
            )
        )
        baseline_events = session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.event_type == "task.dependency_added",
                OutboxEvent.aggregate_id == project_id,
            )
        )
    assert isinstance(baseline_audits, int)
    assert isinstance(baseline_events, int)

    gate = LockGate()
    target_project_id = project_id

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
            if not for_update or project_id != target_project_id:
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

    def add_dependency(
        role: WorkerRole,
        predecessor_task_id: UUID,
        successor_task_id: UUID,
        trace_id: str,
    ) -> DependencyResponse | ApiProblem:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, role)
            try:
                return ProjectService(
                    session,
                    policy=GatedAuthorizationPolicy(session),
                ).add_dependency(
                    identity=identity,
                    predecessor_task_id=predecessor_task_id,
                    successor_task_id=successor_task_id,
                    audit=_audit(trace_id),
                )
            except ApiProblem as problem:
                return problem

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            holder = executor.submit(
                add_dependency,
                "holder",
                task_a,
                task_b,
                "req-race-dependency-a-b",
            )
            assert gate.holder_locked.wait(WAIT_SECONDS)
            waiter = executor.submit(
                add_dependency,
                "waiter",
                task_c,
                task_d,
                "req-race-dependency-c-d",
            )
            assert gate.waiter_entered.wait(WAIT_SECONDS)
            assert_waiting_on_lock(migrated_engine, gate)
            gate.release_holder.set()
            holder_result = holder.result(timeout=FUTURE_SECONDS)
            waiter_result = waiter.result(timeout=FUTURE_SECONDS)
        finally:
            gate.release_holder.set()

    assert isinstance(holder_result, DependencyResponse)
    assert holder_result.predecessor_task_id == task_a
    assert holder_result.successor_task_id == task_b
    assert isinstance(waiter_result, ApiProblem)
    assert waiter_result.status_code == 409
    assert waiter_result.code == "dependency_cycle"

    with database.session_factory() as session:
        edges = set(
            session.execute(
                select(
                    TaskDependency.predecessor_task_id,
                    TaskDependency.successor_task_id,
                ).where(TaskDependency.project_id == project_id)
            ).tuples()
        )
        audits = session.scalars(
            select(AuditLog).where(
                AuditLog.org_id == identity.organization.id,
                AuditLog.action == "task.dependency_added",
            )
        ).all()
        events = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "task.dependency_added",
                OutboxEvent.aggregate_id == project_id,
            )
        ).all()

    assert edges == {(task_b, task_c), (task_d, task_a), (task_a, task_b)}
    assert len(audits) == baseline_audits + 1
    assert len(events) == baseline_events + 1
    committed_audits = [
        audit for audit in audits if audit.trace_id == "req-race-dependency-a-b"
    ]
    assert len(committed_audits) == 1
    assert committed_audits[0].resource_id == holder_result.id
    assert "req-race-dependency-c-d" not in {audit.trace_id for audit in audits}
    committed_events = [
        event
        for event in events
        if event.payload.get("dependencyId") == str(holder_result.id)
    ]
    assert len(committed_events) == 1
    assert committed_events[0].payload["predecessorTaskId"] == str(task_a)
    assert committed_events[0].payload["successorTaskId"] == str(task_b)
