"""Real project locks prevent lost revisions across task mutation types."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem
from cairn_api.projects.models import OutboxEvent, Project, Task
from cairn_api.projects.schemas import TaskResponse, TaskUpdateRequest
from cairn_api.projects.service import ProjectService
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from .concurrency_helpers import (
    FUTURE_SECONDS,
    WAIT_SECONDS,
    LockGate,
    WorkerRole,
    assert_waiting_on_lock,
    install_race_session_deadlines,
)
from .test_project_concurrency import _audit, _create_project_with_tasks, _seed_identity

# pyright: reportPrivateUsage=false

pytestmark = pytest.mark.integration


def test_detail_and_status_serialize_one_revision_and_one_event(
    database: Database, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = _seed_identity(database)
    project_id, [task_id] = _create_project_with_tasks(database, identity, "Contended edit")
    gate = LockGate()
    real_lock_organization = ProjectService._lock_organization  # pyright: ignore[reportPrivateUsage]

    def gated_lock_organization(self: ProjectService, identity: IdentityContextResponse) -> None:
        gate.before_locked_read(self._session)  # pyright: ignore[reportPrivateUsage]
        real_lock_organization(self, identity)

    monkeypatch.setattr(ProjectService, "_lock_organization", gated_lock_organization)

    class GatedPolicy(AuthorizationPolicy):
        def __init__(self, session: Session) -> None:
            super().__init__(session)
            self.session = session

        def find_project(
            self,
            identity: IdentityContextResponse,
            project_id: UUID,
            required: ProjectPermission,
            *,
            for_update: bool = False,
        ) -> Project | None:
            if not for_update:
                return super().find_project(identity, project_id, required)
            role = gate.before_locked_read(self.session)
            project = super().find_project(identity, project_id, required, for_update=True)
            gate.after_locked_read(role)
            return project

    def write(role: WorkerRole) -> TaskResponse | ApiProblem:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, role)
            service = ProjectService(session, GatedPolicy(session))
            try:
                if role == "holder":
                    return service.update_task(
                        identity=identity,
                        task_id=task_id,
                        payload=TaskUpdateRequest.model_validate(
                            {"expectedRevision": 1, "title": "Committed edit"}
                        ),
                        audit=_audit("edit-holder"),
                    )
                return service.transition_task(
                    identity=identity,
                    task_id=task_id,
                    requested_status="todo",
                    expected_revision=1,
                    audit=_audit("status-waiter"),
                )
            except ApiProblem as problem:
                return problem

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            holder = executor.submit(write, "holder")
            assert gate.holder_locked.wait(WAIT_SECONDS)
            waiter = executor.submit(write, "waiter")
            assert gate.waiter_entered.wait(WAIT_SECONDS)
            assert_waiting_on_lock(migrated_engine, gate)
            gate.release_holder.set()
            committed = holder.result(FUTURE_SECONDS)
            rejected = waiter.result(FUTURE_SECONDS)
        finally:
            gate.release_holder.set()
    assert isinstance(committed, TaskResponse) and committed.revision == 2
    assert isinstance(rejected, ApiProblem) and rejected.code == "revision_conflict"
    with database.session_factory() as session:
        stored = session.get(Task, task_id)
        assert (
            stored
            and stored.title == "Committed edit"
            and stored.status == "backlog"
            and stored.revision == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.resource_id == task_id,
                    AuditLog.action.in_(("task.updated", "task.status_changed")),
                )
            )
            == 1
        )
        events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == project_id,
                    OutboxEvent.event_type.in_(("task.updated", "task.status_changed")),
                )
            )
        )
        assert len(events) == 1 and events[0].payload == {
            "projectId": str(project_id),
            "taskId": str(task_id),
            "revision": 2,
        }


@pytest.mark.parametrize(
    "loss,code",
    [
        ("actor_role", "not_found"),
        ("actor_disabled", "not_found"),
        ("target_disabled", "invalid_assignee"),
        ("target_read", "invalid_assignee"),
    ],
)
def test_waiting_edit_revalidates_actor_and_target_before_commit(
    database: Database, migrated_engine: Engine, loss: str, code: str
) -> None:
    from cairn_api.auth.models import User
    from cairn_api.authorization.models import ResourceAclEntry
    from cairn_api.organizations.models import Membership, Organization
    from sqlalchemy import update

    identity = _seed_identity(database)
    project_id, [task_id] = _create_project_with_tasks(database, identity, "Access race")
    with database.session_factory.begin() as session:
        target = User(display_name="Candidate", is_active=True)
        session.add(target)
        session.flush()
        target_id = target.id
        session.add(Membership(org_id=identity.organization.id, user_id=target_id, role="member"))
    gate = LockGate()

    class WaitingService(ProjectService):
        def _lock_organization(self, identity: IdentityContextResponse) -> None:
            gate.before_locked_read(self._session)
            super()._lock_organization(identity)

    def edit() -> ApiProblem | TaskResponse:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, "waiter")
            try:
                return WaitingService(session).update_task(
                    identity=identity,
                    task_id=task_id,
                    payload=TaskUpdateRequest.model_validate(
                        {
                            "expectedRevision": 1,
                            "title": "Denied edit",
                            "assigneeUserId": str(target_id),
                        }
                    ),
                    audit=_audit("denied-waiting-edit"),
                )
            except ApiProblem as problem:
                return problem

    with ThreadPoolExecutor(max_workers=1) as executor:
        with database.session_factory.begin() as holder:
            install_race_session_deadlines(holder)
            gate.register(holder, "holder")
            gate.before_locked_read(holder)
            holder.scalar(
                select(Organization.id)
                .where(Organization.id == identity.organization.id)
                .with_for_update(key_share=True)
            )
            holder.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
            pending = executor.submit(edit)
            assert gate.waiter_entered.wait(WAIT_SECONDS)
            assert_waiting_on_lock(migrated_engine, gate)
            if loss == "actor_role":
                holder.execute(
                    update(Membership)
                    .where(Membership.id == identity.membership.id)
                    .values(role="viewer")
                )
            elif loss == "actor_disabled":
                holder.execute(
                    update(User).where(User.id == identity.user.id).values(is_active=False)
                )
            elif loss == "target_disabled":
                holder.execute(update(User).where(User.id == target_id).values(is_active=False))
            else:
                from datetime import UTC, datetime

                holder.execute(
                    update(ResourceAclEntry)
                    .where(
                        ResourceAclEntry.resource_id == project_id,
                        ResourceAclEntry.principal_type == "org",
                    )
                    .values(
                        revoked_at=datetime.now(UTC),
                        revoked_by_type="user",
                        revoked_by_id=identity.user.id,
                    )
                )
        result = pending.result(FUTURE_SECONDS)
    assert isinstance(result, ApiProblem) and result.code == code
    with database.session_factory() as session:
        stored = session.get(Task, task_id)
        assert (
            stored
            and stored.title == "Access race"
            and stored.revision == 1
            and stored.assignee_user_id is None
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.trace_id == "denied-waiting-edit")
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "task.updated")
            )
            == 0
        )


def test_opposite_assignments_in_two_projects_serialize_and_finish(
    database: Database, migrated_engine: Engine
) -> None:
    from cairn_api.auth.models import User
    from cairn_api.auth.schemas import UserResponse
    from cairn_api.authorization.types import MembershipRole
    from cairn_api.organizations.models import Membership
    from cairn_api.organizations.schemas import MembershipResponse

    first = _seed_identity(database)
    with database.session_factory.begin() as session:
        user = User(display_name="Second owner", is_active=True)
        session.add(user)
        session.flush()
        membership = Membership(org_id=first.organization.id, user_id=user.id, role="owner")
        session.add(membership)
        session.flush()
        second = first.model_copy(
            update={
                "user": UserResponse(id=user.id, email=None, display_name=user.display_name),
                "membership": MembershipResponse(id=membership.id, role=MembershipRole.OWNER),
            }
        )
    project_a, [task_a] = _create_project_with_tasks(database, first, "Assign A")
    project_b, [task_b] = _create_project_with_tasks(database, second, "Assign B")
    gate = LockGate()

    class GatedService(ProjectService):
        def _lock_organization(self, identity: IdentityContextResponse) -> None:
            role = gate.before_locked_read(self._session)
            super()._lock_organization(identity)
            gate.after_locked_read(role)

    def assign(
        role: WorkerRole, identity: IdentityContextResponse, task_id: UUID, target: UUID
    ) -> TaskResponse:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, role)
            return GatedService(session).update_task(
                identity=identity,
                task_id=task_id,
                payload=TaskUpdateRequest.model_validate(
                    {"expectedRevision": 1, "assigneeUserId": str(target)}
                ),
                audit=_audit(f"opposite-{role}"),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            holder = executor.submit(assign, "holder", first, task_a, second.user.id)
            assert gate.holder_locked.wait(WAIT_SECONDS)
            waiter = executor.submit(assign, "waiter", second, task_b, first.user.id)
            assert gate.waiter_entered.wait(WAIT_SECONDS)
            assert_waiting_on_lock(migrated_engine, gate)
            gate.release_holder.set()
            results = [holder.result(FUTURE_SECONDS), waiter.result(FUTURE_SECONDS)]
        finally:
            gate.release_holder.set()
    assert [result.revision for result in results] == [2, 2]
    assert [result.assignee_user_id for result in results] == [second.user.id, first.user.id]
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "task.updated",
                    OutboxEvent.aggregate_id.in_((project_a, project_b)),
                )
            )
            == 2
        )


def test_dependency_read_waits_for_project_and_observes_committed_edge(
    database: Database, migrated_engine: Engine
) -> None:
    from cairn_api.projects.models import TaskDependency

    identity = _seed_identity(database)
    project_id, [predecessor_id, successor_id] = _create_project_with_tasks(
        database, identity, "Predecessor", "Successor"
    )
    gate = LockGate()

    class ReadPolicy(AuthorizationPolicy):
        def __init__(self, session: Session) -> None:
            super().__init__(session)
            self.session = session

        def find_project(
            self,
            identity: IdentityContextResponse,
            project_id: UUID,
            required: ProjectPermission,
            *,
            for_update: bool = False,
        ) -> Project | None:
            if for_update:
                gate.before_locked_read(self.session)
            return super().find_project(identity, project_id, required, for_update=for_update)

    def read():
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, "waiter")
            return ProjectService(session, ReadPolicy(session)).list_dependencies(
                identity=identity, task_id=successor_id, cursor=None, limit=50
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with database.session_factory.begin() as holder:
            install_race_session_deadlines(holder)
            gate.register(holder, "holder")
            gate.before_locked_read(holder)
            holder.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
            waiting = executor.submit(read)
            assert gate.waiter_entered.wait(WAIT_SECONDS)
            assert_waiting_on_lock(migrated_engine, gate)
            holder.add(
                TaskDependency(
                    org_id=identity.organization.id,
                    project_id=project_id,
                    predecessor_task_id=predecessor_id,
                    successor_task_id=successor_id,
                )
            )
        page = waiting.result(FUTURE_SECONDS)
    assert len(page.items) == 1 and page.items[0].predecessor_task_id == predecessor_id


def test_two_organizations_opposite_global_user_validation_locks_are_compatible(
    database: Database,
) -> None:
    from threading import Barrier

    from cairn_api.organizations.models import Membership

    first = _seed_identity(database)
    second = _seed_identity(database)
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Membership(org_id=first.organization.id, user_id=second.user.id, role="owner"),
                Membership(org_id=second.organization.id, user_id=first.user.id, role="owner"),
            ]
        )
    project_a, [task_a] = _create_project_with_tasks(database, first, "Cross-org A")
    project_b, [task_b] = _create_project_with_tasks(database, second, "Cross-org B")
    barrier = Barrier(2)

    class PausedAfterActorUser(ProjectService):
        def _require_active_actor(self, identity: IdentityContextResponse) -> None:
            super()._require_active_actor(identity)
            barrier.wait(timeout=WAIT_SECONDS)

    def assign(identity: IdentityContextResponse, task_id: UUID, target: UUID) -> TaskResponse:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            return PausedAfterActorUser(session).update_task(
                identity=identity,
                task_id=task_id,
                payload=TaskUpdateRequest.model_validate(
                    {"expectedRevision": 1, "assigneeUserId": str(target)}
                ),
                audit=_audit("cross-org-assignment"),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            one = executor.submit(assign, first, task_a, second.user.id)
            two = executor.submit(assign, second, task_b, first.user.id)
            results = [one.result(timeout=FUTURE_SECONDS), two.result(timeout=FUTURE_SECONDS)]
        finally:
            barrier.abort()
    assert [result.revision for result in results] == [2, 2]
    assert [result.assignee_user_id for result in results] == [second.user.id, first.user.id]
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "task.updated",
                    OutboxEvent.aggregate_id.in_((project_a, project_b)),
                )
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "task.updated", AuditLog.resource_id.in_((task_a, task_b))
                )
            )
            == 2
        )
