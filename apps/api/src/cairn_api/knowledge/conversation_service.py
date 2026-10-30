from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.models import AuthSession, User
from cairn_api.auth.repository import get_session_record
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.security import digest_token
from cairn_api.auth.service import AuthService, RequestAuditContext, identity_context
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import ProjectPermission
from cairn_api.db.errors import DATABASE_UNAVAILABLE_ERRORS
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import assistant_repository, search_repository
from cairn_api.knowledge.answer_models import (
    AnswerModelOption,
    ConfiguredAnswerModel,
    selected_answer_model,
)
from cairn_api.knowledge.answer_provider import AnswerHistoryTurn
from cairn_api.knowledge.answer_schemas import KnowledgeAnswerParagraph, KnowledgeAnswerResponse
from cairn_api.knowledge.answer_service import KnowledgeAnswerService, knowledge_changed
from cairn_api.knowledge.conversation_models import KnowledgeConversation, KnowledgeConversationTurn
from cairn_api.knowledge.conversation_schemas import (
    KnowledgeConversationPage,
    KnowledgeConversationResponse,
    KnowledgeConversationSummary,
    KnowledgeConversationTurnResponse,
)
from cairn_api.knowledge.models import KnowledgeResource
from cairn_api.knowledge.schemas import KnowledgeCitation, normalize_search_query
from cairn_api.knowledge.source_access import validate_index_source
from cairn_api.pagination import load_cursor_page, page_by_timestamp

MAX_HISTORY_TURNS = 6
MAX_HISTORY_CODEPOINTS = 12000


def conversation_answer_snapshot(answer: KnowledgeAnswerResponse) -> dict[str, object]:
    # Citation fields accept internal names; locator models require wire aliases.
    # Keep the snapshot roundtrippable without broadening either public schema.
    snapshot = answer.model_dump(mode="json")
    snapshot["citations"] = [
        {
            **citation.model_dump(mode="json", exclude={"locator"}),
            "locator": citation.locator.model_dump(mode="json", by_alias=True),
        }
        for citation in answer.citations
    ]
    return snapshot


def bounded_history(turns: list[AnswerHistoryTurn]) -> tuple[list[AnswerHistoryTurn], bool]:
    """Retain a contiguous suffix of complete eligible turns, never partial text."""
    selected: list[AnswerHistoryTurn] = []
    size = 0
    for turn in reversed(turns):
        length = len(turn.question) + len(turn.answer)
        if len(selected) == MAX_HISTORY_TURNS or size + length > MAX_HISTORY_CODEPOINTS:
            break
        selected.append(turn)
        size += length
    selected.reverse()
    return selected, len(selected) != len(turns)


def safe_knowledge_operation[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    @wraps(operation)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return operation(*args, **kwargs)
        except (ApiProblem, *DATABASE_UNAVAILABLE_ERRORS):
            raise
        except Exception:  # noqa: BLE001
            raise ApiProblem(
                status_code=500, code="internal_error", message="服务器内部错误"
            ) from None

    return wrapped


def _conflict() -> ApiProblem:
    return ApiProblem(
        status_code=409, code="conversation_conflict", message="对话已发生变化，请重新读取对话"
    )


def _not_found() -> ApiProblem:
    return ApiProblem(status_code=404, code="not_found", message="资源不存在")


class KnowledgeConversationService:
    def __init__(
        self,
        session: Session,
        identity: IdentityContextResponse,
        session_token: str | None,
        audit: RequestAuditContext,
        answer_service: KnowledgeAnswerService | None = None,
        *,
        answer_models: dict[str, ConfiguredAnswerModel] | None = None,
    ) -> None:
        self._session = session
        self._identity = identity
        self._session_token = session_token
        self._audit = audit
        self._answer_service = answer_service
        self._answer_models = answer_models if answer_models is not None else {}
        self._policy = AuthorizationPolicy(session)

    def close(self) -> None:
        self._session.close()

    def _authorize(self, project_id: UUID) -> IdentityContextResponse:
        # The request identity and cached ORM objects may be stale after provider I/O.
        self._session.expire_all()
        self._policy.require_project(
            self._identity, project_id, ProjectPermission.READ, for_update=True
        )
        if self._session_token is None:
            raise ApiProblem(status_code=401, code="session_invalid", message="会话无效或已过期")
        digest = digest_token(self._session_token)
        self._session.scalar(
            select(AuthSession.id).where(AuthSession.token_digest == digest).with_for_update()
        )
        self._session.scalar(
            # NO KEY UPDATE still serializes deactivation/deletion, while allowing
            # auth-restore audit inserts to take their foreign-key KEY SHARE lock.
            # FOR UPDATE here can deadlock with that restore's auth-session update.
            select(User.id).where(User.id == self._identity.user.id).with_for_update(key_share=True)
        )
        record = get_session_record(self._session, digest)
        if not AuthService.record_is_valid(record, csrf_token=self._identity.csrf_token):
            raise ApiProblem(status_code=401, code="session_invalid", message="会话无效或已过期")
        assert record is not None
        if (
            record.user.id != self._identity.user.id
            or record.organization.id != self._identity.organization.id
        ):
            raise ApiProblem(status_code=401, code="session_invalid", message="会话无效或已过期")
        return identity_context(record, user=record.user, csrf_token=self._identity.csrf_token)

    def _conversation(self, project_id: UUID, conversation_id: UUID) -> KnowledgeConversation:
        row = self._session.scalar(
            select(KnowledgeConversation)
            .where(
                KnowledgeConversation.id == conversation_id,
                KnowledgeConversation.org_id == self._identity.organization.id,
                KnowledgeConversation.project_id == project_id,
                KnowledgeConversation.owner_id == self._identity.user.id,
            )
            .with_for_update()
        )
        if row is None:
            raise _not_found()
        return row

    def _turns(self, conversation_id: UUID) -> list[KnowledgeConversationTurn]:
        return list(
            self._session.scalars(
                select(KnowledgeConversationTurn)
                .where(KnowledgeConversationTurn.conversation_id == conversation_id)
                .order_by(KnowledgeConversationTurn.sequence)
            )
        )

    def _citations_valid(
        self,
        identity: IdentityContextResponse,
        project_id: UUID,
        citations: list[KnowledgeCitation],
    ) -> bool:
        if not citations:
            return True
        # A chunk may occur in multiple historical answers; validate the unique evidence.
        citations = list({citation.chunk_id: citation for citation in citations}.values())
        resources = sorted({citation.resource_id for citation in citations}, key=str)
        self._session.execute(
            select(KnowledgeResource.id)
            .where(
                KnowledgeResource.org_id == identity.organization.id,
                KnowledgeResource.project_id == project_id,
                KnowledgeResource.id.in_(resources),
            )
            .order_by(KnowledgeResource.id)
            .with_for_update()
        ).all()
        for citation in sorted(citations, key=lambda item: str(item.resource_id)):
            if not validate_index_source(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                resource_id=citation.resource_id,
                version_id=citation.resource_version_id,
                lock_source=True,
            ):
                return False
        records = search_repository.load_citations(
            self._session,
            org_id=identity.organization.id,
            project_id=project_id,
            chunk_ids=[item.chunk_id for item in citations],
            access_filter=self._policy.project_filter(
                identity,
                ProjectPermission.READ,
                cast(ColumnElement[UUID], KnowledgeResource.project_id),
            ),
        )
        return [
            (item.resource_id, item.resource_version_id, item.chunk_id) for item in records
        ] == [(item.resource_id, item.resource_version_id, item.chunk_id) for item in citations]

    def _detail(
        self, identity: IdentityContextResponse, row: KnowledgeConversation
    ) -> KnowledgeConversationResponse:
        turns: list[KnowledgeConversationTurnResponse] = []
        for turn in self._turns(row.id):
            answer = KnowledgeAnswerResponse.model_validate(turn.answer)
            valid = self._citations_valid(identity, row.project_id, list(answer.citations))
            turns.append(
                KnowledgeConversationTurnResponse(
                    id=turn.id,
                    sequence=turn.sequence,
                    question=turn.question,
                    answer=answer if valid else None,
                    assistantName=turn.assistant_name,
                    assistantId=turn.assistant_id,
                    assistantRevision=turn.assistant_revision,
                    skillId=turn.skill_id,
                    model=AnswerModelOption.model_validate(turn.model_snapshot) if turn.model_snapshot is not None else None,
                    answerUnavailable=not valid,
                    contextTruncated=turn.context_truncated,
                    createdAt=turn.created_at,
                )
            )
        return KnowledgeConversationResponse(
            **KnowledgeConversationSummary.model_validate(row).model_dump(), turns=turns
        )

    def _business_audit(
        self,
        project_id: UUID,
        conversation_id: UUID,
        action: str,
        details: dict[str, object],
        *,
        resource_type: str = "knowledge_conversation",
    ) -> None:
        add_audit_log(
            self._session,
            org_id=self._identity.organization.id,
            actor_type="user",
            actor_id=self._identity.user.id,
            action=action,
            resource_type=resource_type,
            resource_id=conversation_id,
            trace_id=self._audit.trace_id,
            ip=self._audit.ip,
            user_agent=self._audit.user_agent,
            details={"projectId": str(project_id), **details},
        )

    @safe_knowledge_operation
    def model_authorize(self, project_id: UUID) -> None:
        with self._session.begin():
            self._authorize(project_id)

    @safe_knowledge_operation
    def create(
        self, project_id: UUID, conversation_id: UUID
    ) -> tuple[KnowledgeConversationResponse, bool]:
        with self._session.begin():
            identity = self._authorize(project_id)
            created = (
                self._session.scalar(
                    insert(KnowledgeConversation)
                    .values(
                        id=conversation_id,
                        org_id=identity.organization.id,
                        project_id=project_id,
                        owner_id=identity.user.id,
                    )
                    .on_conflict_do_nothing(index_elements=[KnowledgeConversation.id])
                    .returning(KnowledgeConversation.id)
                )
                is not None
            )
            row = self._conversation(project_id, conversation_id)
            if created:
                self._business_audit(
                    project_id,
                    conversation_id,
                    "knowledge.conversation_created",
                    {"revision": 1, "turnCount": 0},
                )
            return self._detail(identity, row), created

    @safe_knowledge_operation
    def list(
        self, project_id: UUID, *, cursor: str | None, limit: int, current_assistant: bool = False
    ) -> KnowledgeConversationPage:
        with self._session.begin():
            identity = self._authorize(project_id)
            query = select(KnowledgeConversation).where(
                KnowledgeConversation.org_id == identity.organization.id,
                KnowledgeConversation.project_id == project_id,
                KnowledgeConversation.owner_id == identity.user.id,
            )
            if current_assistant:
                config = assistant_repository.settings_response(assistant_repository.settings_row(
                    self._session, identity.organization.id, project_id, identity.user.id
                ))
                query = query.where(select(KnowledgeConversationTurn.id).where(
                    KnowledgeConversationTurn.conversation_id == KnowledgeConversation.id,
                    KnowledgeConversationTurn.assistant_id == config.id,
                ).exists(), ~select(KnowledgeConversationTurn.id).where(
                    KnowledgeConversationTurn.conversation_id == KnowledgeConversation.id,
                    KnowledgeConversationTurn.assistant_id.is_distinct_from(config.id),
                ).exists())
            rows, next_cursor = load_cursor_page(
                lambda: page_by_timestamp(
                    self._session,
                    query,
                    timestamp_column=KnowledgeConversation.created_at,
                    id_column=KnowledgeConversation.id,
                    cursor=cursor,
                    limit=limit,
                    descending=True,
                )
            )
            return KnowledgeConversationPage(
                items=[KnowledgeConversationSummary.model_validate(row) for row in rows],
                nextCursor=next_cursor,
            )

    @safe_knowledge_operation
    def read(self, project_id: UUID, conversation_id: UUID) -> KnowledgeConversationResponse:
        with self._session.begin():
            identity = self._authorize(project_id)
            return self._detail(identity, self._conversation(project_id, conversation_id))

    def _replay(
        self,
        row: KnowledgeConversation,
        turn_id: UUID,
        question: str,
        assistant_revision: int = 0,
        skill_id: str | None = None,
    ) -> bool:
        turn = self._session.get(KnowledgeConversationTurn, turn_id)
        if turn is None:
            return False
        if (
            turn.conversation_id != row.id
            or turn.org_id != row.org_id
            or turn.project_id != row.project_id
        ):
            raise _not_found()
        if (
            turn.question != question
            or turn.assistant_revision != assistant_revision
            or turn.skill_id != skill_id
        ):
            raise _conflict()
        return True

    @safe_knowledge_operation
    def append(
        self,
        project_id: UUID,
        conversation_id: UUID,
        *,
        turn_id: UUID,
        expected_revision: int,
        question: str,
        assistant_revision: int = 0,
        skill_id: str | None = None,
        on_paragraph: Callable[[KnowledgeAnswerParagraph], None] | None = None,
        check_cancelled: Callable[[], None] = lambda: None,
        wait_for_delivery: Callable[[], None] = lambda: None,
    ) -> KnowledgeConversationResponse:
        check_cancelled()
        question = normalize_search_query(question)
        if (
            not 3 <= len(question) <= 500
            or type(expected_revision) is not int
            or expected_revision < 1
        ):
            raise ApiProblem(status_code=422, code="validation_error", message="请求参数无效")
        with self._session.begin():
            identity = self._authorize(project_id)
            row = self._conversation(project_id, conversation_id)
            if self._replay(row, turn_id, question, assistant_revision, skill_id):
                return self._detail(identity, row)
            if row.revision != expected_revision or row.revision >= 51:
                raise _conflict()
            config, applied_guidance = assistant_repository.guidance(
                self._session,
                identity.organization.id,
                project_id,
                identity.user.id,
                assistant_revision,
                skill_id,
            )
            selected_model = selected_answer_model(self._answer_models, config.model_id)
            detail = self._detail(identity, row)
            if any(turn.assistant_id != config.id for turn in detail.turns):
                raise ApiProblem(
                    status_code=409,
                    code="conversation_assistant_mismatch",
                    message="这段对话包含其他助手的历史，请为当前助手新建对话；原历史仍保留。",
                )
            eligible = [turn for turn in detail.turns if turn.answer is not None]
            history, truncated = bounded_history(
                [
                    AnswerHistoryTurn(
                        question=turn.question,
                        answer="\n".join(
                            paragraph.text
                            for paragraph in cast(KnowledgeAnswerResponse, turn.answer).paragraphs
                        ),
                    )
                    for turn in eligible
                ]
            )
            truncated = truncated or len(eligible) != len(detail.turns)
            used_history = eligible[-len(history) :] if history else []
            historical_citations = [
                citation
                for turn in used_history
                for citation in cast(KnowledgeAnswerResponse, turn.answer).citations
            ]
        # Retrieval and provider I/O run outside transactions. Old questions can resolve
        # follow-ups, while old answers never replace the current retrieval evidence.
        retrieval_query = question
        if history and len(question) < 499:
            retrieval_query = question + " " + history[-1].question[: 499 - len(question)]
        current_citations: list[KnowledgeCitation] = []

        def check_history() -> None:
            with self._session.begin():
                fresh = self._authorize(project_id)
                current = self._conversation(project_id, conversation_id)
                if current.revision != expected_revision:
                    raise _conflict()
                assistant_repository.guidance(
                    self._session,
                    fresh.organization.id,
                    project_id,
                    fresh.user.id,
                    assistant_revision,
                    skill_id,
                )
                if not self._citations_valid(
                    fresh, project_id, list(historical_citations)
                ) or not self._citations_valid(fresh, project_id, current_citations):
                    raise knowledge_changed()

        def emit(paragraph: KnowledgeAnswerParagraph) -> None:
            # Buffer waits happen before the short authorization transaction.
            wait_for_delivery()
            check_cancelled()
            check_history()
            check_cancelled()
            assert on_paragraph is not None
            on_paragraph(paragraph)

        assert self._answer_service is not None
        try:
            answer = self._answer_service.answer(
                provider=selected_model.provider,
                identity=identity,
                project_id=project_id,
                question=question,
                audit=self._audit,
                history=history,
                guidance=applied_guidance,
                retrieval_query=retrieval_query,
                before_generate=check_history,
                audit_result=False,
                retrieved_evidence=current_citations.extend,
                on_paragraph=emit if on_paragraph is not None else None,
                check_cancelled=check_cancelled,
            )
        except ApiProblem as problem:
            if problem.status_code == 409 and problem.code in {
                "conversation_conflict",
                "assistant_changed",
            }:
                # An identical request may commit while this request retrieves.
                # Recover its saved response before presenting a revision conflict,
                # with the same fresh auth/scope/evidence checks as any read.
                with self._session.begin():
                    fresh = self._authorize(project_id)
                    current = self._conversation(project_id, conversation_id)
                    if self._replay(current, turn_id, question, assistant_revision, skill_id):
                        return self._detail(fresh, current)
            raise
        with self._session.begin():
            identity = self._authorize(project_id)
            row = self._conversation(project_id, conversation_id)
            if self._replay(row, turn_id, question, assistant_revision, skill_id):
                return self._detail(identity, row)
            if row.revision != expected_revision or row.revision >= 51:
                raise _conflict()
            if not self._citations_valid(
                identity, project_id, list(historical_citations)
            ) or not self._citations_valid(identity, project_id, current_citations):
                raise knowledge_changed()
            assistant_repository.guidance(
                self._session,
                identity.organization.id,
                project_id,
                identity.user.id,
                assistant_revision,
                skill_id,
            )
            check_cancelled()
            sequence = row.revision
            inserted = self._session.scalar(
                insert(KnowledgeConversationTurn)
                .values(
                    id=turn_id,
                    org_id=identity.organization.id,
                    project_id=project_id,
                    conversation_id=row.id,
                    sequence=sequence,
                    assistant_name=config.name,
                    assistant_id=config.id,
                    assistant_revision=config.revision,
                    skill_id=skill_id,
                    model_snapshot=selected_model.info.model_dump(mode="json"),
                    question=question,
                    answer=conversation_answer_snapshot(answer),
                    context_truncated=truncated,
                )
                .on_conflict_do_nothing(index_elements=[KnowledgeConversationTurn.id])
                .returning(KnowledgeConversationTurn.id)
            )
            # Another private scope may commit this UUID after the initial lookup.
            # Handle that database uniqueness race without exposing its owner.
            if inserted is None:
                if self._replay(row, turn_id, question, assistant_revision, skill_id):
                    return self._detail(identity, row)
                raise _not_found()
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            if sequence == 1:
                row.title = question[:60]
            self._session.flush()
            self._business_audit(
                project_id,
                conversation_id,
                "knowledge.conversation_turn_appended",
                {
                    "turnId": str(turn_id),
                    "revision": row.revision,
                    "turnCount": row.revision - 1,
                    "questionLength": len(question),
                    "paragraphCount": len(answer.paragraphs),
                    "sourceCount": len(answer.citations),
                    "status": answer.status,
                    "contextTruncated": truncated,
                    "assistantRevision": config.revision,
                    "skillId": skill_id,
                    "modelId": selected_model.info.id,
                },
            )
            result = self._detail(identity, row)
            check_cancelled()
            return result
