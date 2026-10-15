"""Create and edit project structure under the existing project write lock."""

from uuid import UUID

from sqlalchemy import exists, select

from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.projects import structure_repository as repository
from cairn_api.projects.models import Milestone, ProjectStage, Task
from cairn_api.projects.schemas import (
    MilestoneCreateRequest,
    MilestonePage,
    MilestoneResponse,
    MilestoneUpdateRequest,
    StageCreateRequest,
    StagePage,
    StageResponse,
    StageUpdateRequest,
)
from cairn_api.projects.service import ProjectService, _not_found, _validate_limit

# pyright: reportPrivateUsage=false


class ProjectStructureService(ProjectService):
    def list_stages(
        self, *, identity: IdentityContextResponse, project_id: UUID, cursor: str | None, limit: int
    ) -> StagePage:
        _validate_limit(limit)
        self._policy.require_project(identity, project_id, ProjectPermission.READ)
        rows, next_cursor = repository.list_stages(
            self._session, identity.organization.id, project_id, cursor, limit
        )
        return StagePage(
            items=[StageResponse.model_validate(row) for row in rows], next_cursor=next_cursor
        )

    def list_milestones(
        self, *, identity: IdentityContextResponse, project_id: UUID, cursor: str | None, limit: int
    ) -> MilestonePage:
        _validate_limit(limit)
        self._policy.require_project(identity, project_id, ProjectPermission.READ)
        rows, next_cursor = repository.list_milestones(
            self._session, identity.organization.id, project_id, cursor, limit
        )
        return MilestonePage(
            items=[MilestoneResponse.model_validate(row) for row in rows], next_cursor=next_cursor
        )

    def _record_structure(
        self,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        row: ProjectStage | Milestone,
        action: str,
    ) -> None:
        resource = "stage" if isinstance(row, ProjectStage) else "milestone"
        self._session.flush()
        self._audit(
            identity=identity,
            audit=audit,
            action=action,
            resource_type=resource,
            resource_id=row.id,
        )
        self._outbox(
            org_id=identity.organization.id,
            event_type=action,
            project_id=row.project_id,
            payload={
                "projectId": str(row.project_id),
                "resourceId": str(row.id),
                "revision": row.revision,
            },
        )

    def _change_lifecycle(
        self,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        row: ProjectStage | Milestone,
        archived: bool,
    ) -> None:
        # Revisions were checked under the project/member lock before this call.
        if row.archived == archived:
            return
        if archived:
            task_group = (
                Task.stage_id == row.id
                if isinstance(row, ProjectStage)
                else Task.milestone_id == row.id
            )
            occupied = self._session.scalar(
                select(
                    exists().where(
                        Task.org_id == row.org_id,
                        Task.project_id == row.project_id,
                        task_group,
                    )
                )
            )
            if isinstance(row, ProjectStage):
                occupied = occupied or self._session.scalar(
                    select(
                        exists().where(
                            Milestone.org_id == row.org_id,
                            Milestone.project_id == row.project_id,
                            Milestone.stage_id == row.id,
                            Milestone.archived.is_(False),
                        )
                    )
                )
            if occupied:
                raise ApiProblem(
                    status_code=409,
                    code="structure_in_use",
                    message=(
                        "请先解除所有任务关联，并归档活动里程碑，再归档阶段"
                        if isinstance(row, ProjectStage)
                        else "请先解除所有任务关联，再归档里程碑"
                    ),
                )
        elif isinstance(row, Milestone):
            self._validate_grouping(identity, row.project_id, row.stage_id, None)
        row.archived = archived
        row.revision += 1
        resource = "stage" if isinstance(row, ProjectStage) else "milestone"
        self._record_structure(
            identity, audit, row, f"{resource}.{'archived' if archived else 'restored'}"
        )

    def create_stage(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        payload: StageCreateRequest,
        audit: RequestAuditContext,
    ) -> StageResponse:
        with self._session.begin():
            project = self._locked_project(identity, project_id)
            self._check_project_revision(project, payload.expected_project_revision)
            row = ProjectStage(
                org_id=identity.organization.id,
                project_id=project_id,
                name=payload.name,
                position=payload.position,
            )
            self._session.add(row)
            self._record_structure(identity, audit, row, "stage.created")
        return StageResponse.model_validate(row)

    def update_stage(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        stage_id: UUID,
        payload: StageUpdateRequest,
        audit: RequestAuditContext,
    ) -> StageResponse:
        with self._session.begin():
            project = self._locked_project(identity, project_id)
            row = repository.get_stage(
                self._session, identity.organization.id, project_id, stage_id
            )
            if row is None:
                raise _not_found()
            self._check_project_revision(project, payload.expected_project_revision)
            self._check_revision(row, payload.expected_revision)
            if "archived" in payload.model_fields_set:
                self._change_lifecycle(identity, audit, row, payload.archived)
            else:
                self._require_active_structure(row)
                for field, value in payload.model_dump(
                    exclude_unset=True, exclude={"expected_revision", "expected_project_revision"}
                ).items():
                    setattr(row, field, value)
                row.revision += 1
                self._record_structure(identity, audit, row, "stage.updated")
        return StageResponse.model_validate(row)

    def create_milestone(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        payload: MilestoneCreateRequest,
        audit: RequestAuditContext,
    ) -> MilestoneResponse:
        with self._session.begin():
            project = self._locked_project(identity, project_id)
            self._check_project_revision(project, payload.expected_project_revision)
            self._validate_grouping(identity, project_id, payload.stage_id, None)
            row = Milestone(
                org_id=identity.organization.id,
                project_id=project_id,
                **payload.model_dump(exclude={"expected_project_revision"}),
            )
            self._session.add(row)
            self._record_structure(identity, audit, row, "milestone.created")
        return MilestoneResponse.model_validate(row)

    def update_milestone(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        milestone_id: UUID,
        payload: MilestoneUpdateRequest,
        audit: RequestAuditContext,
    ) -> MilestoneResponse:
        with self._session.begin():
            project = self._locked_project(identity, project_id)
            row = repository.get_milestone(
                self._session, identity.organization.id, project_id, milestone_id
            )
            if row is None:
                raise _not_found()
            self._check_project_revision(project, payload.expected_project_revision)
            self._check_revision(row, payload.expected_revision)
            if "archived" in payload.model_fields_set:
                self._change_lifecycle(identity, audit, row, payload.archived)
            else:
                self._require_active_structure(row)
                changes = payload.model_dump(
                    exclude_unset=True, exclude={"expected_revision", "expected_project_revision"}
                )
                if "stage_id" in changes:
                    self._validate_grouping(identity, project_id, payload.stage_id, None)
                    incompatible = self._session.scalar(
                        select(
                            exists().where(
                                Task.org_id == identity.organization.id,
                                Task.project_id == project_id,
                                Task.milestone_id == row.id,
                                Task.stage_id.is_distinct_from(payload.stage_id),
                            )
                        )
                    )
                    if incompatible:
                        raise ApiProblem(
                            status_code=409,
                            code="milestone_in_use",
                            message="请先调整绑定任务的归属，再修改里程碑阶段",
                        )
                for field, value in changes.items():
                    setattr(row, field, value)
                row.revision += 1
                self._record_structure(identity, audit, row, "milestone.updated")
        return MilestoneResponse.model_validate(row)
