from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.pagination import InvalidCursorError, page_by_timestamp
from cairn_api.projects.models import Project, ProjectStage, Task, TaskDependency


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
    access_filter: ColumnElement[bool],
    cursor: str | None,
    limit: int,
) -> tuple[list[Project], str | None]:
    return page_by_timestamp(
        session,
        select(Project).where(Project.org_id == org_id, access_filter),
        timestamp_column=Project.created_at,
        id_column=Project.id,
        cursor=cursor,
        limit=limit,
    )


def get_stage(
    session: Session,
    *,
    org_id: UUID,
    project_id: UUID,
    stage_id: UUID,
) -> ProjectStage | None:
    return session.scalar(
        select(ProjectStage).where(
            ProjectStage.org_id == org_id,
            ProjectStage.project_id == project_id,
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
    project_id: UUID | None = None,
    for_update: bool = False,
) -> Task | None:
    statement = select(Task).where(Task.org_id == org_id, Task.id == task_id)
    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)
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
    return page_by_timestamp(
        session,
        select(Task).where(Task.org_id == org_id, Task.project_id == project_id),
        timestamp_column=Task.created_at,
        id_column=Task.id,
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
