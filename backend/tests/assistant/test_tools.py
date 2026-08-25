import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from app.assistant.deps import AssistantDeps, AssistantModelSettings
from app.assistant.evidence import EvidenceLimitError, TurnEvidence
from app.assistant.tools import (
    FilingSearchFilters,
    read_chunk,
    read_surrounding_chunks,
    search_filings,
)
from app.grounding.validator import GroundingValidator
from app.retrieval.models import (
    ExtractedKeywords,
    KeywordGroup,
    RetrievalFilters,
    RetrievalResult,
    SourcePassage,
)

USER_ID = UUID(int=500)
THREAD_ID = UUID(int=600)


def passage(value: int, *, kind: str = "ranked") -> SourcePassage:
    return SourcePassage(
        chunk_id=UUID(int=value),
        document_id=UUID(int=100),
        chunk_index=value,
        text=("Full retrieved filing evidence. " * 30) + str(value),
        token_count=100,
        page_number=10,
        section_title="Results of Operations",
        source_start=value * 1_000,
        source_end=value * 1_000 + 900,
        metadata={},
        company="Apple Inc.",
        ticker="AAPL",
        filing_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        accession_number="0000320193-24-000123",
        sec_url="https://www.sec.gov/example",
        passage_kind=kind,
    )


def retrieval_result() -> RetrievalResult:
    return RetrievalResult(
        passages=(passage(1),),
        context_passages=(passage(2, kind="neighbor"),),
        keywords=ExtractedKeywords(
            groups=(KeywordGroup(terms=("Services", "net sales")),)
        ),
    )


def deps(retriever: object) -> AssistantDeps:
    return AssistantDeps(
        user_id=USER_ID,
        thread_id=THREAD_ID,
        retriever=retriever,
        grounding_validator=GroundingValidator(),
        model_settings=AssistantModelSettings(
            model_name="test",
            reasoning_effort="medium",
            max_output_tokens=3000,
        ),
    )


def test_search_uses_fixed_bounds_filters_and_stable_source_ids() -> None:
    retriever = SimpleNamespace(
        search=AsyncMock(return_value=retrieval_result()),
        surrounding_chunks=AsyncMock(),
    )
    context = SimpleNamespace(deps=deps(retriever))
    filters = FilingSearchFilters(
        companies=("Apple Inc.",),
        tickers=("aapl",),
        filing_types=("10-k",),
        filing_years=(2024,),
        filed_on_or_after=date(2024, 1, 1),
        filed_on_or_before=date(2024, 12, 31),
    )

    first = asyncio.run(search_filings(context, " Services growth ", filters))
    second = asyncio.run(search_filings(context, "Services growth", filters))

    assert first.query == "Services growth"
    assert first.lexical_query == "Services net sales"
    assert first.ranked_passages[0].source_id == "S1"
    assert first.context_passages[0].source_id == "S2"
    assert second.ranked_passages[0].source_id == "S1"
    assert len(first.ranked_passages[0].preview) <= 601
    call = retriever.search.await_args_list[0]
    assert call.kwargs == {"limit": 10, "candidate_limit": 50}
    retrieval_filters = call.args[1]
    assert retrieval_filters.companies == ("apple inc.",)
    assert retrieval_filters.tickers == ("AAPL",)
    assert retrieval_filters.filing_types == ("10-K",)


def test_search_rejects_a_fourth_attempt() -> None:
    retriever = SimpleNamespace(search=AsyncMock(return_value=retrieval_result()))
    context = SimpleNamespace(deps=deps(retriever))
    filters = FilingSearchFilters(corpus_wide=True)

    for _ in range(3):
        asyncio.run(search_filings(context, "Services", filters))

    with pytest.raises(ModelRetry, match="maximum of three"):
        asyncio.run(search_filings(context, "One more search", filters))
    assert retriever.search.await_count == 3


def test_search_scope_requires_filters_or_explicit_corpus_wide() -> None:
    with pytest.raises(ValidationError, match="at least one filter"):
        FilingSearchFilters()

    with pytest.raises(ValidationError, match="cannot be combined"):
        FilingSearchFilters(tickers=("AAPL",), corpus_wide=True)

    corpus_wide = FilingSearchFilters(corpus_wide=True)

    assert corpus_wide.to_retrieval_filters() == RetrievalFilters()


def test_read_requires_current_turn_source_and_marks_it_read() -> None:
    active_deps = deps(SimpleNamespace())
    active_deps.evidence.register(passage(1))
    context = SimpleNamespace(deps=active_deps)

    result = asyncio.run(read_chunk(context, "S1"))

    assert result.source_id == "S1"
    assert result.text.startswith("Full retrieved")
    assert active_deps.evidence.read_source_ids == {"S1"}
    with pytest.raises(ModelRetry, match="not evidence retrieved"):
        asyncio.run(read_chunk(context, "S99"))


def test_surrounding_read_is_fixed_to_radius_one_and_two_results() -> None:
    retriever = SimpleNamespace(
        surrounding_chunks=AsyncMock(
            return_value=[
                passage(2, kind="neighbor"),
                passage(3, kind="neighbor"),
                passage(4, kind="neighbor"),
            ]
        )
    )
    active_deps = deps(retriever)
    active_deps.evidence.register(passage(1))
    context = SimpleNamespace(deps=active_deps)

    results = asyncio.run(read_surrounding_chunks(context, "S1"))

    assert [item.source_id for item in results] == ["S2", "S3"]
    assert active_deps.evidence.read_source_ids == {"S2", "S3"}
    retriever.surrounding_chunks.assert_awaited_once_with(UUID(int=1), radius=1)


def test_evidence_registry_enforces_limit_and_dependencies_are_single_use() -> None:
    evidence = TurnEvidence(max_passages=1)
    evidence.register(passage(1))

    with pytest.raises(EvidenceLimitError, match="at most 1"):
        evidence.register(passage(2))

    active_deps = deps(SimpleNamespace())
    active_deps.evidence.register(passage(1))
    with pytest.raises(ValueError, match="cannot be reused"):
        active_deps.require_fresh_run()
