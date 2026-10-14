from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel

from cairn_api.knowledge.answer_models import AnswerModelOption
from cairn_api.knowledge.answer_protocols import AnswerProtocol
from cairn_api.knowledge.answer_schemas import (
    KnowledgeAnswerParagraph,
    KnowledgeAnswerRequest,
    KnowledgeAnswerResponse,
)


class KnowledgeAnswerModelStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configured: bool
    model: str | None
    protocol: AnswerProtocol | None
    default_model_id: str | None = Field(alias="defaultModelId")
    models: list[AnswerModelOption]


class KnowledgeConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID


class KnowledgeConversationTurnRequest(KnowledgeAnswerRequest):
    id: UUID
    expected_revision: int = Field(alias="expectedRevision", strict=True, gt=0)
    assistant_revision: int = Field(default=0, alias="assistantRevision", strict=True, ge=0)
    skill_id: str | None = Field(default=None, alias="skillId", min_length=1, max_length=64)


class KnowledgeConversationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, from_attributes=True)
    id: UUID
    title: str = Field(min_length=1, max_length=60)
    revision: int = Field(ge=1, le=51)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class KnowledgeConversationTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: UUID
    sequence: int = Field(ge=1, le=50)
    question: str = Field(min_length=3, max_length=500)
    answer: KnowledgeAnswerResponse | None
    assistant_name: str = Field(default="岑宁", alias="assistantName")
    assistant_id: UUID | None = Field(default=None, alias="assistantId")
    assistant_revision: int = Field(default=0, alias="assistantRevision", ge=0)
    skill_id: str | None = Field(default=None, alias="skillId")
    model: AnswerModelOption | None = None
    answer_unavailable: bool = Field(alias="answerUnavailable")
    context_truncated: bool = Field(alias="contextTruncated")
    created_at: datetime = Field(alias="createdAt")


class KnowledgeConversationResponse(KnowledgeConversationSummary):
    turns: list[KnowledgeConversationTurnResponse] = Field(max_length=50)


class KnowledgeConversationPage(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    items: list[KnowledgeConversationSummary]
    next_cursor: str | None = Field(alias="nextCursor")


class KnowledgeConversationParagraphEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: Literal["paragraph"]
    conversation_id: UUID = Field(alias="conversationId")
    turn_id: UUID = Field(alias="turnId")
    index: int = Field(strict=True, ge=0, le=7)
    paragraph: KnowledgeAnswerParagraph


class KnowledgeConversationCompleteEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: Literal["complete"]
    conversation_id: UUID = Field(alias="conversationId")
    turn_id: UUID = Field(alias="turnId")
    conversation: KnowledgeConversationResponse


class KnowledgeConversationErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: Literal["error"]
    conversation_id: UUID = Field(alias="conversationId")
    turn_id: UUID = Field(alias="turnId")
    status: int = Field(strict=True, ge=400, le=599)
    code: str
    message: str
    trace_id: str = Field(alias="traceId")
    retry_after: str | None = Field(alias="retryAfter")


class KnowledgeConversationStreamEvent(
    RootModel[
        Annotated[
            KnowledgeConversationParagraphEvent
            | KnowledgeConversationCompleteEvent
            | KnowledgeConversationErrorEvent,
            Field(discriminator="type"),
        ]
    ]
):
    pass
