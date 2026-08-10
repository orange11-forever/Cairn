from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.types import MembershipRole
from cairn_api.errors import ApiProblem
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects import repository
from cairn_api.projects.models import OutboxEvent, Project, Task, TaskDependency
from cairn_api.projects.service import ALLOWED_TASK_TRANSITIONS, ProjectService
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
AUDIT = RequestAuditContext(
    trace_id="req-project-service",
    ip="198.51.100.20",
    user_agent="project-service-test",
)


def _identity(org_id: UUID) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(id=uuid4(), email="member@example.com", display_name="Member"),
        organization=OrganizationResponse(id=org_id, slug=f"org-{org_id}", name="Organization"),
        membership=MembershipResponse(id=uuid4(), role=MembershipRole.OWNER),
        csrf_token="csrf-token",
    )


def _project(org_id: UUID, *, created_at: datetime = NOW) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id,
        name="Project Alpha",
        description="Project description",
        created_at=created_at,
        updated_at=created_at,
    )


def _task(
    org_id: UUID,
    project_id: UUID,
    *,
    status: str = "backlog",
    created_at: datetime = NOW,
) -> Task:
    return Task(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        stage_id=None,
        milestone_id=None,
        parent_task_id=None,
        title="Task Alpha",
        description=None,
        acceptance_criteria="Observable result",
        status=status,
        priority="high",
        due_at=NOW + timedelta(days=3),
        created_at=created_at,
        updated_at=created_at,
    )


def _added[Model](session: MagicMock, model_type: type[Model]) -> list[Model]:
    return [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], model_type)
    ]


def test_create_project_uses_identity_tenant_and_records_transactional_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    org_id = uuid4()
    identity = _identity(org_id)
    project = _project(org_id)
    captured_org_ids: list[UUID] = []

    def create_project(
        db: Session,
        *,
        org_id: UUID,
        name: str,
        description: str | None,
    ) -> Project:
        assert db is session
        assert name == "Project Alpha"
        assert description == "Project description"
        captured_org_ids.append(org_id)
        return project

    monkeypatch.setattr(repository, "create_project", create_project)

    result = ProjectService(session).create_project(
        identity=identity,
        name="Project Alpha",
        description="Project description",
        audit=AUDIT,
    )

    assert result.id == project.id
    assert captured_org_ids == [identity.organization.id]
    audit_logs = _added(session, AuditLog)
    assert len(audit_logs) == 1
    assert audit_logs[0].org_id == org_id
    assert audit_logs[0].action == "project.created"
    assert audit_logs[0].resource_id == project.id
    events = _added(session, OutboxEvent)
    assert len(events) == 1
    assert events[0].event_type == "project.created"
    assert events[0].aggregate_type == "project"
    assert events[0].aggregate_id == project.id
    assert events[0].payload == {"projectId": str(project.id)}


def test_project_reads_use_each_identity_tenant_and_hide_cross_tenant_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    org_one = uuid4()
    org_two = uuid4()
    project_one = _project(org_one)
    seen: list[tuple[str, UUID, object]] = []

    def list_projects(
        db: Session, *, org_id: UUID, cursor: str | None, limit: int
    ) -> tuple[list[Project], str | None]:
        assert db is session
        seen.append(("list", org_id, (cursor, limit)))
        return ([project_one], "next-project-page") if org_id == org_one else ([], None)

    def get_project(
        db: Session, *, org_id: UUID, project_id: UUID, for_update: bool = False
    ) -> Project | None:
        assert db is session
        seen.append(("get", org_id, (project_id, for_update)))
        return project_one if org_id == org_one and project_id == project_one.id else None

    monkeypatch.setattr(repository, "list_projects", list_projects)
    monkeypatch.setattr(repository, "get_project", get_project)
    service = ProjectService(session)

    page = service.list_projects(identity=_identity(org_one), cursor=None, limit=20)
    assert [item.id for item in page.items] == [project_one.id]
    assert page.next_cursor == "next-project-page"
    assert service.get_project(identity=_identity(org_one), project_id=project_one.id).id == project_one.id
    with pytest.raises(ApiProblem) as raised:
        service.get_project(identity=_identity(org_two), project_id=project_one.id)

    assert raised.value.code == "not_found"
    assert [entry[1] for entry in seen] == [org_one, org_one, org_two]


def test_create_task_uses_identity_tenant_and_preserves_acceptance_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    org_id = uuid4()
    identity = _identity(org_id)
    project = _project(org_id)
    task = _task(org_id, project.id)
    calls: list[tuple[str, UUID]] = []

    def get_project(
        db: Session, *, org_id: UUID, project_id: UUID, for_update: bool = False
    ) -> Project | None:
        assert db is session
        assert project_id == project.id
        assert for_update is False
        calls.append(("project", org_id))
        return project

    def create_task(db: Session, *, org_id: UUID, **values: object) -> Task:
        assert db is session
        assert values["project_id"] == project.id
        assert values["acceptance_criteria"] == "Observable result"
        calls.append(("create", org_id))
        return task

    monkeypatch.setattr(repository, "get_project", get_project)
    monkeypatch.setattr(repository, "create_task", create_task)

    result = ProjectService(session).create_task(
        identity=identity,
        project_id=project.id,
        title="Task Alpha",
        stage_id=None,
        parent_task_id=None,
        priority="high",
        due_at=task.due_at,
        acceptance_criteria="Observable result",
        audit=AUDIT,
    )

    assert result.acceptance_criteria == "Observable result"
    assert calls == [("project", org_id), ("create", org_id)]
    audit_logs = _added(session, AuditLog)
    assert [(log.action, log.resource_id) for log in audit_logs] == [("task.created", task.id)]
    events = _added(session, OutboxEvent)
    assert len(events) == 1
    assert events[0].aggregate_type == "project"
    assert events[0].aggregate_id == project.id
    assert events[0].payload == {
        "projectId": str(project.id),
        "taskId": str(task.id),
        "status": "backlog",
    }


def test_create_task_rejects_missing_project_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    org_id = uuid4()
    project_id = uuid4()
    create_task = MagicMock()
    monkeypatch.setattr(repository, "get_project", MagicMock(return_value=None))
    monkeypatch.setattr(repository, "create_task", create_task)

    with pytest.raises(ApiProblem) as raised:
        ProjectService(session).create_task(
            identity=_identity(org_id),
            project_id=project_id,
            title="Missing project task",
            stage_id=None,
            parent_task_id=None,
            priority="medium",
            due_at=None,
            acceptance_criteria=None,
            audit=AUDIT,
        )

    assert raised.value.code == "not_found"
    create_task.assert_not_called()
    assert _added(session, AuditLog) == []
    assert _added(session, OutboxEvent) == []


def test_transition_table_is_immutable_and_accepts_exactly_the_approved_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected: dict[str, frozenset[str]] = {
        "backlog": frozenset({"todo"}),
        "todo": frozenset({"in_progress"}),
        "in_progress": frozenset({"blocked", "done", "cancelled"}),
        "blocked": frozenset({"in_progress"}),
        "done": frozenset(),
        "cancelled": frozenset(),
    }
    assert isinstance(ALLOWED_TASK_TRANSITIONS, MappingProxyType)
    assert ALLOWED_TASK_TRANSITIONS == expected

    org_id = uuid4()
    project = _project(org_id)
    identity = _identity(org_id)
    all_statuses = tuple(expected)
    for current_status in all_statuses:
        for requested_status in all_statuses:
            session = MagicMock(spec=Session)
            task = _task(org_id, project.id, status=current_status)
            monkeypatch.setattr(repository, "get_task", MagicMock(return_value=task))

            def set_task_status(
                db: Session,
                *,
                org_id: UUID,
                task_id: UUID,
                current_status: str,
                requested_status: str,
                expected_session: Session = session,
                expected_task: Task = task,
            ) -> Task:
                assert db is expected_session
                assert org_id == identity.organization.id
                assert task_id == expected_task.id
                assert current_status == expected_task.status
                expected_task.status = requested_status
                return expected_task

            update = MagicMock(side_effect=set_task_status)
            monkeypatch.setattr(repository, "set_task_status", update)
            if requested_status in expected[current_status]:
                result = ProjectService(session).transition_task(
                    identity=identity,
                    task_id=task.id,
                    requested_status=requested_status,
                    audit=AUDIT,
                )
                assert result.status == requested_status
                assert len(_added(session, AuditLog)) == 1
                events = _added(session, OutboxEvent)
                assert len(events) == 1
                assert events[0].payload == {
                    "projectId": str(project.id),
                    "taskId": str(task.id),
                    "status": requested_status,
                }
            else:
                with pytest.raises(ApiProblem) as raised:
                    ProjectService(session).transition_task(
                        identity=identity,
                        task_id=task.id,
                        requested_status=requested_status,
                        audit=AUDIT,
                    )
                assert raised.value.code == "invalid_state_transition"
                update.assert_not_called()
                assert _added(session, AuditLog) == []
                assert _added(session, OutboxEvent) == []


def test_transition_hides_task_from_another_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    own_org = uuid4()
    other_org = uuid4()
    task_id = uuid4()
    seen_org_ids: list[UUID] = []

    def get_task(
        db: Session, *, org_id: UUID, task_id: UUID, for_update: bool = False
    ) -> Task | None:
        assert db is session
        assert for_update is True
        seen_org_ids.append(org_id)
        return None

    monkeypatch.setattr(repository, "get_task", get_task)
    update = MagicMock()
    monkeypatch.setattr(repository, "set_task_status", update)

    with pytest.raises(ApiProblem) as raised:
        ProjectService(session).transition_task(
            identity=_identity(other_org),
            task_id=task_id,
            requested_status="todo",
            audit=AUDIT,
        )

    assert raised.value.code == "not_found"
    assert seen_org_ids == [other_org]
    assert own_org not in seen_org_ids
    update.assert_not_called()


def test_add_dependency_accepts_same_project_acyclic_edge_and_records_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    org_id = uuid4()
    project = _project(org_id)
    predecessor = _task(org_id, project.id)
    successor = _task(org_id, project.id)
    dependency = TaskDependency(
        id=uuid4(),
        org_id=org_id,
        predecessor_task_id=predecessor.id,
        successor_task_id=successor.id,
        created_at=NOW,
    )
    seen: list[tuple[str, UUID, UUID, UUID | None]] = []
    created_values: dict[str, UUID] = {}

    def get_task(
        db: Session, *, org_id: UUID, task_id: UUID, for_update: bool = False
    ) -> Task | None:
        assert db is session
        assert for_update is True
        seen.append(("task", org_id, task_id, None))
        return predecessor if task_id == predecessor.id else successor

    def get_dependency(
        db: Session, *, org_id: UUID, predecessor_task_id: UUID, successor_task_id: UUID
    ) -> TaskDependency | None:
        assert db is session
        seen.append(("duplicate", org_id, predecessor_task_id, successor_task_id))
        return None

    def get_project(
        db: Session, *, org_id: UUID, project_id: UUID, for_update: bool = False
    ) -> Project | None:
        assert db is session
        assert for_update is True
        seen.append(("project", org_id, project_id, None))
        return project

    def dependency_path_exists(
        db: Session, *, org_id: UUID, start_task_id: UUID, target_task_id: UUID
    ) -> bool:
        assert db is session
        seen.append(("path", org_id, start_task_id, target_task_id))
        return False

    def create_dependency(db: Session, *, org_id: UUID, **values: UUID) -> TaskDependency:
        assert db is session
        created_values.update(values)
        seen.append(
            (
                "create",
                org_id,
                values["predecessor_task_id"],
                values["successor_task_id"],
            )
        )
        return dependency

    monkeypatch.setattr(repository, "get_task", get_task)
    monkeypatch.setattr(repository, "get_project", get_project)
    monkeypatch.setattr(repository, "get_dependency", get_dependency)
    monkeypatch.setattr(repository, "dependency_path_exists", dependency_path_exists)
    monkeypatch.setattr(repository, "create_dependency", create_dependency)

    result = ProjectService(session).add_dependency(
        identity=_identity(org_id),
        predecessor_task_id=predecessor.id,
        successor_task_id=successor.id,
        audit=AUDIT,
    )

    assert result.id == dependency.id
    assert all(entry[1] == org_id for entry in seen)
    assert ("path", org_id, successor.id, predecessor.id) in seen
    assert created_values.get("project_id") == project.id
    operation_order = [entry[0] for entry in seen]
    assert operation_order.index("project") < operation_order.index("path")
    audit_logs = _added(session, AuditLog)
    assert [(log.action, log.resource_id) for log in audit_logs] == [
        ("task.dependency_added", dependency.id)
    ]
    events = _added(session, OutboxEvent)
    assert len(events) == 1
    assert events[0].aggregate_type == "project"
    assert events[0].aggregate_id == project.id
    assert events[0].payload == {
        "projectId": str(project.id),
        "dependencyId": str(dependency.id),
        "predecessorTaskId": str(predecessor.id),
        "successorTaskId": str(successor.id),
    }


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("self", "invalid_dependency"),
        ("cross_project", "invalid_dependency"),
        ("duplicate", "dependency_exists"),
        ("cycle", "dependency_cycle"),
        ("cross_organization", "not_found"),
    ],
)
def test_add_dependency_rejects_invalid_edges_before_writes(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_code: str,
) -> None:
    session = MagicMock(spec=Session)
    org_id = uuid4()
    project = _project(org_id)
    predecessor = _task(org_id, project.id)
    successor_project_id = uuid4() if scenario == "cross_project" else project.id
    successor = _task(org_id, successor_project_id)
    successor_id = predecessor.id if scenario == "self" else successor.id

    def get_task(
        db: Session, *, org_id: UUID, task_id: UUID, for_update: bool = False
    ) -> Task | None:
        assert db is session
        assert org_id == identity.organization.id
        assert for_update is True
        if scenario == "cross_organization" and task_id == successor_id:
            return None
        return predecessor if task_id == predecessor.id else successor

    identity = _identity(org_id)
    monkeypatch.setattr(repository, "get_task", get_task)
    monkeypatch.setattr(
        repository,
        "get_dependency",
        MagicMock(return_value=TaskDependency() if scenario == "duplicate" else None),
    )
    monkeypatch.setattr(
        repository,
        "dependency_path_exists",
        MagicMock(return_value=scenario == "cycle"),
    )
    create = MagicMock()
    monkeypatch.setattr(repository, "create_dependency", create)

    with pytest.raises(ApiProblem) as raised:
        ProjectService(session).add_dependency(
            identity=identity,
            predecessor_task_id=predecessor.id,
            successor_task_id=successor_id,
            audit=AUDIT,
        )

    assert raised.value.code == expected_code
    create.assert_not_called()
    assert _added(session, AuditLog) == []
    assert _added(session, OutboxEvent) == []


def test_list_project_tasks_is_tenant_scoped_paginated_and_requires_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    org_id = uuid4()
    other_org_id = uuid4()
    project = _project(org_id)
    task = _task(org_id, project.id)
    seen: list[tuple[str, UUID, object]] = []

    def get_project(
        db: Session, *, org_id: UUID, project_id: UUID, for_update: bool = False
    ) -> Project | None:
        assert db is session
        seen.append(("project", org_id, project_id))
        return project if org_id == project.org_id and project_id == project.id else None

    def list_project_tasks(
        db: Session,
        *,
        org_id: UUID,
        project_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[Task], str | None]:
        assert db is session
        seen.append(("tasks", org_id, (project_id, cursor, limit)))
        return [task], "next-task-page"

    monkeypatch.setattr(repository, "get_project", get_project)
    monkeypatch.setattr(repository, "list_project_tasks", list_project_tasks)
    service = ProjectService(session)

    page = service.list_project_tasks(
        identity=_identity(org_id), project_id=project.id, cursor="cursor", limit=5
    )
    assert [item.id for item in page.items] == [task.id]
    assert page.next_cursor == "next-task-page"
    with pytest.raises(ApiProblem) as raised:
        service.list_project_tasks(
            identity=_identity(other_org_id), project_id=project.id, cursor=None, limit=5
        )

    assert raised.value.code == "not_found"
    assert [entry[1] for entry in seen] == [org_id, org_id, other_org_id]


def test_project_repository_uses_stable_tenant_cursor_pagination() -> None:
    session = MagicMock(spec=Session)
    org_id = uuid4()
    first = _project(org_id, created_at=NOW)
    second = _project(org_id, created_at=NOW)
    third = _project(org_id, created_at=NOW + timedelta(seconds=1))
    first.id = UUID("00000000-0000-4000-8000-000000000001")
    second.id = UUID("00000000-0000-4000-8000-000000000002")
    third.id = UUID("00000000-0000-4000-8000-000000000003")
    session.scalars.return_value.all.side_effect = [[first, second, third], [third]]

    items, next_cursor = repository.list_projects(
        session, org_id=org_id, cursor=None, limit=2
    )
    assert [item.id for item in items] == [first.id, second.id]
    assert next_cursor is not None
    first_statement = str(session.scalars.call_args_list[0].args[0])
    assert "projects.org_id" in first_statement
    assert "ORDER BY projects.created_at, projects.id" in first_statement

    remaining, final_cursor = repository.list_projects(
        session, org_id=org_id, cursor=next_cursor, limit=2
    )
    assert [item.id for item in remaining] == [third.id]
    assert final_cursor is None
    second_statement = str(session.scalars.call_args_list[1].args[0])
    assert "projects.org_id" in second_statement
    assert "projects.created_at >" in second_statement
    assert "projects.created_at =" in second_statement
    assert "projects.id >" in second_statement
    assert "ORDER BY projects.created_at, projects.id" in second_statement


def test_project_repository_reports_malformed_cursor_with_dedicated_error() -> None:
    session = MagicMock(spec=Session)

    # Break caught: cursor decoding leaks a generic ValueError that callers cannot distinguish.
    with pytest.raises(repository.InvalidCursorError):
        repository.list_projects(
            session,
            org_id=uuid4(),
            cursor="not-a-cursor",
            limit=20,
        )

    session.scalars.assert_not_called()


def test_task_repository_query_is_tenant_and_project_scoped_and_bounded() -> None:
    session = MagicMock(spec=Session)
    org_id = uuid4()
    project_id = uuid4()
    tasks = [
        _task(org_id, project_id, created_at=NOW + timedelta(seconds=index))
        for index in range(3)
    ]
    session.scalars.return_value.all.return_value = tasks

    items, next_cursor = repository.list_project_tasks(
        session,
        org_id=org_id,
        project_id=project_id,
        cursor=None,
        limit=2,
    )

    assert items == tasks[:2]
    assert next_cursor is not None
    statement = session.scalars.call_args.args[0]
    sql = str(statement)
    assert "tasks.org_id" in sql
    assert "tasks.project_id" in sql
    assert "ORDER BY tasks.created_at, tasks.id" in sql
    assert statement._limit_clause.value == 3
