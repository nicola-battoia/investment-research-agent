"""The only bounded retrieval capabilities exposed to the document agent."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field
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
    """Small model-controlled subset of explicit Phase 7 filing filters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    companies: tuple[str, ...] = Field(default=(), max_length=5)
    tickers: tuple[str, ...] = Field(default=(), max_length=5)
    filing_types: tuple[str, ...] = Field(default=(), max_length=3)
    filing_years: tuple[int, ...] = Field(default=(), max_length=5)
    filed_on_or_after: date | None = None
    filed_on_or_before: date | None = None

    def to_retrieval_filters(self) -> RetrievalFilters:
        return RetrievalFilters.model_validate(self.model_dump())


async def search_filings(
    ctx: RunContext[AssistantDeps],
    query: str,
    filters: FilingSearchFilters | None = None,
) -> SearchToolResult:
    """Search SEC filings with hybrid retrieval.

    Args:
        query: Focused evidence question or SEC filing concepts to retrieve.
        filters: Optional company, ticker, form, fiscal year, or filing-date filters.
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
        (filters or FilingSearchFilters()).to_retrieval_filters(),
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
