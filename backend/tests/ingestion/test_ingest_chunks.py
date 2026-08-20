from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from postgrest import ReturnMethod

from ingestion.chunk_documents import PreparedChunk
from ingestion.ingest_chunks import (
    build_document_chunk_rows,
    upsert_document_chunks,
    validate_stored_source_documents,
)
from ingestion.ingest_documents import SourceDocumentRow

UPDATED_AT = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)


def test_build_document_chunk_rows_populates_retrieval_metadata() -> None:
    document_id = str(uuid4())
    source_row = _source_row()
    chunk = PreparedChunk(
        chunk_index=0,
        text="Risk Factors\nRevenue concentration is a risk.",
        token_count=9,
        page_number=None,
        section_title="Risk Factors",
        source_start=120,
        source_end=152,
        metadata={"contains_table": False, "doc_item_refs": ["#/texts/1"]},
    )
    embedding = [0.1] * 1_536

    rows = build_document_chunk_rows(
        source_row,
        document_id,
        [chunk],
        [embedding],
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1_536,
        updated_at=UPDATED_AT,
    )

    assert rows == [
        {
            "document_id": document_id,
            "chunk_index": 0,
            "text": "Risk Factors\nRevenue concentration is a risk.",
            "token_count": 9,
            "page_number": None,
            "section_title": "Risk Factors",
            "source_start": 120,
            "source_end": 152,
            "metadata": {
                "contains_table": False,
                "doc_item_refs": ["#/texts/1"],
                "company": "Apple Inc.",
                "ticker": "AAPL",
                "filing_type": "10-K",
                "filing_date": "2024-11-01",
                "report_date": "2024-09-28",
                "filing_year": "2024",
                "accession_number": "0000320193-24-000123",
                "sec_url": "https://www.sec.gov/example.htm",
                "content_checksum": "abc123",
                "page_number": None,
                "section_title": "Risk Factors",
                "source_start": 120,
                "source_end": 152,
                "embedding_model": "text-embedding-3-small",
                "embedding_dimensions": 1_536,
            },
            "embedding": embedding,
            "updated_at": "2026-08-19T14:00:00+00:00",
        }
    ]


def test_build_document_chunk_rows_rejects_schema_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="document_chunks.embedding requires 1536"):
        build_document_chunk_rows(
            _source_row(),
            str(uuid4()),
            [],
            [],
            embedding_model="text-embedding-3-small",
            embedding_dimensions=3,
        )


def test_validate_stored_source_documents_checks_presence_and_checksum() -> None:
    source_row = _source_row()

    with pytest.raises(ValueError, match="missing accessions"):
        validate_stored_source_documents([source_row], {})

    with pytest.raises(ValueError, match="does not match"):
        validate_stored_source_documents(
            [source_row],
            {
                source_row["accession_number"]: {
                    "id": str(uuid4()),
                    "accession_number": source_row["accession_number"],
                    "content_checksum": "different",
                }
            },
        )


def test_upsert_document_chunks_uses_stable_index_and_removes_stale_tail() -> None:
    document_id = str(uuid4())
    rows = [
        _chunk_row(document_id, 0),
        _chunk_row(document_id, 1),
        _chunk_row(document_id, 2),
    ]
    upsert_execute = AsyncMock(return_value=SimpleNamespace(data=[]))
    delete_execute = AsyncMock(return_value=SimpleNamespace(data=[]))
    delete_query = MagicMock()
    delete_query.eq.return_value = delete_query
    delete_query.gt.return_value = SimpleNamespace(execute=delete_execute)
    table = MagicMock()
    table.upsert.return_value = SimpleNamespace(execute=upsert_execute)
    table.delete.return_value = delete_query
    client = MagicMock()
    client.table.return_value = table

    asyncio.run(upsert_document_chunks(client, rows, batch_size=2))

    client.table.assert_called_once_with("document_chunks")
    assert table.upsert.call_count == 2
    assert table.upsert.call_args_list[0].kwargs == {
        "on_conflict": "document_id,chunk_index",
        "returning": ReturnMethod.minimal,
    }
    assert table.upsert.call_args_list[0].args == (rows[:2],)
    assert table.upsert.call_args_list[1].args == (rows[2:],)
    table.delete.assert_called_once_with(returning=ReturnMethod.minimal)
    delete_query.eq.assert_called_once_with("document_id", document_id)
    delete_query.gt.assert_called_once_with("chunk_index", 2)
    assert upsert_execute.await_count == 2
    delete_execute.assert_awaited_once_with()


def _source_row() -> SourceDocumentRow:
    return {
        "company": "Apple Inc.",
        "ticker": "AAPL",
        "filing_type": "10-K",
        "filing_date": "2024-11-01",
        "report_date": "2024-09-28",
        "accession_number": "0000320193-24-000123",
        "sec_url": "https://www.sec.gov/example.htm",
        "normalized_markdown": "# Filing",
        "extraction_metadata": {},
        "content_checksum": "abc123",
        "updated_at": "2026-08-19T14:00:00+00:00",
    }


def _chunk_row(document_id: str, chunk_index: int) -> dict[str, object]:
    return {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "text": f"Chunk {chunk_index}",
        "token_count": 2,
        "page_number": None,
        "section_title": None,
        "source_start": None,
        "source_end": None,
        "metadata": {},
        "embedding": [0.1] * 1_536,
        "updated_at": "2026-08-19T14:00:00+00:00",
    }
