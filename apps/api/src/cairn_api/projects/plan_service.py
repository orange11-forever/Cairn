import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select

from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.conversation_service import safe_knowledge_operation
from cairn_api.pagination import load_cursor_page, page_by_timestamp
from cairn_api.projects import repository
from cairn_api.projects.analysis_service import ProjectAnalysisService, analysis_changed
from cairn_api.projects.models import Milestone, ProjectStage
from cairn_api.projects.plan_models import ProjectPlanApplication
from cairn_api.projects.plan_schemas import (
    PlanSourceReference,
    ProjectPlanApplicationPage,
    ProjectPlanApplicationResponse,
    ProjectPlanApplyRequest,
)
from cairn_api.projects.service import _not_found
from cairn_api.projects.structure_service import ProjectStructureService

# pyright: reportPrivateUsage=false


class ProjectPlanService(ProjectAnalysisService):
    def _guard(self, project_id: UUID, *, write: bool = False) -> None:
        # Follow the project mutation order: organization -> project -> membership/session.
        ProjectStructureService(self._session)._lock_organization(self._identity)
        identity = self._authorize(project_id)
        if write:
            self._policy.require_project(
                identity, project_id, ProjectPermission.WRITE, for_update=True
            )

    def _records(self, project_id: UUID):
        return select(ProjectPlanApplication).where(
            ProjectPlanApplication.org_id == self._identity.organization.id,
            ProjectPlanApplication.project_id == project_id,
            ProjectPlanApplication.owner_id == self._identity.user.id,
        )

    @staticmethod
    def _response(row: ProjectPlanApplication) -> ProjectPlanApplicationResponse:
        return ProjectPlanApplicationResponse.model_validate(
            {
                "operationId": row.id,
                "projectId": row.project_id,
                "generatedAt": row.generated_at,
                "appliedAt": row.created_at,
                "plan": row.plan,
                "sources": row.sources,
                **row.entity_ids,
            }
        )

    @safe_knowledge_operation
    def get(self, project_id: UUID, operation_id: UUID) -> ProjectPlanApplicationResponse:
        with self._session.begin():
            self._guard(project_id)
            row = self._session.scalar(
                self._records(project_id).where(ProjectPlanApplication.id == operation_id)
            )
            if row is None:
                raise _not_found()
            return self._response(row)

    @safe_knowledge_operation
    def list_plans(
        self, project_id: UUID, cursor: str | None, limit: int
    ) -> ProjectPlanApplicationPage:
        with self._session.begin():
            self._guard(project_id)
            rows, next_cursor = load_cursor_page(
                lambda: page_by_timestamp(
                    self._session,
                    self._records(project_id),
                    timestamp_column=ProjectPlanApplication.created_at,
                    id_column=ProjectPlanApplication.id,
                    cursor=cursor,
                    limit=limit,
                    descending=True,
                )
            )
            return ProjectPlanApplicationPage(
                items=[self._response(row) for row in rows], nextCursor=next_cursor
            )

    @safe_knowledge_operation
    def apply(
        self, project_id: UUID, payload: ProjectPlanApplyRequest
    ) -> tuple[ProjectPlanApplicationResponse, bool]:
        preview = payload.preview
        digest = hashlib.sha256(
            json.dumps(
                preview.model_dump(mode="json", by_alias=True),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).digest()
        with self._session.begin():
            self._guard(project_id, write=True)
            existing = self._session.scalar(
                self._records(project_id).where(ProjectPlanApplication.id == payload.operation_id)
            )
            if existing is not None:
                if existing.request_digest != digest:
                    raise ApiProblem(
                        status_code=409,
                        code="plan_operation_conflict",
                        message="此提交编号已用于另一份规划，请重新确认",
                    )
                return self._response(existing), False
            if preview.project_id != project_id or preview.snapshot.project.id != project_id:
                raise analysis_changed()
            self._check_inputs(project_id, preview.snapshot, list(preview.citations))
            writer = ProjectStructureService(self._session)
            identity, audit = self._identity, self._audit
            org_id = identity.organization.id
            plan = preview.plan
            stage_ids = {item.id: uuid4() for item in plan.stages}
            milestone_ids = {item.id: uuid4() for item in plan.milestones}
            task_ids: dict[str, UUID] = {}
            position = max((stage.position for stage in preview.snapshot.stages), default=-1) + 1
            for index, item in enumerate(plan.stages):
                row = ProjectStage(
                    id=stage_ids[item.id],
                    org_id=org_id,
                    project_id=project_id,
                    name=item.name,
                    position=position + index,
                )
                self._session.add(row)
                writer._record_structure(identity, audit, row, "stage.created")
            for item in plan.milestones:
                milestone = Milestone(
                    id=milestone_ids[item.id],
                    org_id=org_id,
                    project_id=project_id,
                    stage_id=stage_ids[item.stage_id],
                    name=item.name,
                    acceptance_criteria=item.acceptance_criteria,
                )
                self._session.add(milestone)
                writer._record_structure(identity, audit, milestone, "milestone.created")
            for item in plan.tasks:
                task = repository.create_task(
                    self._session,
                    org_id=org_id,
                    project_id=project_id,
                    title=item.title,
                    description=item.description,
                    stage_id=stage_ids[item.stage_id],
                    milestone_id=milestone_ids[item.milestone_id] if item.milestone_id else None,
                    parent_task_id=None,
                    priority=item.priority,
                    due_at=None,
                    acceptance_criteria=item.acceptance_criteria,
                )
                task_ids[item.id] = task.id
                writer._audit(
                    identity=identity,
                    audit=audit,
                    action="task.created",
                    resource_type="task",
                    resource_id=task.id,
                )
                writer._outbox(
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
            for item in plan.tasks:
                for predecessor in item.depends_on:
                    edge = repository.create_dependency(
                        self._session,
                        org_id=org_id,
                        project_id=project_id,
                        predecessor_task_id=task_ids[predecessor],
                        successor_task_id=task_ids[item.id],
                    )
                    task = repository.get_task(
                        self._session, org_id=org_id, task_id=task_ids[item.id]
                    )
                    assert task is not None
                    task.revision += 1
                    writer._audit(
                        identity=identity,
                        audit=audit,
                        action="task.dependency_added",
                        resource_type="task_dependency",
                        resource_id=edge.id,
                    )
                    writer._outbox(
                        org_id=org_id,
                        event_type="task.dependency_added",
                        project_id=project_id,
                        payload={
                            "projectId": str(project_id),
                            "dependencyId": str(edge.id),
                            "predecessorTaskId": str(edge.predecessor_task_id),
                            "successorTaskId": str(edge.successor_task_id),
                            "taskId": str(task.id),
                            "revision": task.revision,
                        },
                    )
            writer._audit(
                identity=identity,
                audit=audit,
                action="project.plan_applied",
                resource_type="project",
                resource_id=project_id,
            )
            writer._outbox(
                org_id=org_id,
                event_type="project.plan_applied",
                project_id=project_id,
                payload={"projectId": str(project_id), "operationId": str(payload.operation_id)},
            )
            self._session.flush()
            saved = ProjectPlanApplication(
                id=payload.operation_id,
                org_id=org_id,
                project_id=project_id,
                owner_id=identity.user.id,
                request_digest=digest,
                plan=plan.model_dump(mode="json", by_alias=True),
                sources=[
                    PlanSourceReference(
                        id=c.id,
                        resourceId=c.resource_id,
                        resourceVersionId=c.resource_version_id,
                        chunkId=c.chunk_id,
                    ).model_dump(mode="json", by_alias=True)
                    for c in preview.citations
                ],
                entity_ids={
                    "stageIds": {key: str(value) for key, value in stage_ids.items()},
                    "milestoneIds": {key: str(value) for key, value in milestone_ids.items()},
                    "taskIds": {key: str(value) for key, value in task_ids.items()},
                },
                generated_at=preview.generated_at,
            )
            self._session.add(saved)
            self._session.flush()
            response = self._response(saved)
        return response, True
