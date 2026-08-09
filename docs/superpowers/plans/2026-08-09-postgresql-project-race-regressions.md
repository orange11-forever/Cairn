# PostgreSQL Project Race Regressions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic PostgreSQL 16 integration regressions for competing task transitions and concurrent dependency cycle closure, including exact audit/outbox atomicity assertions.

**Architecture:** Create one focused integration test module. Each race uses two `ProjectService` calls with independent SQLAlchemy Sessions, test-only repository wrappers to hold the winning transaction after its real locked read, and `pg_blocking_pids()` to prove the losing backend is waiting before the winner is released. No production code changes are expected.

**Tech Stack:** Python 3.12, pytest 8, SQLAlchemy 2, psycopg 3, PostgreSQL 16, `ThreadPoolExecutor`, `threading.Event`.

## Global Constraints

- Use the existing `CAIRN_TEST_DATABASE_URL` guard and migrated PostgreSQL integration fixtures.
- Do not use SQLite, mocks, or an in-memory database for the race assertions.
- Do not add production-only synchronization hooks or change the task state machine/dependency algorithm.
- Do not add concurrent HTTP-client, load, throughput, or soak coverage.
- Every Event wait, PostgreSQL catalog poll, and Future result must have an explicit timeout.
- Use PostgreSQL lock observation for synchronization; do not use an arbitrary fixed sleep to decide when to release a transaction.
- Assert final domain state plus exact audit and outbox deltas for both races.

## File Structure

- Create `apps/api/tests/integration/test_project_concurrency.py`: owns identity/domain setup helpers, the PostgreSQL lock gate and diagnostics, worker orchestration, and both concurrency regressions.
- Do not modify production files. Temporary local mutations used to prove RED must be restored before each GREEN run and must never be staged.

## Test Environment Setup

Create `/tmp/cairn-project-races.env` with `apply_patch` and these exact contents:

```dotenv
CAIRN_POSTGRES_PORT=55439
POSTGRES_DB=cairn_test
POSTGRES_USER=cairn
POSTGRES_PASSWORD=cairn-local-only
```

Start an isolated PostgreSQL 16 project:

```bash
docker compose --env-file /tmp/cairn-project-races.env -f deploy/compose/core.yml -p cairn-test-project-races up -d --wait postgres
```

Use this URL for focused integration commands:

```bash
CAIRN_TEST_DATABASE_URL=postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:55439/cairn_test
```

Always tear the project down after focused validation, including failure paths:

```bash
docker compose --env-file /tmp/cairn-project-races.env -f deploy/compose/core.yml -p cairn-test-project-races down --volumes --remove-orphans
```

---

### Task 1: Competing Task Transition Regression

**Files:**
- Create: `apps/api/tests/integration/test_project_concurrency.py`
- Temporarily mutate for RED only, then restore: `apps/api/src/cairn_api/projects/service.py:247-255`

**Interfaces:**
- Consumes: `Database.session_factory`, `ProjectService.create_project`, `ProjectService.create_task`, `ProjectService.transition_task`, `repository.get_task`, `AuditLog`, `OutboxEvent`, and the PostgreSQL functions `pg_backend_pid()` / `pg_blocking_pids(integer)`.
- Produces: `_LockGate`, `_assert_waiting_on_lock(...)`, `_seed_identity(...)`, `_create_project_with_tasks(...)`, `_audit(...)`, and `test_competing_task_transitions_serialize_with_single_side_effect(...)`; Task 2 reuses all helpers except the transition-specific wrapper.

- [ ] **Step 1: Create the shared setup and lock-observation helpers**

Create `apps/api/tests/integration/test_project_concurrency.py` with the imports and helper contracts below. Keep constants at module scope so both regressions share the same bounded timing policy.

```python
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
from cairn_api.projects.models import OutboxEvent, Project, Task, TaskDependency
from cairn_api.projects.schemas import DependencyResponse, TaskResponse
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
    roles: dict[int, WorkerRole] = field(default_factory=dict)
    backend_pids: dict[WorkerRole, int] = field(default_factory=dict)
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
            row = connection.execute(
                statement,
                {"waiter_pid": waiter_pid},
            ).mappings().one_or_none()
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
```

- [ ] **Step 2: Write the competing-transition test**

Add a `@pytest.mark.integration` test with this orchestration. The repository wrapper must call the real `get_task`; it gates only registered worker Sessions, the target task, and `for_update=True`.

```python
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
            select(func.count()).select_from(AuditLog).where(
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
```

- [ ] **Step 3: Prove RED with a controlled lock mutation**

Use `apply_patch` to change only the `transition_task()` call from:

```python
task = repository.get_task(
    self._session,
    org_id=org_id,
    task_id=task_id,
    for_update=True,
)
```

to the same call without `for_update=True`. Run:

```bash
CAIRN_TEST_DATABASE_URL=postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:55439/cairn_test uv run --package cairn-api pytest apps/api/tests/integration/test_project_concurrency.py::test_competing_task_transitions_serialize_with_single_side_effect -q -m integration
```

Expected: FAIL within five seconds because `holder_locked` is never signaled (or lock observation reports no blocker). This demonstrates that the regression detects removal of the real task-row lock.

- [ ] **Step 4: Restore production code and prove GREEN**

Use `apply_patch` to restore the exact `for_update=True` argument. Confirm no production diff remains:

```bash
git diff -- apps/api/src/cairn_api/projects/service.py
```

Expected: no output. Rerun the focused test command from Step 3.

Expected: `1 passed` with no timeout or deadlock.

- [ ] **Step 5: Run API static checks for the new test module**

```bash
uv run --package cairn-api ruff format apps/api/tests/integration/test_project_concurrency.py
uv run --package cairn-api ruff check apps/api/tests/integration/test_project_concurrency.py
uv run --package cairn-api pyright apps/api/tests/integration/test_project_concurrency.py
```

Expected: formatting completes, and both check commands exit 0. Resolve type narrowing with explicit assertions/casts; do not weaken project-wide type checking.

- [ ] **Step 6: Commit the transition regression**

```bash
git add apps/api/tests/integration/test_project_concurrency.py
git commit -m "test(api): cover concurrent task transitions"
```

Expected: the commit contains only the new integration test module; `service.py` is unchanged.

---

### Task 2: Concurrent Dependency Cycle-Closure Regression

**Files:**
- Modify: `apps/api/tests/integration/test_project_concurrency.py`
- Temporarily mutate for RED only, then restore: `apps/api/src/cairn_api/projects/service.py:324-330`

**Interfaces:**
- Consumes: `_LockGate`, `_assert_waiting_on_lock(...)`, `_seed_identity(...)`, `_create_project_with_tasks(...)`, `_audit(...)`, `ProjectService.add_dependency`, and `repository.get_project` from Task 1.
- Produces: `test_concurrent_dependency_additions_cannot_close_cycle(...)`; no production interfaces change.

- [ ] **Step 1: Add the disjoint-endpoint dependency race**

Append the following test. Seed edges are `B -> C` and `D -> A`; concurrent edges are `A -> B` and `C -> D`. The endpoint sets `{A, B}` and `{C, D}` are disjoint, so only the project row lock can serialize the two cycle decisions.

```python
@pytest.mark.integration
def test_concurrent_dependency_additions_cannot_close_cycle(
    database: Database,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
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

    gate = _LockGate()
    real_get_project = repository.get_project

    def gated_get_project(
        session: Session,
        *,
        org_id: UUID,
        project_id: UUID,
        for_update: bool = False,
    ) -> Project | None:
        if not for_update or project_id != target_project_id:
            return real_get_project(
                session,
                org_id=org_id,
                project_id=project_id,
                for_update=for_update,
            )
        role = gate.before_locked_read(session)
        project = real_get_project(
            session,
            org_id=org_id,
            project_id=project_id,
            for_update=for_update,
        )
        gate.after_locked_read(role)
        return project

    target_project_id = project_id
    monkeypatch.setattr(repository, "get_project", gated_get_project)

    def add_dependency(
        role: WorkerRole,
        predecessor_task_id: UUID,
        successor_task_id: UUID,
        trace_id: str,
    ) -> DependencyResponse | ApiProblem:
        with database.session_factory() as session:
            gate.register(session, role)
            try:
                return ProjectService(session).add_dependency(
                    identity=identity,
                    predecessor_task_id=predecessor_task_id,
                    successor_task_id=successor_task_id,
                    audit=_audit(trace_id),
                )
            except ApiProblem as problem:
                return problem

    with ThreadPoolExecutor(max_workers=2) as executor:
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
        try:
            _assert_waiting_on_lock(migrated_engine, gate)
        finally:
            gate.release_holder.set()
        holder_result = holder.result(timeout=FUTURE_SECONDS)
        waiter_result = waiter.result(timeout=FUTURE_SECONDS)

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
```

- [ ] **Step 2: Prove RED with a controlled project-lock mutation**

Use `apply_patch` to change only the `add_dependency()` owning-project read from:

```python
owning_project = repository.get_project(
    self._session,
    org_id=org_id,
    project_id=predecessor.project_id,
    for_update=True,
)
```

to the same call without `for_update=True`. Run:

```bash
CAIRN_TEST_DATABASE_URL=postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:55439/cairn_test uv run --package cairn-api pytest apps/api/tests/integration/test_project_concurrency.py::test_concurrent_dependency_additions_cannot_close_cycle -q -m integration
```

Expected: FAIL within five seconds because the holder gate is not reached (or no project-lock blocker is observed). This proves the four-task topology detects removal of project-level serialization rather than passing on endpoint-task locks.

- [ ] **Step 3: Restore production code and prove GREEN**

Use `apply_patch` to restore the exact `for_update=True` argument. Confirm:

```bash
git diff -- apps/api/src/cairn_api/projects/service.py
```

Expected: no output. Then run both regressions together:

```bash
CAIRN_TEST_DATABASE_URL=postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:55439/cairn_test uv run --package cairn-api pytest apps/api/tests/integration/test_project_concurrency.py -q -m integration
```

Expected: `2 passed`, with no timeout or deadlock.

- [ ] **Step 4: Run focused neighboring API regressions and static checks**

```bash
CAIRN_TEST_DATABASE_URL=postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:55439/cairn_test uv run --package cairn-api pytest apps/api/tests/integration/test_project_concurrency.py apps/api/tests/integration/test_projects_api.py apps/api/tests/test_project_service.py -q
pnpm lint:api
pnpm typecheck:api
```

Expected: all tests pass and both static-check commands exit 0.

- [ ] **Step 5: Commit the dependency regression**

```bash
git add apps/api/tests/integration/test_project_concurrency.py
git commit -m "test(api): cover concurrent dependency cycles"
```

Expected: the commit contains only the integration test change; no production file is staged.

---

### Task 3: Full Verification and Resource Cleanup

**Files:**
- Verify only; no files should change.

**Interfaces:**
- Consumes: both committed integration regressions from Tasks 1 and 2.
- Produces: final PostgreSQL 16, API, and repository-wide verification evidence plus a clean Docker/worktree state.

- [ ] **Step 1: Re-run the focused race module in the isolated PostgreSQL project**

```bash
CAIRN_TEST_DATABASE_URL=postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:55439/cairn_test uv run --package cairn-api pytest apps/api/tests/integration/test_project_concurrency.py -q -m integration
```

Expected: `2 passed`.

- [ ] **Step 2: Tear down and audit the focused PostgreSQL project**

```bash
docker compose --env-file /tmp/cairn-project-races.env -f deploy/compose/core.yml -p cairn-test-project-races down --volumes --remove-orphans
docker ps -a --filter label=com.docker.compose.project=cairn-test-project-races --format '{{.ID}}'
docker network ls --filter label=com.docker.compose.project=cairn-test-project-races --format '{{.ID}}'
docker volume ls --filter label=com.docker.compose.project=cairn-test-project-races --format '{{.Name}}'
```

Expected: teardown exits 0 and all three label-filtered audit commands print no resource IDs.

- [ ] **Step 3: Run the repository verification pipeline**

```bash
pnpm verify
```

Expected: exit 0, including PostgreSQL 16 integration tests, Ruff, Pyright, API build, Web checks, production verification, Chromium, and auth-proxy verification. The verification script must tear down its own isolated Compose project.

- [ ] **Step 4: Audit the final diff and status**

```bash
git diff --check HEAD~2..HEAD
git status --short --branch
git log -3 --oneline
```

Expected: `git diff --check` exits 0; the worktree is clean; the two test commits follow the design/plan documentation commits; no temporary production mutation remains.
