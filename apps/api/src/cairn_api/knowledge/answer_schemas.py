from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cairn_api.knowledge.schemas import KnowledgeCitation, normalize_search_query


class KnowledgeAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value: object) -> object:
        return normalize_search_query(value) if isinstance(value, str) else value


class KnowledgeAnswerParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    text: str = Field(min_length=1, max_length=1000)
    citation_ids: list[str] = Field(
        alias="citationIds", serialization_alias="citationIds", min_length=1, max_length=6
    )


class KnowledgeAnswerCitation(KnowledgeCitation):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(pattern=r"^S[1-6]$")


class KnowledgeAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["answered", "insufficient_evidence"]
    retrieval_mode: Literal["hybrid", "keyword_fallback"] = Field(
        alias="retrievalMode", serialization_alias="retrievalMode"
    )
    paragraphs: list[KnowledgeAnswerParagraph] = Field(max_length=8)
    citations: list[KnowledgeAnswerCitation] = Field(max_length=6)

    @model_validator(mode="after")
    def validate_answer_invariants(self) -> "KnowledgeAnswerResponse":
        if self.status == "insufficient_evidence":
            if self.paragraphs or self.citations:
                raise ValueError("insufficient evidence cannot include content")
            return self
        if not self.paragraphs or not self.citations:
            raise ValueError("answered responses require paragraphs and citations")
        citation_ids = [citation.id for citation in self.citations]
        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("citation ids must be unique")
        known = set(citation_ids)
        for paragraph in self.paragraphs:
            if len(paragraph.citation_ids) != len(set(paragraph.citation_ids)):
                raise ValueError("paragraph citation ids must be unique")
            if not set(paragraph.citation_ids) <= known:
                raise ValueError("paragraph references an unknown citation")
        return self


__all__ = [
    "KnowledgeAnswerCitation",
    "KnowledgeAnswerParagraph",
    "KnowledgeAnswerRequest",
    "KnowledgeAnswerResponse",
]
