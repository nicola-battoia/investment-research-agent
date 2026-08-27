"""The only bounded retrieval capabilities exposed to the document agent."""

from __future__ import annotations

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai import ModelRetry, RunContext

from app.assistant.deps import AssistantDeps
from app.assistant.evidence import EvidenceLimitError, UnknownSourceError
from app.assistant.outputs import ReadablePassage, SearchToolResult
from app.config import settings
from app.retrieval.models import RetrievalFilters


class FilingSearchFilters(BaseModel):
    """Explicit filing scope for one model-controlled search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    companies: tuple[str, ...] = Field(
        default=(),
        max_length=settings.assistant_max_filter_companies,
    )
    tickers: tuple[str, ...] = Field(
        default=(),
        max_length=settings.assistant_max_filter_tickers,
    )
    filing_types: tuple[str, ...] = Field(
        default=(),
        max_length=settings.assistant_max_filter_filing_types,
    )
    filing_years: tuple[int, ...] = Field(
        default=(),
        max_length=settings.assistant_max_filter_filing_years,
    )
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
            raise ValueError("corpus_wide=true cannot be combined with filing filters")
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
    if len(query) > settings.assistant_max_search_query_characters:
        raise ModelRetry(
            "The filing search query cannot exceed "
            f"{settings.assistant_max_search_query_characters} characters"
        )
    if ctx.deps.counters.search_calls >= settings.assistant_max_search_calls:
        raise ModelRetry(
            f"The maximum of {settings.assistant_max_search_calls} filing searches "
            "is exhausted; answer from current evidence or return insufficient_evidence"
        )
    ctx.deps.counters.search_calls += 1

    result = await ctx.deps.retriever.search(
        query,
        filters.to_retrieval_filters(),
        limit=settings.assistant_search_result_limit,
        candidate_limit=settings.assistant_search_candidate_limit,
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
    if ctx.deps.counters.surrounding_calls >= settings.assistant_max_surrounding_calls:
        raise ModelRetry(
            f"The maximum of {settings.assistant_max_surrounding_calls} "
            "surrounding-chunk reads is exhausted"
        )
    try:
        anchor = ctx.deps.evidence.require(source_id)
    except UnknownSourceError as error:
        raise ModelRetry(str(error)) from error
    ctx.deps.counters.surrounding_calls += 1
    passages = await ctx.deps.retriever.surrounding_chunks(
        anchor.chunk_id,
        radius=settings.assistant_surrounding_chunk_radius,
    )
    try:
        return tuple(
            ctx.deps.evidence.readable(item)
            for item in passages[: settings.assistant_max_surrounding_chunks]
        )
    except EvidenceLimitError as error:
        raise ModelRetry(str(error)) from error
