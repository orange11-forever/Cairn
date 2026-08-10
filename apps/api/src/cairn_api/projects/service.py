from datetime import datetime
from types import MappingProxyType
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization import repository as acl_repository
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import (
    ActorType,
    PrincipalRef,
    PrincipalType,
    ProjectPermission,
    ResourceType,
)
from cairn_api.errors import ApiProblem
from cairn_api.projects import repository
from cairn_api.projects.models import OutboxEvent, Project
from cairn_api.projects.schemas import (
    DependencyResponse,
    ProjectPage,
    ProjectResponse,
    TaskPage,
    TaskResponse,
)

ALLOWED_TASK_TRANSITIONS = MappingProxyType(
    {
        "backlog": frozenset({"todo"}),
        "todo": frozenset({"in_progress"}),
        "in_progress": frozenset({"blocked", "done", "cancelled"}),
        "blocked": frozenset({"in_progress"}),
        "done": frozenset(),
        "cancelled": frozenset(),
    }
)


def _not_found() -> ApiProblem:
    return ApiProblem(status_code=404, code="not_found", message="资源不存在")


def _invalid_task_reference() -> ApiProblem:
    return ApiProblem(
        status_code=422,
        code="invalid_task_reference",
        message="任务引用不属于当前项目",
    )


def _invalid_state_transition() -> ApiProblem:
    return ApiProblem(
        status_code=409,
        code="invalid_state_transition",
        message="不允许该任务状态转换",
    )


def _invalid_dependency() -> ApiProblem:
    return ApiProblem(
        status_code=422,
        code="invalid_dependency",
        message="任务依赖必须位于同一项目且不能指向自身",
    )


def _dependency_exists() -> ApiProblem:
    return ApiProblem(status_code=409, code="dependency_exists", message="任务依赖已存在")


def _dependency_cycle() -> ApiProblem:
    return ApiProblem(status_code=409, code="dependency_cycle", message="任务依赖不能形成环")


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 100:
        raise ApiProblem(status_code=422, code="invalid_page_limit", message="分页大小无效")


class ProjectService:
    def __init__(
        self,
        session: Session,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._session = session
        self._policy = policy or AuthorizationPolicy(session)

    def create_project(
        self,
        *,
        identity: IdentityContextResponse,
        name: str,
        description: str | None,
        audit: RequestAuditContext,
    ) -> ProjectResponse:
        self._policy.require_project_creation(identity)
        org_id = identity.organization.id
        with self._session.begin():
            project = repository.create_project(
                self._session,
                org_id=org_id,
                name=name,
                description=description,
            )
            acl_repository.create_entry(
                self._session,
                org_id=org_id,
                resource_type=ResourceType.PROJECT,
                resource_id=project.id,
                principal=PrincipalRef(PrincipalType.ORG, str(org_id)),
                permission=ProjectPermission.READ,
                actor_type=ActorType.USER,
                actor_id=identity.user.id,
            )
            acl_repository.create_entry(
                self._session,
                org_id=org_id,
                resource_type=ResourceType.PROJECT,
                resource_id=project.id,
                principal=PrincipalRef(PrincipalType.USER, str(identity.user.id)),
                permission=ProjectPermission.MANAGE,
                actor_type=ActorType.USER,
                actor_id=identity.user.id,
            )
            self._audit(
                identity=identity,
                audit=audit,
                action="project.created",
                resource_type="project",
                resource_id=project.id,
            )
            self._outbox(
                org_id=org_id,
                event_type="project.created",
                project_id=project.id,
                payload={"projectId": str(project.id)},
            )
        return ProjectResponse.model_validate(project)

    def list_projects(
        self,
        *,
        identity: IdentityContextResponse,
        cursor: str | None,
        limit: int,
    ) -> ProjectPage:
        _validate_limit(limit)
        projects, next_cursor = repository.list_projects(
            self._session,
            org_id=identity.organization.id,
            access_filter=self._policy.project_filter(
                identity,
                ProjectPermission.READ,
                cast(ColumnElement[UUID], Project.id),
            ),
            cursor=cursor,
            limit=limit,
        )
        return ProjectPage(
            items=[ProjectResponse.model_validate(project) for project in projects],
            next_cursor=next_cursor,
        )

    def get_project(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
    ) -> ProjectResponse:
        project = self._policy.require_project(
            identity,
            project_id,
            ProjectPermission.READ,
        )
        return ProjectResponse.model_validate(project)

    def create_task(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        title: str,
        stage_id: UUID | None,
        parent_task_id: UUID | None,
        priority: str,
        due_at: datetime | None,
        acceptance_criteria: str | None,
        audit: RequestAuditContext,
    ) -> TaskResponse:
        org_id = identity.organization.id
        with self._session.begin():
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.WRITE,
                for_update=True,
            )
            if stage_id is not None:
                stage = repository.get_stage(self._session, org_id=org_id, stage_id=stage_id)
                if stage is None:
                    raise _not_found()
                if stage.project_id != project_id:
                    raise _invalid_task_reference()
            if parent_task_id is not None:
                parent = repository.get_task(
                    self._session,
                    org_id=org_id,
                    task_id=parent_task_id,
                )
                if parent is None:
                    raise _not_found()
                if parent.project_id != project_id:
                    raise _invalid_task_reference()
            task = repository.create_task(
                self._session,
                org_id=org_id,
                project_id=project_id,
                title=title,
                stage_id=stage_id,
                parent_task_id=parent_task_id,
                priority=priority,
                due_at=due_at,
                acceptance_criteria=acceptance_criteria,
            )
            self._audit(
                identity=identity,
                audit=audit,
                action="task.created",
                resource_type="task",
                resource_id=task.id,
            )
            self._outbox(
                org_id=org_id,
                event_type="task.created",
                project_id=project_id,
                payload={
                    "projectId": str(project_id),
                    "taskId": str(task.id),
                    "status": task.status,
                },
            )
        return TaskResponse.model_validate(task)

    def list_project_tasks(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> TaskPage:
        _validate_limit(limit)
        org_id = identity.organization.id
        self._policy.require_project(
            identity,
            project_id,
            ProjectPermission.READ,
        )
        tasks, next_cursor = repository.list_project_tasks(
            self._session,
            org_id=org_id,
            project_id=project_id,
            cursor=cursor,
            limit=limit,
        )
        return TaskPage(
            items=[TaskResponse.model_validate(task) for task in tasks],
            next_cursor=next_cursor,
        )

    def transition_task(
        self,
        *,
        identity: IdentityContextResponse,
        task_id: UUID,
        requested_status: str,
        audit: RequestAuditContext,
    ) -> TaskResponse:
        org_id = identity.organization.id
        with self._session.begin():
            task = repository.get_task(
                self._session,
                org_id=org_id,
                task_id=task_id,
                for_update=True,
            )
            if task is None:
                raise _not_found()
            self._policy.require_project(
                identity,
                task.project_id,
                ProjectPermission.WRITE,
                for_update=True,
            )
            if requested_status not in ALLOWED_TASK_TRANSITIONS.get(
                task.status,
                frozenset(),
            ):
                raise _invalid_state_transition()
            updated_task = repository.set_task_status(
                self._session,
                org_id=org_id,
                task_id=task_id,
                current_status=task.status,
                requested_status=requested_status,
            )
            if updated_task is None:
                raise _invalid_state_transition()
            self._audit(
                identity=identity,
                audit=audit,
                action="task.status_changed",
                resource_type="task",
                resource_id=updated_task.id,
            )
            self._outbox(
                org_id=org_id,
                event_type="task.status_changed",
                project_id=updated_task.project_id,
                payload={
                    "projectId": str(updated_task.project_id),
                    "taskId": str(updated_task.id),
                    "status": updated_task.status,
                },
            )
        return TaskResponse.model_validate(updated_task)

    def add_dependency(
        self,
        *,
        identity: IdentityContextResponse,
        predecessor_task_id: UUID,
        successor_task_id: UUID,
        audit: RequestAuditContext,
    ) -> DependencyResponse:
        org_id = identity.organization.id
        with self._session.begin():
            successor = repository.get_task(
                self._session,
                org_id=org_id,
                task_id=successor_task_id,
                for_update=True,
            )
            if successor is None:
                raise _not_found()
            self._policy.require_project(
                identity,
                successor.project_id,
                ProjectPermission.WRITE,
                for_update=True,
            )
            if predecessor_task_id == successor_task_id:
                raise _invalid_dependency()
            predecessor = repository.get_task(
                self._session,
                org_id=org_id,
                task_id=predecessor_task_id,
                project_id=successor.project_id,
                for_update=True,
            )
            if predecessor is None:
                raise _invalid_dependency()
            existing = repository.get_dependency(
                self._session,
                org_id=org_id,
                predecessor_task_id=predecessor_task_id,
                successor_task_id=successor_task_id,
            )
            if existing is not None:
                raise _dependency_exists()
            if repository.dependency_path_exists(
                self._session,
                org_id=org_id,
                start_task_id=successor_task_id,
                target_task_id=predecessor_task_id,
            ):
                raise _dependency_cycle()
            dependency = repository.create_dependency(
                self._session,
                org_id=org_id,
                project_id=successor.project_id,
                predecessor_task_id=predecessor_task_id,
                successor_task_id=successor_task_id,
            )
            self._audit(
                identity=identity,
                audit=audit,
                action="task.dependency_added",
                resource_type="task_dependency",
                resource_id=dependency.id,
            )
            self._outbox(
                org_id=org_id,
                event_type="task.dependency_added",
                project_id=successor.project_id,
                payload={
                    "projectId": str(predecessor.project_id),
                    "dependencyId": str(dependency.id),
                    "predecessorTaskId": str(predecessor_task_id),
                    "successorTaskId": str(successor_task_id),
                },
            )
        return DependencyResponse.model_validate(dependency)

    def _audit(
        self,
        *,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        action: str,
        resource_type: str,
        resource_id: UUID,
    ) -> None:
        add_audit_log(
            self._session,
            org_id=identity.organization.id,
            actor_type="user",
            actor_id=identity.user.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=audit.trace_id,
            ip=audit.ip,
            user_agent=audit.user_agent,
        )

    def _outbox(
        self,
        *,
        org_id: UUID,
        event_type: str,
        project_id: UUID,
        payload: dict[str, object],
    ) -> None:
        self._session.add(
            OutboxEvent(
                org_id=org_id,
                event_type=event_type,
                aggregate_type="project",
                aggregate_id=project_id,
                payload=payload,
            )
        )


__all__ = ["ALLOWED_TASK_TRANSITIONS", "ProjectService"]
