from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from cairn_api.audit.repository import add_audit_log
from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import assistant_repository
from cairn_api.knowledge.answer_models import ConfiguredAnswerModel, selected_answer_model
from cairn_api.knowledge.answer_provider import (
    AnswerEvidence,
    AnswerGuidance,
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
    GuidedAnswerProvider,
    ProjectPlanProvider,
)
from cairn_api.knowledge.answer_schemas import KnowledgeAnswerCitation, KnowledgeAnswerParagraph
from cairn_api.knowledge.assistant_schemas import AssistantSettingsResponse
from cairn_api.knowledge.conversation_service import (
    KnowledgeConversationService,
    safe_knowledge_operation,
)
from cairn_api.knowledge.schemas import KnowledgeCitation, KnowledgeSearchResponse
from cairn_api.knowledge.search_service import KnowledgeSearchService
from cairn_api.projects.analysis_schemas import (
    ProjectAnalysisResponse,
    ProjectAnalysisSnapshot,
    ProjectPlanPreviewResponse,
)
from cairn_api.projects.models import Milestone, Project, ProjectStage, Task, TaskDependency
from cairn_api.projects.schemas import (
    DependencyResponse,
    MilestoneResponse,
    ProjectResponse,
    StageResponse,
    TaskResponse,
)

ANALYSIS_QUESTION = (
    "请根据 S1 项目结构快照与其他检索证据，按“进展、缺口、风险、下一步建议”分析当前项目。"
    "每段引用支持判断的来源。区分已记录事实、推断和建议，推断须明确标注；"
    "任务状态只是记录，不等于实际验收通过。缺少目标、截止日期、负责人或验收标准时明确说明。"
    "归档阶段和里程碑是历史记录。没有命中知识资料不代表项目不存在其他资料；"
    "本次检索不是全量资料审阅。不得虚构完成情况、截止日期或声称已执行项目操作。"
)


def analysis_changed() -> ApiProblem:
    return ApiProblem(
        status_code=409,
        code="project_analysis_changed",
        message="项目、资料或访问权限已变化，请重新分析",
    )


def analysis_too_large() -> ApiProblem:
    return ApiProblem(
        status_code=422,
        code="project_analysis_too_large",
        message="项目超出本次分析容量（100个任务、50个阶段、50个里程碑、300条依赖或60000字符）",
    )


@dataclass(frozen=True)
class ProjectAnalysisInputs:
    snapshot: ProjectAnalysisSnapshot
    assistant: AssistantSettingsResponse
    model: ConfiguredAnswerModel
    found: KnowledgeSearchResponse
    evidence: list[AnswerEvidence]
    citations: list[KnowledgeAnswerCitation]


class ProjectAnalysisService(KnowledgeConversationService):
    """Reuse the private assistant's session and evidence guards; persist no conversation."""

    def _snapshot(self, project_id: UUID) -> ProjectAnalysisSnapshot:
        org_id = self._identity.organization.id
        project = self._session.scalar(
            select(Project).where(Project.org_id == org_id, Project.id == project_id)
        )
        assert project is not None  # _authorize already checked and locked this project.
        stages = list(
            self._session.scalars(
                select(ProjectStage)
                .where(ProjectStage.org_id == org_id, ProjectStage.project_id == project_id)
                .order_by(ProjectStage.position, ProjectStage.id)
                .limit(51)
            )
        )
        milestones = list(
            self._session.scalars(
                select(Milestone)
                .where(Milestone.org_id == org_id, Milestone.project_id == project_id)
                .order_by(Milestone.id)
                .limit(51)
            )
        )
        tasks = list(
            self._session.scalars(
                select(Task)
                .where(Task.org_id == org_id, Task.project_id == project_id)
                .order_by(Task.id)
                .limit(101)
            )
        )
        dependencies = list(
            self._session.scalars(
                select(TaskDependency)
                .where(TaskDependency.org_id == org_id, TaskDependency.project_id == project_id)
                .order_by(TaskDependency.id)
                .limit(301)
            )
        )
        if len(stages) > 50 or len(milestones) > 50 or len(tasks) > 100 or len(dependencies) > 300:
            raise analysis_too_large()
        snapshot = ProjectAnalysisSnapshot(
            project=ProjectResponse.model_validate(project),
            stages=[StageResponse.model_validate(row) for row in stages],
            milestones=[MilestoneResponse.model_validate(row) for row in milestones],
            tasks=[TaskResponse.model_validate(row) for row in tasks],
            dependencies=[DependencyResponse.model_validate(row) for row in dependencies],
        )
        if len(snapshot.model_dump_json(by_alias=True)) > 60_000:
            raise analysis_too_large()
        return snapshot

    def _check_inputs(
        self,
        project_id: UUID,
        snapshot: ProjectAnalysisSnapshot,
        citations: list[KnowledgeCitation],
    ) -> None:
        try:
            identity = self._authorize(project_id)
            if self._snapshot(project_id) != snapshot or not self._citations_valid(
                identity, project_id, citations
            ):
                raise analysis_changed()
        except ApiProblem as exc:
            if exc.code in {"not_found", "project_analysis_too_large"}:
                raise analysis_changed() from None
            raise

    def _load_inputs(
        self, project_id: UUID, search: KnowledgeSearchService
    ) -> ProjectAnalysisInputs:
        with self._session.begin():
            identity = self._authorize(project_id)
            snapshot = self._snapshot(project_id)
            assistant = assistant_repository.settings_response(
                assistant_repository.settings_row(
                    self._session,
                    identity.organization.id,
                    project_id,
                    identity.user.id,
                )
            )
            model = selected_answer_model(self._answer_models, assistant.model_id)
        # Both network operations run outside transactions; finalization checks all inputs again.
        found = search.search(
            identity=identity,
            project_id=project_id,
            query=f"项目进展 风险 验收 {snapshot.project.name} {snapshot.project.description or ''}"[
                :500
            ],
            limit=5,
            audit=self._audit,
        )
        citations = found.results
        with self._session.begin():
            self._check_inputs(project_id, snapshot, citations)
        evidence = [
            AnswerEvidence(
                id="S1",
                chunk_id=project_id,
                title="项目结构快照",
                locator={"type": "project", "projectId": str(project_id)},
                text=snapshot.model_dump_json(by_alias=True),
            )
        ] + [
            AnswerEvidence(
                id=f"S{index}",
                chunk_id=citation.chunk_id,
                title=citation.title,
                locator=citation.locator.model_dump(by_alias=True),
                text=citation.excerpt,
            )
            for index, citation in enumerate(citations, 2)
        ]
        return ProjectAnalysisInputs(
            snapshot=snapshot,
            assistant=assistant,
            model=model,
            found=found,
            evidence=evidence,
            citations=[
                KnowledgeAnswerCitation(
                    id=f"S{index}",
                    **citation.model_dump(exclude={"locator"}),
                    locator=citation.locator,
                )
                for index, citation in enumerate(citations, 2)
            ],
        )

    @safe_knowledge_operation
    def analyze(self, project_id: UUID, search: KnowledgeSearchService) -> ProjectAnalysisResponse:
        inputs = self._load_inputs(project_id, search)
        snapshot, assistant, model, found, evidence = (
            inputs.snapshot,
            inputs.assistant,
            inputs.model,
            inputs.found,
            inputs.evidence,
        )
        question = f"本次分析时间（UTC）：{datetime.now(UTC).isoformat()}。{ANALYSIS_QUESTION}"
        try:
            if assistant.instructions:
                if not callable(getattr(model.provider, "generate_with_guidance", None)):
                    raise AnswerProviderUnavailable()
                generated = cast(GuidedAnswerProvider, model.provider).generate_with_guidance(
                    question=question,
                    evidence=evidence,
                    history=[],
                    guidance=AnswerGuidance(
                        assistant_name=assistant.name,
                        instructions=assistant.instructions,
                        skill_id=None,
                        skill_instructions="",
                        resources=[],
                    ),
                )
            else:
                generated = model.provider.generate(question=question, evidence=evidence)
            response = ProjectAnalysisResponse(
                projectId=project_id,
                generatedAt=datetime.now(UTC),
                assistantName=assistant.name,
                model=model.info,
                snapshot=snapshot,
                status=generated.status,
                retrievalMode=found.retrieval_mode,
                paragraphs=[
                    KnowledgeAnswerParagraph(
                        text=paragraph.text.strip(),
                        citationIds=paragraph.citation_ids,
                    )
                    for paragraph in generated.paragraphs
                ],
                citations=inputs.citations,
            )
        except (AnswerProviderUnavailable, AnswerProviderInvalidResponse, ValidationError):
            raise ApiProblem(
                status_code=503,
                code="answer_unavailable",
                message="项目分析暂时不可用，请稍后重试",
            ) from None
        self._finish(project_id, inputs, response.status, "project.analyzed")
        return response

    @safe_knowledge_operation
    def preview_plan(
        self, project_id: UUID, search: KnowledgeSearchService
    ) -> ProjectPlanPreviewResponse:
        inputs = self._load_inputs(project_id, search)
        try:
            if not callable(getattr(inputs.model.provider, "generate_project_plan", None)):
                raise AnswerProviderUnavailable()
            plan = cast(ProjectPlanProvider, inputs.model.provider).generate_project_plan(
                question=f"请依据当前项目生成后续只读规划建议。当前时间（UTC）：{datetime.now(UTC).isoformat()}。已有任务仅作为依据，不要声称已经创建或修改项目。",
                evidence=inputs.evidence,
                guidance=AnswerGuidance(
                    assistant_name=inputs.assistant.name,
                    instructions=inputs.assistant.instructions,
                    skill_id=None,
                    skill_instructions="",
                    resources=[],
                ),
            )
            response = ProjectPlanPreviewResponse(
                projectId=project_id,
                generatedAt=datetime.now(UTC),
                assistantName=inputs.assistant.name,
                model=inputs.model.info,
                snapshot=inputs.snapshot,
                retrievalMode=inputs.found.retrieval_mode,
                citations=inputs.citations,
                plan=plan,
            )
        except (AnswerProviderUnavailable, AnswerProviderInvalidResponse, ValidationError):
            raise ApiProblem(
                status_code=503, code="answer_unavailable", message="规划预览暂时不可用，请稍后重试"
            ) from None
        response.can_apply = self._finish(project_id, inputs, plan.status, "project.plan_previewed")
        return response

    def _finish(
        self, project_id: UUID, inputs: ProjectAnalysisInputs, status: str, action: str
    ) -> bool:
        with self._session.begin():
            self._check_inputs(project_id, inputs.snapshot, inputs.found.results)
            can_apply = (
                self._policy.find_project(
                    self._identity, project_id, ProjectPermission.WRITE, for_update=True
                )
                is not None
            )
            add_audit_log(
                self._session,
                org_id=self._identity.organization.id,
                actor_type="user",
                actor_id=self._identity.user.id,
                action=action,
                resource_type="project",
                resource_id=project_id,
                trace_id=self._audit.trace_id,
                ip=self._audit.ip,
                user_agent=self._audit.user_agent,
                details={
                    "status": status,
                    "taskCount": len(inputs.snapshot.tasks),
                    "sourceCount": len(inputs.citations),
                    "modelId": inputs.model.info.id,
                },
            )
            return can_apply
