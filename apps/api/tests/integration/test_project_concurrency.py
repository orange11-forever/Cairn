from __future__ import annotations

from _thread import LockType
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic, sleep
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import User
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem
from cairn_api.organizations.models import Membership, Organization
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects import repository
from cairn_api.projects.models import OutboxEvent, Task
from cairn_api.projects.schemas import TaskResponse
from cairn_api.projects.service import ProjectService
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

WAIT_SECONDS = 5.0
FUTURE_SECONDS = 10.0
POLL_SECONDS = 0.01
WorkerRole = Literal["holder", "waiter"]


def _audit(trace_id: str) -> RequestAuditContext:
    return RequestAuditContext(
        trace_id=trace_id,
        ip="198.51.100.7",
        user_agent="project-race-integration-test",
    )


@dataclass
class _LockGate:
    roles: dict[int, WorkerRole] = field(default_factory=dict[int, WorkerRole])
    backend_pids: dict[WorkerRole, int] = field(default_factory=dict[WorkerRole, int])
    holder_locked: Event = field(default_factory=Event)
    waiter_entered: Event = field(default_factory=Event)
    release_holder: Event = field(default_factory=Event)
    guard: LockType = field(default_factory=Lock)

    def register(self, session: Session, role: WorkerRole) -> None:
        with self.guard:
            self.roles[id(session)] = role

    def before_locked_read(self, session: Session) -> WorkerRole | None:
        with self.guard:
            role = self.roles.get(id(session))
        if role is None:
            return None
        backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(backend_pid, int)
        with self.guard:
            self.backend_pids[role] = backend_pid
        if role == "waiter":
            self.waiter_entered.set()
        return role

    def after_locked_read(self, role: WorkerRole | None) -> None:
        if role != "holder":
            return
        self.holder_locked.set()
        if not self.release_holder.wait(WAIT_SECONDS):
            raise AssertionError("holder was not released before the coordination deadline")

    def pid(self, role: WorkerRole) -> int:
        with self.guard:
            return self.backend_pids[role]


def _assert_waiting_on_lock(engine: Engine, gate: _LockGate) -> None:
    waiter_pid = gate.pid("waiter")
    holder_pid = gate.pid("holder")
    deadline = monotonic() + WAIT_SECONDS
    last_activity: dict[str, object] | None = None
    statement = text(
        """
        SELECT pg_blocking_pids(pid) AS blocking_pids,
               state,
               wait_event_type,
               wait_event
        FROM pg_stat_activity
        WHERE pid = :waiter_pid
        """
    )
    with engine.connect() as connection:
        while monotonic() < deadline:
            row = (
                connection.execute(
                    statement,
                    {"waiter_pid": waiter_pid},
                )
                .mappings()
                .one_or_none()
            )
            last_activity = dict(row) if row is not None else None
            blockers = cast(
                Sequence[int],
                () if row is None or row["blocking_pids"] is None else row["blocking_pids"],
            )
            if holder_pid in blockers:
                return
            sleep(POLL_SECONDS)
    raise AssertionError(
        "waiter backend did not block on holder backend: "
        f"holder_pid={holder_pid}, waiter_pid={waiter_pid}, activity={last_activity}"
    )


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
            membership=MembershipResponse(id=membership.id, role=membership.role),
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

    gate = _LockGate()
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
        holder = executor.submit(transition, "holder", "done", "req-race-transition-done")
        assert gate.holder_locked.wait(WAIT_SECONDS)
        waiter = executor.submit(
            transition,
            "waiter",
            "cancelled",
            "req-race-transition-cancelled",
        )
        assert gate.waiter_entered.wait(WAIT_SECONDS)
        try:
            _assert_waiting_on_lock(migrated_engine, gate)
        finally:
            gate.release_holder.set()
        holder_result = holder.result(timeout=FUTURE_SECONDS)
        waiter_result = waiter.result(timeout=FUTURE_SECONDS)

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
