"""Real PostgreSQL lock contention rejects stale whole-project writes."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.session import Database
from cairn_api.errors import ApiProblem
from cairn_api.projects.models import Milestone, OutboxEvent, Project, ProjectStage
from cairn_api.projects.schemas import (
    MilestoneCreateRequest,
    MilestoneResponse,
    StageCreateRequest,
    StageResponse,
    TaskResponse,
)
from cairn_api.projects.structure_service import ProjectStructureService
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


@pytest.mark.parametrize("holder_operation", ["stage", "status"])
def test_structure_waiter_sees_committed_project_revision(
    database: Database,
    migrated_engine: Engine,
    holder_operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _seed_identity(database)
    project_id, [task_id] = _create_project_with_tasks(database, identity, "Contended structure")
    with database.session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        expected = project.revision
    gate = LockGate()
    original_lock = ProjectStructureService._lock_organization

    def gated_organization(
        self: ProjectStructureService, identity: IdentityContextResponse
    ) -> None:
        gate.before_locked_read(self._session)
        original_lock(self, identity)

    monkeypatch.setattr(ProjectStructureService, "_lock_organization", gated_organization)

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

    def write(role: WorkerRole) -> StageResponse | MilestoneResponse | TaskResponse | ApiProblem:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, role)
            service = ProjectStructureService(session, GatedPolicy(session))
            try:
                if role == "holder" and holder_operation == "status":
                    return service.transition_task(
                        identity=identity,
                        task_id=task_id,
                        requested_status="todo",
                        audit=_audit("structure-status-holder"),
                    )
                if role == "holder":
                    return service.create_stage(
                        identity=identity,
                        project_id=project_id,
                        payload=StageCreateRequest.model_validate(
                            {"name": "Design", "position": 0, "expectedProjectRevision": expected}
                        ),
                        audit=_audit("structure-holder"),
                    )
                return service.create_milestone(
                    identity=identity,
                    project_id=project_id,
                    payload=MilestoneCreateRequest.model_validate(
                        {"name": "Stale milestone", "expectedProjectRevision": expected}
                    ),
                    audit=_audit("structure-waiter"),
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
    assert isinstance(committed, StageResponse if holder_operation == "stage" else TaskResponse)
    assert (
        isinstance(rejected, ApiProblem)
        and rejected.status_code == 409
        and rejected.code == "revision_conflict"
    )
    with database.session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None and project.revision == expected + 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(Milestone)
                .where(Milestone.project_id == project_id)
            )
            == 0
        )
        assert session.scalar(
            select(func.count())
            .select_from(ProjectStage)
            .where(ProjectStage.project_id == project_id)
        ) == (1 if holder_operation == "stage" else 0)
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.aggregate_id == project_id)
            )
            == 3
        )


@pytest.mark.parametrize("waiter_operation", ["archive", "assign"])
def test_lifecycle_waiter_observes_committed_archive_under_project_lock(
    database: Database,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    waiter_operation: str,
) -> None:
    from cairn_api.projects.models import Task
    from cairn_api.projects.schemas import StageUpdateRequest
    from cairn_api.projects.service import ProjectService

    identity = _seed_identity(database)
    project_id, _ = _create_project_with_tasks(database, identity, "Archive race")
    with database.session_factory() as session:
        service = ProjectStructureService(session, AuthorizationPolicy(session))
        stage = service.create_stage(
            identity=identity,
            project_id=project_id,
            payload=StageCreateRequest(name="Race", position=0, expectedProjectRevision=2),
            audit=_audit("race-stage"),
        )
    gate = LockGate()
    original = ProjectService._locked_project

    def gated(self: ProjectService, identity: IdentityContextResponse, project_id: UUID) -> Project:
        role = gate.before_locked_read(self._session)
        project = original(self, identity, project_id)
        gate.after_locked_read(role)
        return project

    monkeypatch.setattr(ProjectService, "_locked_project", gated)

    def write(role: WorkerRole) -> StageResponse | TaskResponse | ApiProblem:
        with database.session_factory() as session:
            install_race_session_deadlines(session)
            gate.register(session, role)
            service = ProjectStructureService(session, AuthorizationPolicy(session))
            try:
                if role == "holder" or waiter_operation == "archive":
                    return service.update_stage(
                        identity=identity,
                        project_id=project_id,
                        stage_id=stage.id,
                        payload=StageUpdateRequest(
                            archived=True, expectedRevision=1, expectedProjectRevision=3
                        ),
                        audit=_audit(f"race-{role}"),
                    )
                return service.create_task(
                    identity=identity,
                    project_id=project_id,
                    title="Rejected",
                    stage_id=stage.id,
                    parent_task_id=None,
                    priority="medium",
                    due_at=None,
                    acceptance_criteria=None,
                    audit=_audit("race-assign"),
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
    assert isinstance(committed, StageResponse) and committed.archived is True
    assert isinstance(rejected, ApiProblem) and rejected.status_code == 409
    assert rejected.code == (
        "revision_conflict" if waiter_operation == "archive" else "structure_archived"
    )
    with database.session_factory() as session:
        project = session.get(Project, project_id)
        row = session.get(ProjectStage, stage.id)
        assert project is not None and project.revision == 4
        assert row is not None and row.archived and row.revision == 2
        assert (
            session.scalar(
                select(func.count()).select_from(Task).where(Task.project_id == project_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.aggregate_id == project_id,
                    OutboxEvent.event_type == "stage.archived",
                )
            )
            == 1
        )
