import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert

from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import assistant_repository
from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings, KnowledgeImportedSkill
from cairn_api.knowledge.assistant_schemas import (
    AssistantCatalogResponse,
    AssistantProfileSummary,
    AssistantSettingsRequest,
    AssistantSettingsResponse,
    KnowledgeSkillCatalogResponse,
    KnowledgeSkillImportResponse,
    KnowledgeSkillPreview,
    SkillImportRequest,
    SkillImportSource,
)
from cairn_api.knowledge.conversation_service import (
    KnowledgeConversationService,
    safe_knowledge_operation,
)
from cairn_api.knowledge.skill_imports import preview_skill


class KnowledgeAssistantService(KnowledgeConversationService):
    def _validate_configuration(
        self, identity: IdentityContextResponse, project_id: UUID, payload: AssistantSettingsRequest
    ) -> None:
        if payload.model_id is not None and payload.model_id not in self._answer_models:
            raise ApiProblem(
                status_code=422,
                code="model_not_available",
                message="只能选择服务端当前配置的可用模型",
            )
        available = {
            item.id
            for item in assistant_repository.catalog(
                self._session, identity.organization.id, project_id, identity.user.id
            )
            if item.runnable
        }
        if not set(payload.enabled_skill_ids) <= available:
            raise ApiProblem(
                status_code=422,
                code="skill_not_enabled",
                message="只能启用当前目录内可运行的只读技能",
            )

    @safe_knowledge_operation
    def list_assistants(self, project_id: UUID) -> AssistantCatalogResponse:
        with self._session.begin():
            identity = self._authorize(project_id)
            return AssistantCatalogResponse(
                items=[
                    AssistantProfileSummary(id=row.id, name=row.name, modelId=row.model_id, avatarDataUrl=row.avatar_data_url)
                    for row in assistant_repository.assistant_rows(
                        self._session, identity.organization.id, project_id, identity.user.id
                    )
                ]
            )

    @safe_knowledge_operation
    def create_assistant(
        self, project_id: UUID, payload: AssistantSettingsRequest
    ) -> AssistantSettingsResponse:
        with self._session.begin():
            # _authorize serializes mutations for this user before reading the active revision.
            identity = self._authorize(project_id)
            row = assistant_repository.settings_row(
                self._session, identity.organization.id, project_id, identity.user.id
            )
            current = assistant_repository.settings_response(row)
            if payload.expected_revision != current.revision:
                raise assistant_repository.assistant_changed()
            self._validate_configuration(identity, project_id, payload)
            if (
                len(
                    assistant_repository.assistant_rows(
                        self._session, identity.organization.id, project_id, identity.user.id
                    )
                )
                >= 20
            ):
                raise ApiProblem(
                    status_code=409, code="assistant_limit", message="当前个人项目最多保存20个助手"
                )
            if row is None:
                # Preserve the previously virtual default as a selectable profile.
                self._session.add(
                    KnowledgeAssistantSettings(
                        id=uuid4(),
                        org_id=identity.organization.id,
                        project_id=project_id,
                        owner_id=identity.user.id,
                        name=current.name,
                        instructions=current.instructions,
                        enabled_skill_ids=current.enabled_skill_ids,
                        model_id=current.model_id,
                        revision=1,
                        is_active=False,
                    )
                )
            else:
                row.is_active = False
                self._session.flush()
            created = KnowledgeAssistantSettings(
                id=uuid4(),
                org_id=identity.organization.id,
                project_id=project_id,
                owner_id=identity.user.id,
                name=payload.name,
                avatar_data_url=payload.avatar_data_url,
                instructions=payload.instructions,
                enabled_skill_ids=payload.enabled_skill_ids,
                model_id=payload.model_id,
                revision=current.revision + 1,
                is_active=True,
            )
            self._session.add(created)
            self._session.flush()
            self._business_audit(
                project_id,
                created.id,
                "knowledge.assistant_created",
                {"revision": created.revision},
                resource_type="knowledge_assistant_settings",
            )
            return assistant_repository.settings_response(created)

    @safe_knowledge_operation
    def select_assistant(
        self, project_id: UUID, assistant_id: UUID, expected_revision: int
    ) -> AssistantSettingsResponse:
        with self._session.begin():
            identity = self._authorize(project_id)
            row = assistant_repository.settings_row(
                self._session, identity.organization.id, project_id, identity.user.id
            )
            target = next(
                (
                    item
                    for item in assistant_repository.assistant_rows(
                        self._session, identity.organization.id, project_id, identity.user.id
                    )
                    if item.id == assistant_id
                ),
                None,
            )
            if target is None:
                raise ApiProblem(status_code=404, code="not_found", message="资源不存在")
            assert row is not None
            current = assistant_repository.settings_response(row)
            if expected_revision != current.revision:
                raise assistant_repository.assistant_changed()
            if row.id == target.id:
                return current
            row.is_active = False
            self._session.flush()
            target.is_active = True
            # The active revision is monotonic across profiles, not local to a profile.
            target.revision = current.revision + 1
            self._session.flush()
            self._business_audit(
                project_id,
                target.id,
                "knowledge.assistant_selected",
                {"revision": target.revision, "previousAssistantId": str(row.id)},
                resource_type="knowledge_assistant_settings",
            )
            return assistant_repository.settings_response(target)

    @safe_knowledge_operation
    def get_settings(self, project_id: UUID) -> AssistantSettingsResponse:
        with self._session.begin():
            identity = self._authorize(project_id)
            return assistant_repository.settings_response(
                assistant_repository.settings_row(
                    self._session, identity.organization.id, project_id, identity.user.id
                )
            )

    @safe_knowledge_operation
    def save_settings(
        self, project_id: UUID, payload: AssistantSettingsRequest
    ) -> AssistantSettingsResponse:
        with self._session.begin():
            identity = self._authorize(project_id)
            row = assistant_repository.settings_row(
                self._session, identity.organization.id, project_id, identity.user.id
            )
            current = assistant_repository.settings_response(row)
            if payload.expected_revision != current.revision:
                raise assistant_repository.assistant_changed()
            self._validate_configuration(identity, project_id, payload)
            avatar = payload.avatar_data_url if "avatar_data_url" in payload.model_fields_set else current.avatar_data_url
            if row is not None and (
                row.name,
                row.avatar_data_url,
                row.instructions,
                row.enabled_skill_ids,
                row.model_id,
            ) == (
                payload.name,
                avatar,
                payload.instructions,
                payload.enabled_skill_ids,
                payload.model_id,
            ):
                return current
            if row is None:
                row = KnowledgeAssistantSettings(
                    id=uuid4(),
                    org_id=identity.organization.id,
                    project_id=project_id,
                    owner_id=identity.user.id,
                    revision=0,
                )
                self._session.add(row)
            row.name, row.instructions, row.enabled_skill_ids, row.model_id = (
                payload.name,
                payload.instructions,
                payload.enabled_skill_ids,
                payload.model_id,
            )
            row.avatar_data_url = avatar
            row.revision += 1
            self._session.flush()
            self._business_audit(
                project_id,
                row.id,
                "knowledge.assistant_configured",
                {
                    "revision": row.revision,
                    "enabledSkillIds": row.enabled_skill_ids,
                    "modelId": row.model_id,
                },
                resource_type="knowledge_assistant_settings",
            )
            return assistant_repository.settings_response(row)

    @safe_knowledge_operation
    def list_skills(self, project_id: UUID) -> KnowledgeSkillCatalogResponse:
        with self._session.begin():
            identity = self._authorize(project_id)
            return KnowledgeSkillCatalogResponse(
                items=assistant_repository.catalog(
                    self._session, identity.organization.id, project_id, identity.user.id
                )
            )

    @safe_knowledge_operation
    def preview(self, project_id: UUID, source: SkillImportSource) -> KnowledgeSkillPreview:
        with self._session.begin():
            self._authorize(project_id)
        preview = preview_skill(source)
        with self._session.begin():
            self._authorize(project_id)
        return preview

    def _import_replay(
        self, project_id: UUID, skill_id: UUID, fingerprint: str
    ) -> KnowledgeSkillImportResponse | None:
        row = self._session.get(KnowledgeImportedSkill, skill_id)
        if row is None:
            return None
        if (
            row.org_id != self._identity.organization.id
            or row.project_id != project_id
            or row.owner_id != self._identity.user.id
        ):
            raise ApiProblem(status_code=404, code="not_found", message="资源不存在")
        if row.request_fingerprint != fingerprint:
            raise ApiProblem(
                status_code=409,
                code="skill_import_changed",
                message="导入参数或内容已变化，请重新预览",
            )
        return KnowledgeSkillImportResponse.model_validate({"id": row.id, **row.preview})

    @safe_knowledge_operation
    def import_skill(
        self, project_id: UUID, payload: SkillImportRequest
    ) -> tuple[KnowledgeSkillImportResponse, bool]:
        fingerprint = hashlib.sha256(
            json.dumps(
                payload.model_dump(mode="json", exclude={"id"}), sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest()
        with self._session.begin():
            self._authorize(project_id)
            replay = self._import_replay(project_id, payload.id, fingerprint)
            if replay is not None:
                return replay, False
        preview = preview_skill(payload.source)
        if preview.digest != payload.expected_digest:
            raise ApiProblem(
                status_code=409, code="skill_import_changed", message="预览后内容已变化，请重新预览"
            )
        with self._session.begin():
            identity = self._authorize(project_id)
            replay = self._import_replay(project_id, payload.id, fingerprint)
            if replay is not None:
                return replay, False
            if (
                len(
                    assistant_repository.imported_rows(
                        self._session, identity.organization.id, project_id, identity.user.id
                    )
                )
                >= 20
            ):
                raise ApiProblem(
                    status_code=409,
                    code="skill_import_limit",
                    message="当前私有项目最多导入 20 个技能",
                )
            saved = self._session.scalar(
                insert(KnowledgeImportedSkill)
                .values(
                    id=payload.id,
                    org_id=identity.organization.id,
                    project_id=project_id,
                    owner_id=identity.user.id,
                    request_fingerprint=fingerprint,
                    preview=preview.model_dump(mode="json"),
                )
                .on_conflict_do_nothing(index_elements=[KnowledgeImportedSkill.id])
                .returning(KnowledgeImportedSkill.id)
            )
            if saved is None:
                replay = self._import_replay(project_id, payload.id, fingerprint)
                assert replay is not None
                return replay, False
            self._business_audit(
                project_id,
                payload.id,
                "knowledge.skill_imported",
                {
                    "skillId": str(payload.id),
                    "sourceType": preview.source_type,
                    "runnable": preview.runnable,
                },
                resource_type="knowledge_skill",
            )
            return KnowledgeSkillImportResponse(id=payload.id, **preview.model_dump()), True
