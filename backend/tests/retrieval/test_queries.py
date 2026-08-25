import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.retrieval.models import RetrievalFilters
from app.retrieval.queries import (
    LEXICAL_RPC,
    SEMANTIC_RPC,
    hydrate_passages,
    lexical_rpc_params,
    lexical_search,
    semantic_rpc_params,
    semantic_search,
)

CHUNK_ID = UUID("00000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000002")


class FakeQuery:
    def __init__(self, data: list[object]) -> None:
        self.data = data
        self.calls: list[tuple[str, object]] = []

    def select(self, columns: str) -> "FakeQuery":
        self.calls.append(("select", columns))
        return self

    def in_(self, column: str, values: list[object]) -> "FakeQuery":
        self.calls.append(("in", (column, values)))
        return self

    async def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.data)


class FakeClient:
    def __init__(self, rpc_data: list[object] | None = None) -> None:
        self.rpc_data = rpc_data or []
        self.rpc_calls: list[tuple[str, dict[str, object]]] = []
        self.table_query: FakeQuery | None = None

    def rpc(self, name: str, params: dict[str, object]) -> FakeQuery:
        self.rpc_calls.append((name, params))
        return FakeQuery(self.rpc_data)

    def table(self, name: str) -> FakeQuery:
        assert name == "document_chunks"
        assert self.table_query is not None
        return self.table_query


def test_rpc_params_apply_every_normalized_filter() -> None:
    filters = RetrievalFilters(
        companies=("Apple Inc.",),
        tickers=("aapl",),
        filing_types=("10-k",),
        filing_years=(2024,),
        filed_on_or_after=date(2024, 1, 1),
        filed_on_or_before=date(2024, 12, 31),
    )

    semantic = semantic_rpc_params([0.1, 0.2], filters, 50)
    lexical = lexical_rpc_params("  cloud revenue  ", filters, 50)

    expected_filters = {
        "p_match_count": 50,
        "p_companies": ["apple inc."],
        "p_tickers": ["AAPL"],
        "p_filing_types": ["10-K"],
        "p_filing_years": [2024],
        "p_filed_on_or_after": "2024-01-01",
        "p_filed_on_or_before": "2024-12-31",
    }
    assert semantic == {"p_query_embedding": [0.1, 0.2], **expected_filters}
    assert lexical == {"p_query_text": "cloud revenue", **expected_filters}


@pytest.mark.parametrize(
    ("filters", "parameter", "expected"),
    [
        (RetrievalFilters(companies=("Apple Inc.",)), "p_companies", ["apple inc."]),
        (RetrievalFilters(tickers=("aapl",)), "p_tickers", ["AAPL"]),
        (RetrievalFilters(filing_types=("10-k",)), "p_filing_types", ["10-K"]),
        (RetrievalFilters(filing_years=(2024,)), "p_filing_years", [2024]),
        (
            RetrievalFilters(filed_on_or_after=date(2024, 1, 1)),
            "p_filed_on_or_after",
            "2024-01-01",
        ),
        (
            RetrievalFilters(filed_on_or_before=date(2024, 12, 31)),
            "p_filed_on_or_before",
            "2024-12-31",
        ),
    ],
)
def test_rpc_params_apply_each_filter_individually(
    filters: RetrievalFilters,
    parameter: str,
    expected: object,
) -> None:
    params = lexical_rpc_params("query", filters, 50)

    assert params[parameter] == expected


@pytest.mark.parametrize("limit", [0, 101])
def test_rpc_params_enforce_candidate_bounds(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        lexical_rpc_params("query", RetrievalFilters(), limit)


def test_searches_use_the_supplied_client_and_validate_rows() -> None:
    client = FakeClient([{"chunk_id": str(CHUNK_ID), "score": 0.75}])

    semantic = asyncio.run(semantic_search(client, [0.1], RetrievalFilters(), 10))
    lexical = asyncio.run(lexical_search(client, "query", RetrievalFilters(), 10))

    assert semantic[0].chunk_id == CHUNK_ID
    assert lexical[0].score == 0.75
    assert [call[0] for call in client.rpc_calls] == [SEMANTIC_RPC, LEXICAL_RPC]


def test_search_rejects_malformed_rpc_rows() -> None:
    client = FakeClient([{"chunk_id": str(CHUNK_ID), "score": "high"}])

    with pytest.raises(TypeError, match="score must be numeric"):
        asyncio.run(lexical_search(client, "query", RetrievalFilters(), 10))


def test_hydration_returns_requested_order_and_source_metadata() -> None:
    second_id = UUID("00000000-0000-0000-0000-000000000003")
    client = FakeClient()
    first = passage_row(CHUNK_ID, 4)
    second = passage_row(second_id, 5)
    client.table_query = FakeQuery([second, first])

    passages = asyncio.run(hydrate_passages(client, [CHUNK_ID, second_id]))

    assert [passage.chunk_id for passage in passages] == [CHUNK_ID, second_id]
    assert passages[0].ticker == "AAPL"
    assert passages[0].filing_date == date(2024, 11, 1)
    select_call = client.table_query.calls[0]
    assert select_call[0] == "select"
    assert "display_table" in str(select_call[1])


def passage_row(chunk_id: UUID, chunk_index: int) -> dict[str, object]:
    return {
        "id": str(chunk_id),
        "document_id": str(DOCUMENT_ID),
        "chunk_index": chunk_index,
        "text": f"Passage {chunk_index}",
        "token_count": 10,
        "page_number": 1,
        "section_title": "Revenue",
        "source_start": 0,
        "source_end": 10,
        "metadata": {"contains_table": False},
        "display_table": None,
        "source_documents": {
            "company": "Apple Inc.",
            "ticker": "AAPL",
            "filing_type": "10-K",
            "filing_date": "2024-11-01",
            "report_date": "2024-09-28",
            "accession_number": "0000320193-24-000123",
            "sec_url": "https://www.sec.gov/example",
        },
    }
