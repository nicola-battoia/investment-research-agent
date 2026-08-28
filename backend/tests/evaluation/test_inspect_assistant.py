import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from app.assistant.agent import DocumentAssistant
from app.assistant.deps import AssistantDeps, AssistantModelSettings
from app.grounding import GroundingValidator
from app.retrieval.models import (
    ExtractedKeywords,
    KeywordGroup,
    RetrievalResult,
    SourcePassage,
)
from evaluation.inspect_assistant import run_assistant_inspection

PASSAGE_TEXT = (
    "Services net sales increased because of higher advertising and cloud services "
    "revenue during the fiscal year."
)


def test_inspection_runs_real_agent_loop_and_returns_evidence_trace() -> None:
    passage = SourcePassage(
        chunk_id=UUID(int=1),
        document_id=UUID(int=2),
        chunk_index=10,
        text=PASSAGE_TEXT,
        token_count=20,
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
    retrieval_result = RetrievalResult(
        passages=(passage,),
        keywords=ExtractedKeywords(
            groups=(KeywordGroup(terms=("Services", "net sales")),)
        ),
    )
    calls = 0

    async def stream_function(_messages, _info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {
                0: DeltaToolCall(
                    name="search_filings",
                    json_args=json.dumps(
                        {
                            "query": "Services",
                            "filters": {"corpus_wide": True},
                        }
                    ),
                    tool_call_id="s",
                )
            }
        elif calls == 2:
            yield {
                0: DeltaToolCall(
                    name="read_chunk",
                    json_args=json.dumps({"source_id": "S1"}),
                    tool_call_id="r",
                )
            }
        else:
            output = {
                "status": "supported",
                "answer": "Services grew from advertising and cloud revenue [S1].",
                "citations": [
                    {
                        "source_id": "S1",
                        "excerpt": (
                            "higher advertising and cloud services revenue during the "
                            "fiscal year"
                        ),
                    }
                ],
            }
            yield json.dumps(output)

    retriever = SimpleNamespace(
        search=AsyncMock(return_value=retrieval_result),
        surrounding_chunks=AsyncMock(),
    )
    deps = AssistantDeps(
        user_id=UUID(int=3),
        thread_id=UUID(int=4),
        retriever=retriever,
        grounding_validator=GroundingValidator(),
        model_settings=AssistantModelSettings(
            model_name="function-test",
            reasoning_effort="medium",
            max_output_tokens=3000,
        ),
    )

    inspection = asyncio.run(
        run_assistant_inspection(
            "What drove Services growth?",
            DocumentAssistant(
                FunctionModel(stream_function=stream_function),
                count_tokens_before_request=False,
            ),
            deps,
        )
    )

    assert inspection.result.answer.status == "supported"
    assert inspection.search_calls == 1
    assert inspection.surrounding_calls == 0
    assert len(inspection.evidence) == 1
    assert inspection.evidence[0].source_id == "S1"
    assert inspection.evidence[0].was_read is True
    assert inspection.evidence[0].was_cited is True
