import base64
import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, and_, exists, or_, select, update
from sqlalchemy.orm import Session

from cairn_api.projects.models import Project, ProjectStage, Task, TaskDependency


class InvalidCursorError(ValueError):
    """Raised when an opaque project pagination cursor cannot be decoded."""


def _encode_cursor(created_at: datetime, item_id: UUID) -> str:
    raw = json.dumps(
        {"createdAt": created_at.isoformat(), "id": str(item_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload: object = json.loads(decoded)
        if not isinstance(payload, dict):
            raise TypeError("cursor payload must be an object")
        typed_payload = cast(dict[str, object], payload)
        created_at_value = typed_payload.get("createdAt")
        item_id_value = typed_payload.get("id")
        if not isinstance(created_at_value, str) or not isinstance(item_id_value, str):
            raise TypeError("cursor fields must be strings")
        created_at = datetime.fromisoformat(created_at_value)
        item_id = UUID(item_id_value)
        if created_at.tzinfo is None:
            raise ValueError("cursor timestamp must include a timezone")
        return created_at, item_id
    except (TypeError, ValueError) as exc:
        raise InvalidCursorError("project pagination cursor is invalid") from exc


def _page[CursorModel: (Project, Task)](
    session: Session,
    statement: Select[tuple[CursorModel]],
    *,
    model: type[CursorModel],
    cursor: str | None,
    limit: int,
) -> tuple[list[CursorModel], str | None]:
    if cursor is not None:
        created_at, item_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                model.created_at > created_at,
                and_(model.created_at == created_at, model.id > item_id),
            )
        )
    statement = statement.order_by(model.created_at, model.id).limit(limit + 1)
    rows = list(session.scalars(statement).all())
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        _encode_cursor(items[-1].created_at, items[-1].id)
        if has_more and items
        else None
    )
    return items, next_cursor


def create_project(
    session: Session,
    *,
    org_id: UUID,
    name: str,
    description: str | None,
) -> Project:
    project = Project(org_id=org_id, name=name, description=description)
    session.add(project)
    session.flush()
    return project


def get_project(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    for_update: bool = False,
) -> Project | None:
    statement = select(Project).where(Project.org_id == org_id, Project.id == project_id)
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def list_projects(
    session: Session,
    *,
    org_id: UUID,
    cursor: str | None,
    limit: int,
) -> tuple[list[Project], str | None]:
    return _page(
        session,
        select(Project).where(Project.org_id == org_id),
        model=Project,
        cursor=cursor,
        limit=limit,
    )


def get_stage(
    session: Session,
    *,
    org_id: UUID,
    stage_id: UUID,
) -> ProjectStage | None:
    return session.scalar(
        select(ProjectStage).where(
            ProjectStage.org_id == org_id,
            ProjectStage.id == stage_id,
        )
    )


def create_task(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    title: str,
    stage_id: UUID | None,
    parent_task_id: UUID | None,
    priority: str,
    due_at: datetime | None,
    acceptance_criteria: str | None,
) -> Task:
    task = Task(
        org_id=org_id,
        project_id=project_id,
        title=title,
        stage_id=stage_id,
        parent_task_id=parent_task_id,
        priority=priority,
        due_at=due_at,
        acceptance_criteria=acceptance_criteria,
    )
    session.add(task)
    session.flush()
    return task


def get_task(
    session: Session,
    *,
    org_id: UUID,
    task_id: UUID,
    for_update: bool = False,
) -> Task | None:
    statement = select(Task).where(Task.org_id == org_id, Task.id == task_id)
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def list_project_tasks(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    cursor: str | None,
    limit: int,
) -> tuple[list[Task], str | None]:
    return _page(
        session,
        select(Task).where(Task.org_id == org_id, Task.project_id == project_id),
        model=Task,
        cursor=cursor,
        limit=limit,
    )


def set_task_status(
    session: Session,
    *,
    org_id: UUID,
    task_id: UUID,
    current_status: str,
    requested_status: str,
) -> Task | None:
    statement = (
        update(Task)
        .where(
            Task.org_id == org_id,
            Task.id == task_id,
            Task.status == current_status,
        )
        .values(status=requested_status)
        .returning(Task)
    )
    return session.scalars(statement).one_or_none()


def get_dependency(
    session: Session,
    *,
    org_id: UUID,
    predecessor_task_id: UUID,
    successor_task_id: UUID,
) -> TaskDependency | None:
    return session.scalar(
        select(TaskDependency).where(
            TaskDependency.org_id == org_id,
            TaskDependency.predecessor_task_id == predecessor_task_id,
            TaskDependency.successor_task_id == successor_task_id,
        )
    )


def dependency_path_exists(
    session: Session,
    *,
    org_id: UUID,
    start_task_id: UUID,
    target_task_id: UUID,
) -> bool:
    reachable = (
        select(TaskDependency.successor_task_id.label("task_id"))
        .where(
            TaskDependency.org_id == org_id,
            TaskDependency.predecessor_task_id == start_task_id,
        )
        .cte("reachable_dependencies", recursive=True)
    )
    reachable = reachable.union(
        select(TaskDependency.successor_task_id.label("task_id"))
        .join(reachable, TaskDependency.predecessor_task_id == reachable.c.task_id)
        .where(TaskDependency.org_id == org_id)
    )
    return bool(
        session.scalar(select(exists().where(reachable.c.task_id == target_task_id)))
    )


def create_dependency(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    predecessor_task_id: UUID,
    successor_task_id: UUID,
) -> TaskDependency:
    dependency = TaskDependency(
        org_id=org_id,
        project_id=project_id,
        predecessor_task_id=predecessor_task_id,
        successor_task_id=successor_task_id,
    )
    session.add(dependency)
    session.flush()
    return dependency


__all__ = [
    "InvalidCursorError",
    "create_dependency",
    "create_project",
    "create_task",
    "dependency_path_exists",
    "get_dependency",
    "get_project",
    "get_stage",
    "get_task",
    "list_project_tasks",
    "list_projects",
    "set_task_status",
]
