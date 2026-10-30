from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.projects.graph_schemas import (
    GraphMilestone,
    GraphStage,
    GraphTask,
    ProjectTaskGraphResponse,
)
from cairn_api.projects.models import Milestone, Project, ProjectStage, Task, TaskDependency
from cairn_api.projects.schemas import DependencyResponse, ProjectResponse
from cairn_api.projects.service import ProjectService

MAX_GRAPH_TASKS = 1000
MAX_GRAPH_EDGES = 5000
MAX_GRAPH_STRUCTURES = 500


class ProjectGraphService(ProjectService):
    def read(
        self, *, identity: IdentityContextResponse, project_id: UUID
    ) -> ProjectTaskGraphResponse:
        # Every project/task/structure/dependency mutation uses this same lock
        # order. Keep the read complete and consistent, including ACL rechecks.
        with self._session.begin():
            project = self._locked_read_project(identity, project_id)
            tasks, edges = self._tasks_and_dependencies(identity, project_id)
            org_id = identity.organization.id
            stages = list(
                self._session.scalars(
                    select(ProjectStage)
                    .where(ProjectStage.org_id == org_id, ProjectStage.project_id == project_id)
                    .order_by(ProjectStage.position, ProjectStage.id)
                    .limit(MAX_GRAPH_STRUCTURES + 1)
                )
            )
            milestones = list(
                self._session.scalars(
                    select(Milestone)
                    .where(Milestone.org_id == org_id, Milestone.project_id == project_id)
                    .order_by(Milestone.created_at, Milestone.id)
                    .limit(MAX_GRAPH_STRUCTURES + 1)
                )
            )
            if len(stages) > MAX_GRAPH_STRUCTURES or len(milestones) > MAX_GRAPH_STRUCTURES:
                raise ApiProblem(
                    status_code=422,
                    code="project_graph_too_large",
                    message="项目超出节点图显示上限（1000个任务、5000条依赖、各500个阶段或里程碑），请使用任务列表。",
                )
            return ProjectTaskGraphResponse(
                project=ProjectResponse.model_validate(project),
                readAt=datetime.now(UTC),
                tasks=[GraphTask.model_validate(row) for row in tasks],
                dependencies=[DependencyResponse.model_validate(row) for row in edges],
                stages=[GraphStage.model_validate(row) for row in stages],
                milestones=[GraphMilestone.model_validate(row) for row in milestones],
            )

    def _locked_read_project(self, identity: IdentityContextResponse, project_id: UUID) -> Project:
        self._lock_organization(identity)
        project = self._policy.require_project(
            identity, project_id, ProjectPermission.READ, for_update=True
        )
        self._require_active_actor(identity)
        return project

    def _tasks_and_dependencies(
        self, identity: IdentityContextResponse, project_id: UUID
    ) -> tuple[list[Task], list[TaskDependency]]:
        org_id = identity.organization.id
        tasks = list(
            self._session.scalars(
                select(Task)
                .where(Task.org_id == org_id, Task.project_id == project_id)
                .order_by(Task.created_at, Task.id)
                .limit(MAX_GRAPH_TASKS + 1)
            )
        )
        edges = list(
            self._session.scalars(
                select(TaskDependency)
                .where(TaskDependency.org_id == org_id, TaskDependency.project_id == project_id)
                .order_by(TaskDependency.id)
                .limit(MAX_GRAPH_EDGES + 1)
            )
        )
        if len(tasks) > MAX_GRAPH_TASKS or len(edges) > MAX_GRAPH_EDGES:
            raise ApiProblem(
                status_code=422,
                code="project_graph_too_large",
                message="项目超出完整计算上限（1000个任务、5000条依赖），请缩小项目范围。",
            )
        return tasks, edges
