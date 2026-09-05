import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from openai.types import CreateEmbeddingResponse
from openai.types.responses import ResponseUsage

from app.assistant.deps import AssistantDeps, AssistantModelSettings
from app.assistant.tools import FilingSearchFilters
from app.config import settings
from app.grounding import GroundingValidator
from app.retrieval.keywords import (
    KEYWORD_EXTRACTION_INSTRUCTIONS,
    OpenAIKeywordExtractor,
)
from app.retrieval.models import (
    ExtractedKeywords,
    KeywordGroup,
    RetrievalResult,
    SourcePassage,
)
from app.retrieval.queries import RankedCandidate
from app.retrieval.retriever import DocumentRetriever
from app.services import AzureOpenAIService
from evaluation.inspect_search_tool import (
    _provider_usage,
    create_inspection_trace,
    run_search_inspection,
)


@pytest.fixture(autouse=True)
def no_network_or_tokenizer_download(monkeypatch):
    send = AsyncMock(side_effect=AssertionError("Inspection must not send HTTP"))
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    encoding = SimpleNamespace(encode=lambda text, **_kwargs: list(text))
    monkeypatch.setattr(
        "evaluation.inspect_search_tool.tiktoken.get_encoding", lambda _name: encoding
    )
    yield
    send.assert_not_awaited()


def _passage(index: int, text: str) -> SourcePassage:
    return SourcePassage(
        chunk_id=UUID(int=index),
        document_id=UUID(int=100),
        chunk_index=index,
        text=text,
        token_count=30,
        page_number=12,
        section_title="Results of Operations",
        source_start=index * 10,
        source_end=index * 10 + len(text),
        metadata={},
        company="Apple Inc.",
        ticker="AAPL",
        filing_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        accession_number="0000320193-24-000123",
        sec_url="https://www.sec.gov/example",
    )


def _dependencies():
    ranked = _passage(1, "Services  net sales\n" * 100)
    bridge = _passage(2, "The adjacent bridge supplies context.")
    retrieval = RetrievalResult(
        passages=(ranked,),
        context_passages=(bridge,),
        keywords=ExtractedKeywords(
            groups=(KeywordGroup(terms=("Services", "net sales")),)
        ),
    )
    retriever = SimpleNamespace(search=AsyncMock(return_value=retrieval))
    trace = create_inspection_trace()
    deps = AssistantDeps(
        user_id=UUID(int=500),
        thread_id=UUID(int=600),
        retriever=retriever,
        grounding_validator=GroundingValidator(),
        model_settings=AssistantModelSettings.from_app_settings(settings),
        trace=trace,
    )
    return deps, trace, retriever


async def _inspect(query, deps, trace, filters=None):
    async with AzureOpenAIService(settings) as service:
        model = service.create_responses_model(
            settings.azure_openai_assistant_deployment,
            settings.openai_assistant_model,
        )
        return await run_search_inspection(
            query,
            filters or FilingSearchFilters(tickers=("AAPL",)),
            deps,
            model,
            trace,
        )


def test_inspection_uses_real_registered_tool_and_exact_followup_output() -> None:
    deps, trace, retriever = _dependencies()
    inspection = asyncio.run(_inspect("  Services growth  ", deps, trace))

    assert inspection.metadata["available_tool_count"] == 3
    assert inspection.metadata["available_tool_names"] == [
        "search_filings",
        "read_chunk",
        "read_surrounding_chunks",
    ]
    assert [tool["name"] for tool in inspection.tool_definitions] == (
        inspection.metadata["available_tool_names"]
    )
    search_definition = inspection.tool_definitions[0]
    assert search_definition["type"] == "function"
    assert set(search_definition["parameters"]["properties"]) == {"query", "filters"}
    assert inspection.metadata["result_limit"] == settings.assistant_search_result_limit
    assert inspection.metadata["candidate_limit_per_branch"] == (
        settings.assistant_search_candidate_limit
    )
    assert inspection.metadata["tool_timeout_seconds"] == (
        settings.assistant_tool_timeout_seconds
    )
    assert inspection.metadata["max_search_calls_per_turn"] == (
        settings.assistant_max_search_calls
    )
    retriever.search.assert_awaited_once_with(
        "Services growth",
        FilingSearchFilters(tickers=("AAPL",)).to_retrieval_filters(),
        limit=settings.assistant_search_result_limit,
        candidate_limit=settings.assistant_search_candidate_limit,
    )
    assert inspection.metadata["status"] == "success"
    assert inspection.metadata["submitted_tool_calls"] == 1
    assert inspection.metadata["successful_tool_calls"] == 1
    assert inspection.metadata["search_calls"] == 1
    assert inspection.arguments["query"] == "  Services growth  "
    assert inspection.metadata["normalized_query"] == "Services growth"

    assert inspection.result is not None
    assert inspection.result.ranked_passages[0].source_id == "S1"
    assert inspection.result.context_passages[0].source_id == "S2"
    expected_preview = " ".join(deps.evidence.require("S1").text.split())
    expected_preview = (
        expected_preview[: settings.assistant_evidence_preview_characters].rstrip()
        + "…"
    )
    assert inspection.result.ranked_passages[0].preview == expected_preview
    assert inspection.evidence == deps.evidence.passages
    assert set(inspection.evidence) == {"S1", "S2"}
    assert deps.evidence.read_source_ids == frozenset()
    assert inspection.metadata["ranked_passage_count"] == 1
    assert inspection.metadata["context_passage_count"] == 1
    assert inspection.metadata["registered_evidence_count"] == 2

    assert inspection.output_text == inspection.result.model_dump_json()
    assert (
        json.loads(inspection.output_text)["context_passages"][0]["source_id"] == "S2"
    )
    followup = inspection.assistant_followup_content["input"]
    tool_call = next(item for item in followup if item.get("type") == "function_call")
    tool_output = next(
        item for item in followup if item.get("type") == "function_call_output"
    )
    assert tool_call["name"] == "search_filings"
    assert json.loads(tool_call["arguments"]) == inspection.arguments
    assert tool_call["call_id"] == tool_output["call_id"] == "inspect-search-1"
    assert tool_output["output"] == inspection.output_text
    assert inspection.assistant_request_content["tools"] == inspection.tool_definitions
    assert inspection.assistant_request_content["text"]["format"]["name"] == (
        "grounded_document_answer"
    )
    assert inspection.metadata["assistant_model_requests_sent"] == 0
    assert inspection.metadata["assistant_provider_usage"] is None
    assert deps.validated_answer is None
    assert not any(
        event["stage"].startswith("assistant.model") for event in inspection.events
    )


def test_inspection_token_counts_are_separate_estimates_not_fabricated_usage() -> None:
    deps, trace, _retriever = _dependencies()
    inspection = asyncio.run(_inspect("Services growth", deps, trace))

    tokens = inspection.token_metadata
    assert tokens["encoding"] == "o200k_base"
    assert tokens["measurement"] == (
        "Local text estimates, not provider-reported assistant usage."
    )
    assert tokens["query_text_tokens_estimate"] == len("Services growth")
    assert tokens["tool_result_tokens_estimate"] == len(inspection.output_text)
    assert tokens["tool_definitions_tokens_estimate"] > 0
    assert (
        tokens["assistant_followup_content_tokens_estimate"]
        > (tokens["assistant_request_content_tokens_estimate"])
    )
    assert (
        tokens["production_followup_input_tokens_estimate"]
        > (tokens["production_preflight_input_tokens_estimate"])
    )
    assert "INPUT to the next assistant request" in tokens["note"]
    assert inspection.provider_usage == []
    assert inspection.metadata["assistant_provider_usage"] is None


def test_inspection_rejects_reused_dependencies_and_new_turn_restarts_source_ids() -> (
    None
):
    deps, trace, retriever = _dependencies()
    first = asyncio.run(_inspect("Services", deps, trace))
    with pytest.raises(ValueError, match="cannot be reused"):
        asyncio.run(_inspect("Services", deps, trace))
    retriever.search.assert_awaited_once()

    fresh_deps, fresh_trace, fresh_retriever = _dependencies()
    second = asyncio.run(_inspect("Services", fresh_deps, fresh_trace))
    assert first.result.ranked_passages[0].source_id == "S1"
    assert second.result.ranked_passages[0].source_id == "S1"
    fresh_retriever.search.assert_awaited_once()


@pytest.mark.parametrize("query", ["", " \n\t "])
def test_empty_query_returns_real_model_retry_without_retrieval(query: str) -> None:
    deps, trace, retriever = _dependencies()
    inspection = asyncio.run(_inspect(query, deps, trace))

    retriever.search.assert_not_awaited()
    assert inspection.metadata["status"] == "retry_required"
    assert inspection.result is None
    assert "The filing search query cannot be empty" in inspection.output_text
    assert inspection.metadata["successful_tool_calls"] == 0
    assert inspection.metadata["search_calls"] == 0
    assert inspection.evidence == {}
    outputs = [
        item
        for item in inspection.assistant_followup_content["input"]
        if item.get("type") == "function_call_output"
    ]
    assert outputs[0]["output"] == inspection.output_text


def test_invalid_filter_arguments_are_revalidated_by_registered_dispatcher() -> None:
    deps, trace, retriever = _dependencies()
    invalid_filters = FilingSearchFilters.model_construct(corpus_wide=False)
    inspection = asyncio.run(_inspect("Services", deps, trace, invalid_filters))

    retriever.search.assert_not_awaited()
    assert inspection.metadata["status"] == "retry_required"
    assert inspection.result is None
    assert "at least one filter or corpus_wide=true" in inspection.output_text
    assert any(
        event["event"] == "assistant_tool_validation_failed"
        for event in inspection.events
    )


@pytest.mark.parametrize("usage", [None, {}])
def test_provider_usage_keeps_missing_counts_unavailable(usage) -> None:
    rows = _provider_usage(
        {
            "retrieval.embedding.response": {"model": "embedding", "usage": usage},
            "retrieval.keywords.response": {"model": "keywords", "usage": usage},
        }
    )

    assert len(rows) == 2
    for row in rows:
        assert row["measurement"] == "unavailable"
        assert row["input_tokens"] is None
        assert row["output_tokens"] is None
        assert row["total_tokens"] is None
        assert row["raw_usage"] == usage


def test_provider_usage_preserves_real_zero_and_maps_embedding_and_keyword_usage() -> (
    None
):
    embedding_usage = {"prompt_tokens": 0, "total_tokens": 0}
    keyword_usage = {"input_tokens": 27, "output_tokens": 13, "total_tokens": 40}
    rows = _provider_usage(
        {
            "retrieval.embedding.response": {
                "model": "embedding",
                "duration_ms": 4,
                "usage": embedding_usage,
            },
            "retrieval.keywords.response": {
                "model": "keywords",
                "duration_ms": 9,
                "usage": keyword_usage,
            },
        }
    )

    assert rows[0]["role"] == "embedding"
    assert rows[0]["measurement"] == "provider_reported"
    assert rows[0]["input_tokens"] == rows[0]["total_tokens"] == 0
    assert rows[0]["output_tokens"] is None
    assert rows[0]["raw_usage"] == embedding_usage
    assert rows[1]["role"] == "keywords"
    assert rows[1]["measurement"] == "provider_reported"
    assert rows[1]["input_tokens"] == 27
    assert rows[1]["output_tokens"] == 13
    assert rows[1]["total_tokens"] == 40
    assert rows[1]["duration_ms"] == 9
    assert rows[1]["raw_usage"] == keyword_usage


def test_real_retrieval_pipeline_captures_usage_and_hydrates_bridge(
    monkeypatch,
) -> None:
    first = _passage(1, "Services net sales increased.")
    last = _passage(3, "Cloud services contributed to growth.")
    bridge = _passage(2, "Advertising also contributed to the increase.")
    candidates = [
        RankedCandidate(first.chunk_id, 0.9),
        RankedCandidate(last.chunk_id, 0.8),
    ]
    semantic = AsyncMock(return_value=candidates)
    lexical = AsyncMock(return_value=candidates)
    hydrate = AsyncMock(return_value=[first, last])
    hydrate_keys = AsyncMock(return_value=[bridge])
    for name, boundary in (
        ("semantic_search", semantic),
        ("lexical_search", lexical),
        ("hydrate_passages", hydrate),
        ("hydrate_passage_keys", hydrate_keys),
    ):
        monkeypatch.setattr(f"app.retrieval.retriever.{name}", boundary)

    vector = [0.25] * settings.openai_embedding_dimensions
    embedding_response = CreateEmbeddingResponse(
        data=[{"object": "embedding", "index": 0, "embedding": vector}],
        model=settings.azure_openai_embedding_deployment,
        object="list",
        usage={"prompt_tokens": 7, "total_tokens": 7},
    )
    keyword_usage = ResponseUsage(
        input_tokens=81,
        output_tokens=19,
        total_tokens=100,
        input_tokens_details={"cached_tokens": 30, "cache_write_tokens": 0},
        output_tokens_details={"reasoning_tokens": 4},
    )
    keywords = ExtractedKeywords(
        groups=(KeywordGroup(terms=("Services", "net sales")),)
    )
    embedding_create = AsyncMock(return_value=embedding_response)
    keyword_parse = AsyncMock(
        return_value=SimpleNamespace(
            id="keyword-response-1",
            output_parsed=keywords,
            usage=keyword_usage,
        )
    )
    azure_client = SimpleNamespace(
        embeddings=SimpleNamespace(create=embedding_create),
        responses=SimpleNamespace(parse=keyword_parse),
    )
    supabase = SimpleNamespace()
    deps, trace, _unused_fake_retriever = _dependencies()
    deps.retriever = DocumentRetriever(
        supabase,
        azure_client,
        OpenAIKeywordExtractor(
            azure_client,
            model=settings.azure_openai_keyword_deployment,
            trace=trace,
        ),
        embedding_model=settings.azure_openai_embedding_deployment,
        embedding_dimensions=settings.openai_embedding_dimensions,
        trace=trace,
    )
    filters = FilingSearchFilters(tickers=(" aapl ",), filing_types=("10-k",))
    inspection = asyncio.run(_inspect("  Services net sales  ", deps, trace, filters))

    embedding_create.assert_awaited_once_with(
        input=["Services net sales"],
        model=settings.azure_openai_embedding_deployment,
        dimensions=settings.openai_embedding_dimensions,
    )
    keyword_parse.assert_awaited_once_with(
        model=settings.azure_openai_keyword_deployment,
        instructions=KEYWORD_EXTRACTION_INSTRUCTIONS,
        input="Services net sales",
        text_format=ExtractedKeywords,
        max_output_tokens=settings.openai_keyword_max_output_tokens,
        store=settings.openai_store_responses,
    )
    normalized_filters = filters.to_retrieval_filters()
    assert normalized_filters.tickers == ("AAPL",)
    assert normalized_filters.filing_types == ("10-K",)
    semantic.assert_awaited_once_with(
        supabase,
        vector,
        normalized_filters,
        settings.assistant_search_candidate_limit,
    )
    lexical.assert_awaited_once_with(
        supabase,
        "Services net sales",
        normalized_filters,
        settings.assistant_search_candidate_limit,
    )
    hydrate.assert_awaited_once_with(supabase, [first.chunk_id, last.chunk_id])
    hydrate_keys.assert_awaited_once_with(supabase, {first.document_id: {2}})

    assert inspection.result is not None
    assert [
        (p.source_id, p.chunk_index, p.passage_kind)
        for p in inspection.result.ranked_passages
    ] == [
        ("S1", 1, "ranked"),
        ("S2", 3, "ranked"),
    ]
    assert [
        (p.source_id, p.chunk_index, p.passage_kind)
        for p in inspection.result.context_passages
    ] == [
        ("S3", 2, "neighbor"),
    ]
    assert inspection.result.context_passages[0].preview == bridge.text
    assert inspection.output_text == inspection.result.model_dump_json()
    assert inspection.evidence["S1"].semantic_rank == 1
    assert inspection.evidence["S1"].lexical_rank == 1
    assert inspection.evidence["S1"].fused_score > inspection.evidence["S2"].fused_score

    stages = inspection.stages
    assert {
        "retrieval.search.started",
        "retrieval.embedding.request",
        "retrieval.embedding.response",
        "retrieval.keywords.request",
        "retrieval.keywords.response",
        "retrieval.semantic.completed",
        "retrieval.lexical.completed",
        "retrieval.fusion.completed",
        "retrieval.bridge.completed",
        "retrieval.search.completed",
    } <= stages.keys()
    for stage in (
        "retrieval.embedding.request",
        "retrieval.keywords.request",
        "retrieval.search.completed",
    ):
        assert sum(event["stage"] == stage for event in inspection.events) == 1
    assert stages["retrieval.search.started"][
        "filters"
    ] == normalized_filters.model_dump(mode="json")
    assert stages["retrieval.semantic.completed"]["candidate_count"] == 2
    assert stages["retrieval.lexical.completed"]["candidate_count"] == 2
    assert stages["retrieval.fusion.completed"]["fused_count"] == 2
    assert stages["retrieval.bridge.completed"]["requested_count"] == 1
    assert stages["retrieval.search.completed"]["hydration_ms"] >= 0
    assert stages["retrieval.search.completed"]["context_passage_count"] == 1
    usage_by_role = {row["role"]: row for row in inspection.provider_usage}
    assert set(usage_by_role) == {"embedding", "keywords"}
    assert usage_by_role["embedding"]["measurement"] == "provider_reported"
    assert usage_by_role["embedding"]["input_tokens"] == 7
    assert usage_by_role["embedding"][
        "raw_usage"
    ] == embedding_response.usage.model_dump(mode="json")
    assert usage_by_role["keywords"]["measurement"] == "provider_reported"
    assert usage_by_role["keywords"]["input_tokens"] == 81
    assert usage_by_role["keywords"]["output_tokens"] == 19
    assert usage_by_role["keywords"]["total_tokens"] == 100
    assert usage_by_role["keywords"]["raw_usage"] == keyword_usage.model_dump(
        mode="json"
    )
    assert inspection.metadata["search_calls"] == 1
    assert inspection.metadata["assistant_model_requests_sent"] == 0
    assert inspection.metadata["assistant_provider_usage"] is None
