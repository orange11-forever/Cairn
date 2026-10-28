from datetime import datetime
from types import MappingProxyType
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.models import User
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
from cairn_api.organizations.models import Organization
from cairn_api.projects import repository, structure_repository, task_repository
from cairn_api.projects.models import (
    Milestone,
    OutboxEvent,
    Project,
    ProjectStage,
    Task,
    TaskDependency,
)
from cairn_api.projects.schemas import (
    AssigneePage,
    AssigneeResponse,
    DependencyPage,
    DependencyResponse,
    ProjectPage,
    ProjectResponse,
    TaskPage,
    TaskResponse,
    TaskUpdateRequest,
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
        description: str | None = None,
        assignee_user_id: UUID | None = None,
        milestone_id: UUID | None = None,
        expected_project_revision: int | None = None,
        estimated_effort_minutes: int | None = None,
        remaining_effort_minutes: int | None = None,
        audit: RequestAuditContext,
    ) -> TaskResponse:
        with self._session.begin():
            return self._create_task_in_transaction(
                identity=identity,
                project_id=project_id,
                title=title,
                stage_id=stage_id,
                parent_task_id=parent_task_id,
                priority=priority,
                due_at=due_at,
                acceptance_criteria=acceptance_criteria,
                description=description,
                assignee_user_id=assignee_user_id,
                milestone_id=milestone_id,
                expected_project_revision=expected_project_revision,
                estimated_effort_minutes=estimated_effort_minutes,
                remaining_effort_minutes=remaining_effort_minutes,
                audit=audit,
            )

    def _create_task_in_transaction(
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
        description: str | None = None,
        assignee_user_id: UUID | None = None,
        milestone_id: UUID | None = None,
        expected_project_revision: int | None = None,
        estimated_effort_minutes: int | None = None,
        remaining_effort_minutes: int | None = None,
        audit: RequestAuditContext,
    ) -> TaskResponse:
        org_id = identity.organization.id
        project = self._locked_project(identity, project_id)
        self._check_project_revision(project, expected_project_revision)
        self._validate_grouping(identity, project_id, stage_id, milestone_id)
        if stage_id is not None:
            stage = repository.get_stage(
                self._session,
                org_id=org_id,
                project_id=project_id,
                stage_id=stage_id,
            )
            if stage is None:
                raise _not_found()
        if parent_task_id is not None:
            parent = repository.get_task(
                self._session,
                org_id=org_id,
                task_id=parent_task_id,
                project_id=project_id,
            )
            if parent is None:
                raise _not_found()
        self._validate_assignee(identity, project_id, assignee_user_id)
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
            description=description,
            assignee_user_id=assignee_user_id,
            milestone_id=milestone_id,
            estimated_effort_minutes=estimated_effort_minutes,
            remaining_effort_minutes=remaining_effort_minutes,
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
                "revision": task.revision,
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
        expected_revision: int | None = None,
        audit: RequestAuditContext,
    ) -> TaskResponse:
        with self._session.begin():
            return self._transition_task_in_transaction(
                identity=identity,
                task_id=task_id,
                requested_status=requested_status,
                expected_revision=expected_revision,
                audit=audit,
            )

    def _transition_task_in_transaction(
        self,
        *,
        identity: IdentityContextResponse,
        task_id: UUID,
        requested_status: str,
        expected_revision: int | None = None,
        audit: RequestAuditContext,
    ) -> TaskResponse:
        org_id = identity.organization.id
        task = self._locked_task(identity, task_id)
        self._check_revision(task, expected_revision)
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
                "revision": updated_task.revision,
            },
        )
        return TaskResponse.model_validate(updated_task)

    def add_dependency(
        self,
        *,
        identity: IdentityContextResponse,
        predecessor_task_id: UUID,
        successor_task_id: UUID,
        expected_revision: int | None = None,
        audit: RequestAuditContext,
    ) -> DependencyResponse:
        with self._session.begin():
            return self._add_dependency_in_transaction(
                identity=identity,
                predecessor_task_id=predecessor_task_id,
                successor_task_id=successor_task_id,
                expected_revision=expected_revision,
                audit=audit,
            )

    def _add_dependency_in_transaction(
        self,
        *,
        identity: IdentityContextResponse,
        predecessor_task_id: UUID,
        successor_task_id: UUID,
        expected_revision: int | None = None,
        audit: RequestAuditContext,
    ) -> DependencyResponse:
        org_id = identity.organization.id
        successor = self._locked_task(identity, successor_task_id)
        self._check_revision(successor, expected_revision)
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
        successor.revision += 1
        self._session.flush()
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
                "taskId": str(successor_task_id),
                "revision": successor.revision,
            },
        )
        return DependencyResponse.model_validate(dependency)

    def _lock_organization(self, identity: IdentityContextResponse) -> None:
        # Membership role changes use this same organization lock first. This also
        # prevents opposite assignment targets in separate projects inverting locks.
        current = self._session.scalar(
            select(Organization.id)
            .where(Organization.id == identity.organization.id)
            .with_for_update(key_share=True)
        )
        if current is None:
            raise _not_found()

    def _require_active_actor(self, identity: IdentityContextResponse) -> None:
        current = self._session.scalar(
            select(User.id)
            .where(User.id == identity.user.id, User.is_active.is_(True))
            .with_for_update(read=True, of=User)
        )
        if current is None:
            raise _not_found()

    def _locked_task(self, identity: IdentityContextResponse, task_id: UUID) -> Task:
        # Discover project without locking Task, then consistently lock Project -> Task.
        task = repository.get_task(self._session, org_id=identity.organization.id, task_id=task_id)
        if task is None:
            raise _not_found()
        project_id = task.project_id
        self._locked_project(identity, project_id)
        task = repository.get_task(
            self._session, org_id=identity.organization.id, task_id=task_id, for_update=True
        )
        if task is None or task.project_id != project_id:
            raise _not_found()
        return task

    def _locked_project(self, identity: IdentityContextResponse, project_id: UUID) -> Project:
        self._lock_organization(identity)
        project = self._policy.require_project(
            identity, project_id, ProjectPermission.WRITE, for_update=True
        )
        # A discovery read in this Session may have cached a pre-lock version.
        self._session.refresh(project)
        self._require_active_actor(identity)
        return project

    @staticmethod
    def _check_project_revision(project: Project, expected_revision: int | None) -> None:
        if expected_revision is not None and project.revision != expected_revision:
            raise ApiProblem(
                status_code=409,
                code="revision_conflict",
                message="项目已被更新，请重新读取最新版本",
            )

    def _validate_grouping(
        self,
        identity: IdentityContextResponse,
        project_id: UUID,
        stage_id: UUID | None,
        milestone_id: UUID | None,
    ) -> None:
        org_id = identity.organization.id
        if stage_id is not None:
            stage = structure_repository.get_stage(self._session, org_id, project_id, stage_id)
            if stage is None:
                raise _not_found()
            self._require_active_structure(stage)
        if milestone_id is not None:
            milestone = structure_repository.get_milestone(
                self._session, org_id, project_id, milestone_id
            )
            if milestone is None:
                raise _not_found()
            self._require_active_structure(milestone)
            if milestone.stage_id != stage_id:
                raise ApiProblem(
                    status_code=422,
                    code="invalid_grouping",
                    message="任务阶段必须与里程碑所属阶段一致",
                )

    @staticmethod
    def _require_active_structure(row: ProjectStage | Milestone) -> None:
        if row.archived:
            raise ApiProblem(
                status_code=409,
                code="structure_archived",
                message="阶段已归档，请先恢复阶段后再操作"
                if isinstance(row, ProjectStage)
                else "里程碑已归档，请先恢复里程碑后再操作",
            )

    @staticmethod
    def _check_revision(
        task: Task | ProjectStage | Milestone, expected_revision: int | None
    ) -> None:
        if expected_revision is not None and task.revision != expected_revision:
            raise ApiProblem(
                status_code=409,
                code="revision_conflict",
                message="任务已被更新，请重新读取最新版本",
            )

    def _validate_assignee(
        self, identity: IdentityContextResponse, project_id: UUID, user_id: UUID | None
    ) -> None:
        if user_id is None:
            return
        from cairn_api.organizations.models import Membership

        member = self._session.scalar(
            task_repository.member_statement(identity.organization.id, project_id)
            .where(Membership.user_id == user_id)
            .with_for_update(of=Membership)
        )
        active = (
            self._session.scalar(
                select(User.id)
                .where(User.id == user_id, User.is_active.is_(True))
                .with_for_update(read=True, of=User)
            )
            if member is not None
            else None
        )
        if member is None or active is None:
            raise ApiProblem(
                status_code=422,
                code="invalid_assignee",
                message="负责人必须是当前组织启用且可访问项目的成员",
            )

    def get_task(self, *, identity: IdentityContextResponse, task_id: UUID) -> TaskResponse:
        task = repository.get_task(self._session, org_id=identity.organization.id, task_id=task_id)
        if task is None:
            raise _not_found()
        self._policy.require_project(identity, task.project_id, ProjectPermission.READ)
        return TaskResponse.model_validate(task)

    def update_task(
        self,
        *,
        identity: IdentityContextResponse,
        task_id: UUID,
        payload: TaskUpdateRequest,
        audit: RequestAuditContext,
    ) -> TaskResponse:
        with self._session.begin():
            return self._update_task_in_transaction(
                identity=identity, task_id=task_id, payload=payload, audit=audit
            )

    def _update_task_in_transaction(
        self,
        *,
        identity: IdentityContextResponse,
        task_id: UUID,
        payload: TaskUpdateRequest,
        audit: RequestAuditContext,
    ) -> TaskResponse:
        task = self._locked_task(identity, task_id)
        self._check_revision(task, payload.expected_revision)
        project = self._session.get(Project, task.project_id)
        assert project is not None
        self._check_project_revision(project, payload.expected_project_revision)
        changes = payload.model_dump(
            exclude_unset=True, exclude={"expected_revision", "expected_project_revision"}
        )
        if changes.keys() & {"stage_id", "milestone_id"}:
            self._validate_grouping(
                identity,
                task.project_id,
                changes.get("stage_id", task.stage_id),
                changes.get("milestone_id", task.milestone_id),
            )
        if "assignee_user_id" in changes:
            self._validate_assignee(identity, task.project_id, payload.assignee_user_id)
        for field, value in changes.items():
            setattr(task, field, value)
        task.revision += 1
        self._session.flush()
        self._audit(
            identity=identity,
            audit=audit,
            action="task.updated",
            resource_type="task",
            resource_id=task.id,
        )
        self._outbox(
            org_id=identity.organization.id,
            event_type="task.updated",
            project_id=task.project_id,
            payload={
                "projectId": str(task.project_id),
                "taskId": str(task.id),
                "revision": task.revision,
            },
        )
        return TaskResponse.model_validate(task)

    def list_assignees(
        self, *, identity: IdentityContextResponse, project_id: UUID, cursor: str | None, limit: int
    ) -> AssigneePage:
        _validate_limit(limit)
        self._policy.require_project(identity, project_id, ProjectPermission.READ)
        members, next_cursor = task_repository.list_assignees(
            self._session,
            org_id=identity.organization.id,
            project_id=project_id,
            requester_id=identity.user.id,
            cursor=cursor,
            limit=limit,
        )
        return AssigneePage(
            items=[
                AssigneeResponse(user_id=m.user_id, display_name=u.display_name, role=m.role)
                for m, u in members
            ],
            next_cursor=next_cursor,
        )

    def list_dependencies(
        self, *, identity: IdentityContextResponse, task_id: UUID, cursor: str | None, limit: int
    ) -> DependencyPage:
        _validate_limit(limit)
        task = self.get_task(identity=identity, task_id=task_id)
        self._policy.require_project(
            identity, task.project_id, ProjectPermission.READ, for_update=True
        )
        rows, next_cursor = task_repository.list_dependencies(
            self._session,
            org_id=identity.organization.id,
            task_id=task_id,
            cursor=cursor,
            limit=limit,
        )
        return DependencyPage(
            items=[DependencyResponse.model_validate(row) for row in rows], next_cursor=next_cursor
        )

    def delete_dependency(
        self,
        *,
        identity: IdentityContextResponse,
        task_id: UUID,
        dependency_id: UUID,
        expected_revision: int,
        audit: RequestAuditContext,
    ) -> None:
        with self._session.begin():
            return self._delete_dependency_in_transaction(
                identity=identity,
                task_id=task_id,
                dependency_id=dependency_id,
                expected_revision=expected_revision,
                audit=audit,
            )

    def _delete_dependency_in_transaction(
        self,
        *,
        identity: IdentityContextResponse,
        task_id: UUID,
        dependency_id: UUID,
        expected_revision: int,
        audit: RequestAuditContext,
    ) -> None:
        task = self._locked_task(identity, task_id)
        self._check_revision(task, expected_revision)
        edge = self._session.scalar(
            select(TaskDependency).where(
                TaskDependency.id == dependency_id,
                TaskDependency.org_id == identity.organization.id,
                TaskDependency.project_id == task.project_id,
                TaskDependency.successor_task_id == task.id,
            )
        )
        if edge is None:
            raise _not_found()
        self._session.delete(edge)
        task.revision += 1
        self._session.flush()
        self._audit(
            identity=identity,
            audit=audit,
            action="task.dependency_removed",
            resource_type="task_dependency",
            resource_id=edge.id,
        )
        self._outbox(
            org_id=identity.organization.id,
            event_type="task.dependency_removed",
            project_id=task.project_id,
            payload={
                "projectId": str(task.project_id),
                "taskId": str(task.id),
                "dependencyId": str(edge.id),
                "predecessorTaskId": str(edge.predecessor_task_id),
                "successorTaskId": str(task.id),
                "revision": task.revision,
            },
        )

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
        if event_type != "project.created":
            self._bump_project(project_id)
        self._session.add(
            OutboxEvent(
                org_id=org_id,
                event_type=event_type,
                aggregate_type="project",
                aggregate_id=project_id,
                payload=payload,
            )
        )

    def _bump_project(self, project_id: UUID) -> None:
        # All mutation callers already hold the project's row lock. Keep this
        # increment beside the single business event, in the same transaction.
        project = self._session.get(Project, project_id)
        assert project is not None
        project.revision += 1


__all__ = ["ALLOWED_TASK_TRANSITIONS", "ProjectService"]
