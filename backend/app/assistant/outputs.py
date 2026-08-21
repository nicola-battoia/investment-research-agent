"""Typed model output, validated assistant output, and tool-facing passage views."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_ai.usage import RunUsage

SOURCE_ID_PATTERN = r"^S[1-9][0-9]*$"

AnswerStatus = Literal[
    "supported",
    "insufficient_evidence",
    "investment_advice_refused",
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CitationReference(FrozenModel):
    """A model-proposed reference to evidence retrieved during this turn."""

    source_id: str = Field(pattern=SOURCE_ID_PATTERN)
    excerpt: str = Field(min_length=20, max_length=500)

    @field_validator("excerpt")
    @classmethod
    def normalize_excerpt(cls, value: str) -> str:
        return " ".join(value.split())


class DraftGroundedAnswer(FrozenModel):
    """Strict native structured output produced by the model."""

    status: AnswerStatus
    answer: str = Field(min_length=1, max_length=10_000)
    citations: tuple[CitationReference, ...] = Field(default=(), max_length=20)

    @field_validator("answer")
    @classmethod
    def normalize_answer(cls, value: str) -> str:
        return value.strip()


class Citation(FrozenModel):
    """A validated citation resolved entirely from a retrieved source passage."""

    source_id: str = Field(pattern=SOURCE_ID_PATTERN)
    citation_index: int = Field(ge=0)
    chunk_id: UUID
    document_id: UUID
    chunk_index: int = Field(ge=0)
    excerpt: str = Field(min_length=20, max_length=500)
    company: str
    ticker: str
    filing_type: str
    filing_date: date
    report_date: date
    accession_number: str
    sec_url: str
    page_number: int | None = Field(default=None, gt=0)
    section_title: str | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, gt=0)


class GroundedAnswer(FrozenModel):
    """Only answer type allowed to cross the assistant boundary successfully."""

    status: AnswerStatus
    answer: str
    citations: tuple[Citation, ...] = ()


class AssistantUsage(FrozenModel):
    """Stable, persistence-friendly subset of PydanticAI run usage."""

    requests: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cost_usd: Decimal | None = Field(default=None, ge=0)
    details: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_run_usage(cls, usage: RunUsage) -> AssistantUsage:
        return cls(
            requests=usage.requests,
            tool_calls=usage.tool_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cost_usd=usage.cost,
            details=usage.details,
        )


class AssistantRunResult(FrozenModel):
    """Validated answer plus the model usage needed by Phase 9 persistence."""

    answer: GroundedAnswer
    usage: AssistantUsage


class HistoryMessage(FrozenModel):
    """One prior persisted message supplied to the assistant runner."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10_000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("History message cannot be empty")
        return value


class PassagePreview(FrozenModel):
    """Bounded search result shown before the model selects a chunk to read."""

    source_id: str = Field(pattern=SOURCE_ID_PATTERN)
    passage_kind: Literal["ranked", "neighbor"]
    company: str
    ticker: str
    filing_type: str
    filing_date: date
    report_date: date
    accession_number: str
    chunk_index: int = Field(ge=0)
    page_number: int | None = Field(default=None, gt=0)
    section_title: str | None = None
    preview: str


class ReadablePassage(FrozenModel):
    """Full current-turn passage returned by a bounded read tool."""

    source_id: str = Field(pattern=SOURCE_ID_PATTERN)
    passage_kind: Literal["ranked", "neighbor"]
    company: str
    ticker: str
    filing_type: str
    filing_date: date
    report_date: date
    accession_number: str
    sec_url: str
    chunk_index: int = Field(ge=0)
    page_number: int | None = Field(default=None, gt=0)
    section_title: str | None = None
    text: str


class SearchToolResult(FrozenModel):
    """Auditable result returned by the hybrid search tool."""

    query: str
    lexical_query: str
    ranked_passages: tuple[PassagePreview, ...]
    context_passages: tuple[PassagePreview, ...]
