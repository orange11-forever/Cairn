from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn_api.errors import ApiProblem
from cairn_api.knowledge.answer_provider import AnswerGuidance
from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings, KnowledgeImportedSkill
from cairn_api.knowledge.assistant_schemas import (
    AssistantSettingsResponse,
    KnowledgeSkillItem,
    KnowledgeSkillPreview,
)
from cairn_api.knowledge.skill_registry import BUILTIN_GUIDANCE, BUILTIN_SKILLS


def settings_row(
    session: Session, org_id: UUID, project_id: UUID, owner_id: UUID
) -> KnowledgeAssistantSettings | None:
    return session.scalar(
        select(KnowledgeAssistantSettings)
        .where(
            KnowledgeAssistantSettings.org_id == org_id,
            KnowledgeAssistantSettings.project_id == project_id,
            KnowledgeAssistantSettings.owner_id == owner_id,
            KnowledgeAssistantSettings.is_active.is_(True),
        )
        .with_for_update()
    )


def settings_response(row: KnowledgeAssistantSettings | None) -> AssistantSettingsResponse:
    return AssistantSettingsResponse(
        id=None if row is None else row.id,
        name="岑宁" if row is None else row.name,
        avatarDataUrl=None if row is None else row.avatar_data_url,
        instructions="" if row is None else row.instructions,
        enabledSkillIds=[] if row is None else row.enabled_skill_ids,
        revision=0 if row is None else row.revision,
        modelId=None if row is None else row.model_id,
    )


def assistant_rows(
    session: Session, org_id: UUID, project_id: UUID, owner_id: UUID
) -> list[KnowledgeAssistantSettings]:
    return list(
        session.scalars(
            select(KnowledgeAssistantSettings)
            .where(
                KnowledgeAssistantSettings.org_id == org_id,
                KnowledgeAssistantSettings.project_id == project_id,
                KnowledgeAssistantSettings.owner_id == owner_id,
            )
            .order_by(KnowledgeAssistantSettings.created_at, KnowledgeAssistantSettings.id)
        )
    )


def imported_rows(
    session: Session, org_id: UUID, project_id: UUID, owner_id: UUID
) -> list[KnowledgeImportedSkill]:
    return list(
        session.scalars(
            select(KnowledgeImportedSkill)
            .where(
                KnowledgeImportedSkill.org_id == org_id,
                KnowledgeImportedSkill.project_id == project_id,
                KnowledgeImportedSkill.owner_id == owner_id,
            )
            .order_by(KnowledgeImportedSkill.created_at, KnowledgeImportedSkill.id)
        )
    )


def skill_item(row: KnowledgeImportedSkill) -> KnowledgeSkillItem:
    preview = KnowledgeSkillPreview.model_validate(row.preview)
    return KnowledgeSkillItem(
        id=str(row.id),
        **preview.model_dump(
            include={
                "name",
                "description",
                "default_question",
                "version",
                "capabilities",
                "source_type",
                "runnable",
                "warnings",
            }
        ),
    )


def catalog(
    session: Session, org_id: UUID, project_id: UUID, owner_id: UUID
) -> list[KnowledgeSkillItem]:
    return [
        *BUILTIN_SKILLS,
        *[skill_item(row) for row in imported_rows(session, org_id, project_id, owner_id)],
    ]


def assistant_changed() -> ApiProblem:
    return ApiProblem(
        status_code=409,
        code="assistant_changed",
        message="助手配置已变化，请重新读取助手配置和会话",
    )


def guidance(
    session: Session,
    org_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    expected_revision: int,
    skill_id: str | None,
) -> tuple[AssistantSettingsResponse, AnswerGuidance | None]:
    settings = settings_response(settings_row(session, org_id, project_id, owner_id))
    if settings.revision != expected_revision:
        raise assistant_changed()
    body = ""
    resources: list[dict[str, str]] = []
    if skill_id is not None:
        item = next(
            (
                item
                for item in catalog(session, org_id, project_id, owner_id)
                if item.id == skill_id
            ),
            None,
        )
        if item is None or not item.runnable or skill_id not in settings.enabled_skill_ids:
            raise ApiProblem(
                status_code=422,
                code="skill_not_enabled",
                message="技能不存在、尚未启用或依赖不受支持",
            )
        if skill_id in BUILTIN_GUIDANCE:
            body = BUILTIN_GUIDANCE[skill_id]
        else:
            row = next(
                row
                for row in imported_rows(session, org_id, project_id, owner_id)
                if str(row.id) == skill_id
            )
            preview = KnowledgeSkillPreview.model_validate(row.preview)
            body = preview.body
            resources = [item.model_dump() for item in preview.resources]
    if settings.name == "岑宁" and not settings.instructions and skill_id is None:
        return settings, None
    return settings, AnswerGuidance(
        assistant_name=settings.name,
        instructions=settings.instructions,
        skill_id=skill_id,
        skill_instructions=body,
        resources=resources,
    )
