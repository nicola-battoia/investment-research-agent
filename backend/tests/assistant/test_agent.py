import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.assistant.agent import DocumentAssistant
from app.assistant.deps import AssistantDeps, AssistantModelSettings
from app.assistant.policy import INVESTMENT_ADVICE_STATEMENT
from app.grounding.validator import GroundingFailureError, GroundingValidator
from app.retrieval.models import (
    ExtractedKeywords,
    KeywordGroup,
    RetrievalResult,
    SourcePassage,
)

PASSAGE_TEXT = (
    "Services net sales increased because of higher advertising and cloud services "
    "revenue during the fiscal year."
)


def passage() -> SourcePassage:
    return SourcePassage(
        chunk_id=UUID(int=1),
        document_id=UUID(int=100),
        chunk_index=10,
        text=PASSAGE_TEXT,
        token_count=30,
        page_number=12,
        section_title="Results of Operations",
        source_start=100,
        source_end=100 + len(PASSAGE_TEXT),
        metadata={},
        company="Apple Inc.",
        ticker="AAPL",
        filing_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        accession_number="0000320193-24-000123",
        sec_url="https://www.sec.gov/example",
    )


def retrieval_result() -> RetrievalResult:
    return RetrievalResult(
        passages=(passage(),),
        keywords=ExtractedKeywords(
            groups=(KeywordGroup(terms=("Services", "net sales")),)
        ),
    )


def empty_retrieval_result() -> RetrievalResult:
    return RetrievalResult(
        passages=(),
        keywords=ExtractedKeywords(
            groups=(KeywordGroup(terms=("Services", "net sales")),)
        ),
    )


def make_deps(retriever: object) -> AssistantDeps:
    return AssistantDeps(
        user_id=UUID(int=500),
        thread_id=UUID(int=600),
        retriever=retriever,
        grounding_validator=GroundingValidator(),
        model_settings=AssistantModelSettings(
            model_name="function-test",
            reasoning_effort="medium",
            max_output_tokens=3000,
        ),
    )


def grounded_output() -> dict[str, object]:
    return {
        "status": "supported",
        "answer": "Services grew from advertising and cloud revenue [S1].",
        "citations": [
            {
                "source_id": "S1",
                "excerpt": (
                    "higher advertising and cloud services revenue during the fiscal year"
                ),
            }
        ],
    }


def test_agent_searches_reads_and_returns_only_validated_answer() -> None:
    calls = 0

    def model_function(_messages, _info) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_filings",
                        {"query": "growth", "filters": None},
                        "search-1",
                    )
                ]
            )
        if calls == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_filings",
                        {"query": "Apple Services growth", "filters": None},
                        "search-2",
                    )
                ]
            )
        if calls == 3:
            return ModelResponse(
                parts=[ToolCallPart("read_chunk", {"source_id": "S1"}, "read-1")]
            )
        return ModelResponse(parts=[TextPart(content=json.dumps(grounded_output()))])

    retriever = SimpleNamespace(
        search=AsyncMock(side_effect=[empty_retrieval_result(), retrieval_result()]),
        surrounding_chunks=AsyncMock(),
    )

    result = asyncio.run(
        DocumentAssistant(FunctionModel(model_function)).run(
            "What drove Services growth?",
            make_deps(retriever),
        )
    )

    assert result.answer.status == "supported"
    assert result.answer.citations[0].source_id == "S1"
    assert result.usage.requests == 4
    assert result.usage.tool_calls == 3
    assert retriever.search.await_count == 2


def test_agent_retries_one_invalid_grounded_output_then_succeeds() -> None:
    calls = 0

    def model_function(_messages, _info) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[ToolCallPart("search_filings", {"query": "Services"}, "s")]
            )
        if calls == 2:
            return ModelResponse(
                parts=[ToolCallPart("read_chunk", {"source_id": "S1"}, "r")]
            )
        if calls == 3:
            return ModelResponse(
                parts=[
                    TextPart(
                        content=json.dumps(
                            {
                                "status": "supported",
                                "answer": "An uncited answer.",
                                "citations": [],
                            }
                        )
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content=json.dumps(grounded_output()))])

    retriever = SimpleNamespace(search=AsyncMock(return_value=retrieval_result()))

    result = asyncio.run(
        DocumentAssistant(FunctionModel(model_function)).run(
            "What drove Services growth?",
            make_deps(retriever),
        )
    )

    assert result.answer.status == "supported"
    assert result.usage.requests == 4


def test_agent_raises_controlled_failure_after_grounding_retry() -> None:
    calls = 0

    def model_function(_messages, _info) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[ToolCallPart("search_filings", {"query": "Services"}, "s")]
            )
        return ModelResponse(
            parts=[
                TextPart(
                    content=json.dumps(
                        {
                            "status": "supported",
                            "answer": "An uncited answer.",
                            "citations": [],
                        }
                    )
                )
            ]
        )

    retriever = SimpleNamespace(search=AsyncMock(return_value=retrieval_result()))

    with pytest.raises(GroundingFailureError, match="after correction"):
        asyncio.run(
            DocumentAssistant(FunctionModel(model_function)).run(
                "What drove Services growth?",
                make_deps(retriever),
            )
        )
    assert calls == 3


def test_agent_can_refuse_pure_investment_advice_without_searching() -> None:
    output = {
        "status": "investment_advice_refused",
        "answer": INVESTMENT_ADVICE_STATEMENT,
        "citations": [],
    }

    def model_function(_messages, _info) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=json.dumps(output))])

    retriever = SimpleNamespace(search=AsyncMock())
    result = asyncio.run(
        DocumentAssistant(FunctionModel(model_function)).run(
            "Should I buy this stock?",
            make_deps(retriever),
        )
    )

    assert result.answer.status == "investment_advice_refused"
    assert result.answer.citations == ()
    retriever.search.assert_not_awaited()
