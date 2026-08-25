"""The only bounded retrieval capabilities exposed to the document agent."""

from __future__ import annotations

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai import ModelRetry, RunContext

from app.assistant.deps import AssistantDeps
from app.assistant.evidence import EvidenceLimitError, UnknownSourceError
from app.assistant.outputs import ReadablePassage, SearchToolResult
from app.retrieval.models import RetrievalFilters

MAX_SEARCH_CALLS = 3
MAX_SURROUNDING_CALLS = 3
SEARCH_RESULT_LIMIT = 10
SEARCH_CANDIDATE_LIMIT = 50
MAX_SEARCH_QUERY_CHARACTERS = 500


class FilingSearchFilters(BaseModel):
    """Explicit filing scope for one model-controlled search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    companies: tuple[str, ...] = Field(default=(), max_length=5)
    tickers: tuple[str, ...] = Field(default=(), max_length=5)
    filing_types: tuple[str, ...] = Field(default=(), max_length=3)
    filing_years: tuple[int, ...] = Field(default=(), max_length=5)
    filed_on_or_after: date | None = None
    filed_on_or_before: date | None = None
    corpus_wide: bool = False

    @model_validator(mode="after")
    def require_explicit_scope(self) -> Self:
        has_filing_filter = bool(
            self.companies
            or self.tickers
            or self.filing_types
            or self.filing_years
            or self.filed_on_or_after
            or self.filed_on_or_before
        )
        if not has_filing_filter and not self.corpus_wide:
            raise ValueError(
                "A filing search requires at least one filter or corpus_wide=true"
            )
        if has_filing_filter and self.corpus_wide:
            raise ValueError(
                "corpus_wide=true cannot be combined with filing filters"
            )
        return self

    def to_retrieval_filters(self) -> RetrievalFilters:
        return RetrievalFilters(
            companies=self.companies,
            tickers=self.tickers,
            filing_types=self.filing_types,
            filing_years=self.filing_years,
            filed_on_or_after=self.filed_on_or_after,
            filed_on_or_before=self.filed_on_or_before,
        )


async def search_filings(
    ctx: RunContext[AssistantDeps],
    query: str,
    filters: FilingSearchFilters,
) -> SearchToolResult:
    """Search SEC filings with hybrid retrieval.

    Args:
        query: Focused evidence question or SEC filing concepts to retrieve.
        filters: Required explicit search scope. Supply at least one company,
            ticker, form, fiscal year, or filing-date filter; use corpus_wide=true
            only for an intentionally corpus-wide search.
    """
    query = query.strip()
    if not query:
        raise ModelRetry("The filing search query cannot be empty")
    if len(query) > MAX_SEARCH_QUERY_CHARACTERS:
        raise ModelRetry(
            f"The filing search query cannot exceed {MAX_SEARCH_QUERY_CHARACTERS} characters"
        )
    if ctx.deps.counters.search_calls >= MAX_SEARCH_CALLS:
        raise ModelRetry(
            "The maximum of three filing searches is exhausted; answer from current "
            "evidence or return insufficient_evidence"
        )
    ctx.deps.counters.search_calls += 1

    result = await ctx.deps.retriever.search(
        query,
        filters.to_retrieval_filters(),
        limit=SEARCH_RESULT_LIMIT,
        candidate_limit=SEARCH_CANDIDATE_LIMIT,
    )
    try:
        ranked = tuple(ctx.deps.evidence.preview(item) for item in result.passages)
        context = tuple(
            ctx.deps.evidence.preview(item) for item in result.context_passages
        )
    except EvidenceLimitError as error:
        raise ModelRetry(str(error)) from error
    return SearchToolResult(
        query=query,
        lexical_query=result.keywords.search_text,
        ranked_passages=ranked,
        context_passages=context,
    )


async def read_chunk(
    ctx: RunContext[AssistantDeps],
    source_id: str,
) -> ReadablePassage:
    """Read one complete passage previously returned by search_filings.

    Args:
        source_id: Current-turn source label such as S1; arbitrary UUIDs are forbidden.
    """
    try:
        passage = ctx.deps.evidence.require(source_id)
    except UnknownSourceError as error:
        raise ModelRetry(str(error)) from error
    return ctx.deps.evidence.readable(passage)


async def read_surrounding_chunks(
    ctx: RunContext[AssistantDeps],
    source_id: str,
) -> tuple[ReadablePassage, ...]:
    """Read at most two immediate neighbors of a current-turn source.

    Args:
        source_id: Current-turn source label whose adjacent chunks are needed.
    """
    if ctx.deps.counters.surrounding_calls >= MAX_SURROUNDING_CALLS:
        raise ModelRetry("The maximum of three surrounding-chunk reads is exhausted")
    try:
        anchor = ctx.deps.evidence.require(source_id)
    except UnknownSourceError as error:
        raise ModelRetry(str(error)) from error
    ctx.deps.counters.surrounding_calls += 1
    passages = await ctx.deps.retriever.surrounding_chunks(
        anchor.chunk_id,
        radius=1,
    )
    try:
        return tuple(ctx.deps.evidence.readable(item) for item in passages[:2])
    except EvidenceLimitError as error:
        raise ModelRetry(str(error)) from error
