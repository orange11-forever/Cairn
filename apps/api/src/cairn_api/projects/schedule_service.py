from datetime import UTC, date, datetime
from uuid import UUID

from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.types import ProjectPermission
from cairn_api.projects.graph_service import ProjectGraphService
from cairn_api.projects.schedule_calculator import calculate_schedule
from cairn_api.projects.schedule_schemas import (
    ProjectCapacityUpdateRequest,
    ProjectScheduleResponse,
    ScheduleProjectInput,
    ScheduleTaskInput,
)
from cairn_api.projects.schemas import DependencyResponse, ProjectResponse

ASSUMPTIONS = [
    "所有产能集中到一个可执行任务，按依赖、优先级、创建时间和ID稳定串行排程；日内余量继续用于下一任务。",
    "每日产能是整个项目可投入的总人时，不是单个成员工时。只使用ISO周日历（周一=1），不包含节假日或成员差异。",
    "开始日期若非工作日则顺延。零剩余任务不改变实际状态；整日边界的零工作任务与前置结束日期相同。",
    "已完成任务按0剩余量处理；已取消任务排除工作量，但未完成任务的已取消前置不视为满足。",
    "最长依赖链仅给出忽略共享产能争用的工作日下界，不能代替串行资源排程完成日期。",
    "日期是当前输入下的可复算情景，不是承诺；未记录剩余量、产能不可用或阻塞未解除时不输出完成日期。",
]


class ProjectScheduleService(ProjectGraphService):
    def update_capacity(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        payload: ProjectCapacityUpdateRequest,
        audit: RequestAuditContext,
    ) -> ProjectResponse:
        with self._session.begin():
            project = self._locked_project(identity, project_id)
            self._check_project_revision(project, payload.expected_project_revision)
            project.daily_capacity_minutes = payload.daily_capacity_minutes
            project.working_weekdays = payload.working_weekdays
            self._audit(
                identity=identity,
                audit=audit,
                action="project.capacity_updated",
                resource_type="project",
                resource_id=project_id,
            )
            self._outbox(
                org_id=identity.organization.id,
                event_type="project.capacity_updated",
                project_id=project_id,
                payload={"projectId": str(project_id), "revision": project.revision + 1},
            )
            self._session.flush()
            return ProjectResponse.model_validate(project)

    def scenario(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        start_date: date,
    ) -> ProjectScheduleResponse:
        with self._session.begin():
            project = self._locked_read_project(identity, project_id)
            tasks, edges = self._tasks_and_dependencies(identity, project_id)
            inputs = [ScheduleTaskInput.model_validate(task) for task in tasks]
            calculation = calculate_schedule(
                tasks=inputs,
                edges=[(edge.predecessor_task_id, edge.successor_task_id) for edge in edges],
                capacity=project.daily_capacity_minutes,
                weekdays=project.working_weekdays,
                start=start_date,
            )
            return ProjectScheduleResponse(
                **calculation.model_dump(),
                project=ScheduleProjectInput.model_validate(project),
                readAt=datetime.now(UTC),
                startDate=start_date,
                tasks=inputs,
                dependencies=[DependencyResponse.model_validate(edge) for edge in edges],
                canWrite=self._policy.find_project(
                    identity, project_id, ProjectPermission.WRITE, for_update=True
                )
                is not None,
                assumptions=ASSUMPTIONS,
            )
