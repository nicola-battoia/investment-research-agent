import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from app.retrieval.fusion import FusedRank
from app.retrieval.models import ExtractedKeywords, KeywordGroup, SourcePassage
from app.retrieval.queries import RankedCandidate
from app.retrieval.retriever import RetrievalCandidates, RetrievalTimings
from evaluation.inspect_retrieval import inspect_retrieval

SEMANTIC_ID = UUID(int=1)
LEXICAL_ID = UUID(int=2)
DOCUMENT_ID = UUID(int=10)


def _passage(chunk_id: UUID, index: int) -> SourcePassage:
    return SourcePassage(
        chunk_id=chunk_id,
        document_id=DOCUMENT_ID,
        chunk_index=index,
        text=f"Retrieved evidence for chunk {index}.",
        token_count=10,
        page_number=1,
        section_title="Results of Operations",
        source_start=index * 10,
        source_end=index * 10 + 9,
        metadata={},
        company="Apple Inc.",
        ticker="AAPL",
        filing_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        accession_number="0000320193-24-000123",
        sec_url="https://www.sec.gov/example",
    )


def test_inspector_logs_and_returns_branch_passages(capsys) -> None:
    details = RetrievalCandidates(
        semantic=(RankedCandidate(SEMANTIC_ID, 0.91),),
        lexical=(RankedCandidate(LEXICAL_ID, 0.42),),
        hybrid=(
            FusedRank(SEMANTIC_ID, 0.33, {"semantic": 1}),
            FusedRank(LEXICAL_ID, 0.02, {"lexical": 1}),
        ),
        keywords=ExtractedKeywords(
            groups=(KeywordGroup(terms=("Services", "net sales")),)
        ),
        timings=RetrievalTimings(120.0, 180.0, 0.2, 181.0),
    )
    retriever = SimpleNamespace(candidate_details=AsyncMock(return_value=details))
    client = SimpleNamespace()
    passages = [_passage(SEMANTIC_ID, 10), _passage(LEXICAL_ID, 20)]

    with patch(
        "evaluation.inspect_retrieval.hydrate_passages",
        AsyncMock(return_value=passages),
    ) as hydrate:
        result = asyncio.run(
            inspect_retrieval(
                "What drove Services net sales?",
                show=2,
                retriever=retriever,
                client=client,
            )
        )

    assert result.candidates is details
    assert [passage.chunk_id for passage in result.semantic_passages] == [SEMANTIC_ID]
    assert [passage.chunk_id for passage in result.lexical_passages] == [LEXICAL_ID]
    assert [passage.chunk_id for passage in result.hybrid_passages] == [
        SEMANTIC_ID,
        LEXICAL_ID,
    ]
    retriever.candidate_details.assert_awaited_once()
    hydrate.assert_awaited_once_with(client, [SEMANTIC_ID, LEXICAL_ID])
    output = capsys.readouterr().err
    assert "KEYWORDS" in output
    assert "SEMANTIC RESULTS" in output
    assert "LEXICAL RESULTS" in output
    assert "HYBRID RESULTS" in output
