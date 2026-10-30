from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.responses import StreamingResponse

from cairn_api.auth.csrf import CSRF_REQUIRED_OPENAPI, require_mutation_csrf
from cairn_api.auth.dependencies import CurrentIdentity
from cairn_api.knowledge.answer_service import KnowledgeAnswerService
from cairn_api.knowledge.conversation_schemas import (
    KnowledgeAnswerModelStatus,
    KnowledgeConversationCreateRequest,
    KnowledgeConversationPage,
    KnowledgeConversationResponse,
    KnowledgeConversationStreamEvent,
    KnowledgeConversationTurnRequest,
)
from cairn_api.knowledge.conversation_service import KnowledgeConversationService
from cairn_api.knowledge.dependencies import (
    AnswerModelsDependency,
    AnswerProviderDependency,
    EmbeddingClientDependency,
)
from cairn_api.knowledge.router import (
    ANSWER_ERRORS,
    REQUEST_ID_HEADER,
    AuditContext,
    SessionDependency,
    SettingsDependency,
)
from cairn_api.knowledge.search_service import KnowledgeSearchService

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/knowledge", tags=["knowledge-conversations"]
)


def get_conversation_service(
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
) -> KnowledgeConversationService:
    return KnowledgeConversationService(
        session, identity, request.cookies.get(settings.session_cookie_name), audit
    )


ConversationService = Annotated[KnowledgeConversationService, Depends(get_conversation_service)]
RESPONSES = {200: {"headers": REQUEST_ID_HEADER}, **ANSWER_ERRORS}
MUTATION = [Depends(require_mutation_csrf)]


@router.get("/answer-model", response_model=KnowledgeAnswerModelStatus, responses=RESPONSES)
def answer_model_status(
    project_id: UUID,
    service: ConversationService,
    models: AnswerModelsDependency,
) -> KnowledgeAnswerModelStatus:
    service.model_authorize(project_id)
    default = next(iter(models.values()), None)
    return KnowledgeAnswerModelStatus(
        configured=default is not None,
        model=default.info.model if default is not None else None,
        protocol=default.info.protocol if default is not None else None,
        defaultModelId=default.info.id if default is not None else None,
        models=[item.info for item in models.values()],
    )


@router.get("/conversations", response_model=KnowledgeConversationPage, responses=RESPONSES)
def list_conversations(
    project_id: UUID,
    service: ConversationService,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    current_assistant: Annotated[bool, Query(alias="currentAssistant")] = False,
) -> KnowledgeConversationPage:
    return service.list(project_id, cursor=cursor, limit=limit, current_assistant=current_assistant)


@router.post(
    "/conversations",
    response_model=KnowledgeConversationResponse,
    status_code=201,
    responses={
        **RESPONSES,
        200: {"model": KnowledgeConversationResponse, "headers": REQUEST_ID_HEADER},
        201: {"headers": REQUEST_ID_HEADER},
    },
    dependencies=MUTATION,
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def create_conversation(
    project_id: UUID,
    payload: KnowledgeConversationCreateRequest,
    response: Response,
    service: ConversationService,
) -> KnowledgeConversationResponse:
    detail, created = service.create(project_id, payload.id)
    response.status_code = 201 if created else 200
    return detail


@router.get(
    "/conversations/{conversation_id}",
    response_model=KnowledgeConversationResponse,
    responses=RESPONSES,
)
def read_conversation(
    project_id: UUID, conversation_id: UUID, service: ConversationService
) -> KnowledgeConversationResponse:
    return service.read(project_id, conversation_id)


@router.post(
    "/conversations/{conversation_id}/turns",
    response_model=KnowledgeConversationResponse,
    responses=RESPONSES,
    dependencies=MUTATION,
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
def append_conversation_turn(
    project_id: UUID,
    conversation_id: UUID,
    payload: KnowledgeConversationTurnRequest,
    request: Request,
    identity: CurrentIdentity,
    session: SessionDependency,
    audit: AuditContext,
    settings: SettingsDependency,
    embedding: EmbeddingClientDependency,
    provider: AnswerProviderDependency,
    models: AnswerModelsDependency,
) -> KnowledgeConversationResponse:
    search = KnowledgeSearchService(
        session,
        embedding,
        user_limit=settings.search_user_limit_per_minute,
        org_limit=settings.search_org_limit_per_minute,
        audit_secret=settings.search_audit_secret.get_secret_value(),
    )
    answer = KnowledgeAnswerService(
        session, search, provider, audit_secret=settings.search_audit_secret.get_secret_value()
    )
    service = KnowledgeConversationService(
        session, identity, request.cookies.get(settings.session_cookie_name), audit, answer,
        answer_models=models,
    )
    return service.append(
        project_id,
        conversation_id,
        turn_id=payload.id,
        expected_revision=payload.expected_revision,
        question=payload.question,
        assistant_revision=payload.assistant_revision,
        skill_id=payload.skill_id,
    )


@router.post(
    "/conversations/{conversation_id}/turns/stream",
    # Register the event component without declaring an automatic response media type.
    # Returning StreamingResponse bypasses response-model serialization at runtime.
    response_model=KnowledgeConversationStreamEvent,
    response_class=StreamingResponse,
    responses={
        **{
            status: {
                **description,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ErrorBody"}}
                },
            }
            for status, description in ANSWER_ERRORS.items()
        },
        200: {
            "description": "SSE data frames containing discriminated paragraph, complete or error events. Only complete acknowledges a committed turn.",
            "headers": REQUEST_ID_HEADER,
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/KnowledgeConversationStreamEvent"}
                }
            },
        },
    },
    dependencies=MUTATION,
    openapi_extra=CSRF_REQUIRED_OPENAPI,
)
async def stream_conversation_turn(
    project_id: UUID,
    conversation_id: UUID,
    payload: KnowledgeConversationTurnRequest,
    request: Request,
    identity: CurrentIdentity,
    audit: AuditContext,
    settings: SettingsDependency,
    embedding: EmbeddingClientDependency,
    provider: AnswerProviderDependency,
    models: AnswerModelsDependency,
) -> StreamingResponse:
    from cairn_api.knowledge.conversation_streaming import conversation_stream

    def build_service() -> KnowledgeConversationService:
        session = request.app.state.database.session_factory()
        try:
            search = KnowledgeSearchService(
                session,
                embedding,
                user_limit=settings.search_user_limit_per_minute,
                org_limit=settings.search_org_limit_per_minute,
                audit_secret=settings.search_audit_secret.get_secret_value(),
            )
            answer = KnowledgeAnswerService(
                session,
                search,
                provider,
                audit_secret=settings.search_audit_secret.get_secret_value(),
            )
            return KnowledgeConversationService(
                session, identity, request.cookies.get(settings.session_cookie_name), audit, answer,
                answer_models=models,
            )
        except BaseException:
            session.close()
            raise

    def append(
        service: KnowledgeConversationService, **hooks: Any
    ) -> KnowledgeConversationResponse:
        return service.append(
            project_id,
            conversation_id,
            turn_id=payload.id,
            expected_revision=payload.expected_revision,
            question=payload.question,
            assistant_revision=payload.assistant_revision,
            skill_id=payload.skill_id,
            **hooks,
        )

    return await conversation_stream(
        request,
        build_service=build_service,
        append=append,
        conversation_id=conversation_id,
        turn_id=payload.id,
        trace_id=audit.trace_id,
    )
