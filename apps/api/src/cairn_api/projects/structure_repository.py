"""Scoped structure reads with resource-bound pagination cursors."""

import json
from typing import cast
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from cairn_api.pagination import InvalidCursorError, page_by_timestamp
from cairn_api.projects.models import Milestone, ProjectStage
from cairn_api.projects.task_repository import unwrap_cursor, wrap_cursor


def get_stage(
    session: Session, org_id: UUID, project_id: UUID, stage_id: UUID
) -> ProjectStage | None:
    return session.scalar(
        select(ProjectStage).where(
            ProjectStage.org_id == org_id,
            ProjectStage.project_id == project_id,
            ProjectStage.id == stage_id,
        )
    )


def get_milestone(
    session: Session, org_id: UUID, project_id: UUID, milestone_id: UUID
) -> Milestone | None:
    return session.scalar(
        select(Milestone).where(
            Milestone.org_id == org_id,
            Milestone.project_id == project_id,
            Milestone.id == milestone_id,
        )
    )


def list_stages(
    session: Session, org_id: UUID, project_id: UUID, cursor: str | None, limit: int
) -> tuple[list[ProjectStage], str | None]:
    scope = f"stages:{org_id}:{project_id}"
    inner = unwrap_cursor(cursor, scope)
    statement = select(ProjectStage).where(
        ProjectStage.org_id == org_id, ProjectStage.project_id == project_id
    )
    if inner:
        try:
            decoded: object = json.loads(inner)
            if not isinstance(decoded, dict):
                raise TypeError("stage cursor must be an object")
            bookmark = cast(dict[str, object], decoded)
            position, row_id = bookmark.get("position"), bookmark.get("id")
            if (
                not isinstance(position, int)
                or isinstance(position, bool)
                or not isinstance(row_id, str)
            ):
                raise TypeError("invalid stage bookmark")
            cursor_id = UUID(row_id)
        except (ValueError, TypeError) as exc:
            raise InvalidCursorError("invalid stage cursor") from exc
        statement = statement.where(
            or_(
                ProjectStage.position > position,
                and_(ProjectStage.position == position, ProjectStage.id > cursor_id),
            )
        )
    rows = list(
        session.scalars(statement.order_by(ProjectStage.position, ProjectStage.id).limit(limit + 1))
    )
    items = rows[:limit]
    # Bookmark the observed ordering value, rather than rereading a row whose
    # position may change before the next page is requested.
    next_cursor = (
        json.dumps({"position": items[-1].position, "id": str(items[-1].id)}, separators=(",", ":"))
        if len(rows) > limit
        else None
    )
    return items, wrap_cursor(next_cursor, scope)


def list_milestones(
    session: Session, org_id: UUID, project_id: UUID, cursor: str | None, limit: int
) -> tuple[list[Milestone], str | None]:
    scope = f"milestones:{org_id}:{project_id}"
    items, continuation = page_by_timestamp(
        session,
        select(Milestone).where(Milestone.org_id == org_id, Milestone.project_id == project_id),
        timestamp_column=Milestone.created_at,
        id_column=Milestone.id,
        cursor=unwrap_cursor(cursor, scope),
        limit=limit,
    )
    return items, wrap_cursor(continuation, scope)
