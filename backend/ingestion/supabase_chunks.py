"""Build and store Supabase document chunk rows from local checkpoints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import UUID

from postgrest import ReturnMethod

from app.database.document_chunks import EMBEDDING_DIMENSIONS
from ingestion.chunk_documents import CHUNKER_VERSION, PreparedChunk
from ingestion.ingest_documents import SourceDocumentRow
from ingestion.sec_parser import PARSER_VERSION

if TYPE_CHECKING:
    from supabase import AsyncClient


SOURCE_DOCUMENT_COLUMNS = "id,accession_number,content_checksum"
DATABASE_BATCH_SIZE = 10


class StoredSourceDocument(TypedDict):
    id: str
    accession_number: str
    content_checksum: str


class DocumentChunkRow(TypedDict):
    document_id: str
    chunk_index: int
    text: str
    token_count: int
    page_number: int | None
    section_title: str | None
    source_start: int | None
    source_end: int | None
    metadata: dict[str, object]
    display_table: dict[str, object] | None
    embedding: list[float]
    updated_at: str


def _database_string(row: dict[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise TypeError(f"Supabase field {field!r} must be a non-empty string")
    return value


async def load_stored_source_documents(
    client: AsyncClient,
    accession_numbers: Sequence[str],
) -> dict[str, StoredSourceDocument]:
    response = await (
        client.table("source_documents")
        .select(SOURCE_DOCUMENT_COLUMNS)
        .in_("accession_number", list(accession_numbers))
        .execute()
    )
    records = {}
    for value in response.data:
        if not isinstance(value, dict):
            raise TypeError("Supabase returned an invalid source_documents row")
        record = cast(dict[str, object], value)
        document_id = _database_string(record, "id")
        accession_number = _database_string(record, "accession_number")
        content_checksum = _database_string(record, "content_checksum")
        UUID(document_id)
        records[accession_number] = {
            "id": document_id,
            "accession_number": accession_number,
            "content_checksum": content_checksum,
        }
    return records


def validate_stored_source_documents(
    source_rows: Sequence[SourceDocumentRow],
    stored_documents: dict[str, StoredSourceDocument],
) -> None:
    missing_accessions = sorted(
        row["accession_number"]
        for row in source_rows
        if row["accession_number"] not in stored_documents
    )
    if missing_accessions:
        raise ValueError(
            "Run source-document ingestion first; Supabase is missing accessions: "
            + ", ".join(missing_accessions)
        )

    mismatched_accessions = sorted(
        row["accession_number"]
        for row in source_rows
        if stored_documents[row["accession_number"]]["content_checksum"]
        != row["content_checksum"]
    )
    if mismatched_accessions:
        raise ValueError(
            "Local Markdown does not match source_documents for accessions: "
            + ", ".join(mismatched_accessions)
        )


def build_document_chunk_rows(
    source_row: SourceDocumentRow,
    document_id: str,
    chunks: Sequence[PreparedChunk],
    embeddings: Sequence[list[float]],
    *,
    embedding_model: str,
    embedding_dimensions: int,
    updated_at: datetime | None = None,
) -> list[DocumentChunkRow]:
    if len(chunks) != len(embeddings):
        raise ValueError("Every chunk must have exactly one embedding")
    if embedding_dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Configured embedding dimensions are {embedding_dimensions}, but "
            f"document_chunks.embedding requires {EMBEDDING_DIMENSIONS}"
        )
    UUID(document_id)

    timestamp = (updated_at or datetime.now(UTC)).isoformat()
    filing_year = source_row["report_date"][:4]
    rows = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        if len(embedding) != embedding_dimensions:
            raise ValueError(
                f"Chunk {chunk.chunk_index} embedding has {len(embedding)} dimensions; "
                f"expected {embedding_dimensions}"
            )
        metadata = {
            **chunk.metadata,
            "company": source_row["company"],
            "ticker": source_row["ticker"],
            "filing_type": source_row["filing_type"],
            "filing_date": source_row["filing_date"],
            "report_date": source_row["report_date"],
            "filing_year": filing_year,
            "accession_number": source_row["accession_number"],
            "sec_url": source_row["sec_url"],
            "content_checksum": source_row["content_checksum"],
            "page_number": chunk.page_number,
            "section_title": chunk.section_title,
            "source_start": chunk.source_start,
            "source_end": chunk.source_end,
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_dimensions,
        }
        rows.append(
            DocumentChunkRow(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                source_start=chunk.source_start,
                source_end=chunk.source_end,
                metadata=metadata,
                display_table=(
                    chunk.display_table.model_dump(mode="json")
                    if chunk.display_table is not None
                    else None
                ),
                embedding=list(embedding),
                updated_at=timestamp,
            )
        )
    return rows


async def upsert_document_chunks(
    client: AsyncClient,
    rows: Sequence[DocumentChunkRow],
    *,
    batch_size: int = DATABASE_BATCH_SIZE,
) -> None:
    if not rows:
        raise ValueError("At least one document chunk is required")
    if batch_size <= 0:
        raise ValueError("Database batch size must be positive")
    document_ids = {row["document_id"] for row in rows}
    if len(document_ids) != 1:
        raise ValueError("One upsert call may contain chunks for only one document")

    table = client.table("document_chunks")
    for start in range(0, len(rows), batch_size):
        await table.upsert(
            list(rows[start : start + batch_size]),
            on_conflict="document_id,chunk_index",
            returning=ReturnMethod.minimal,
        ).execute()

    document_id = rows[0]["document_id"]
    last_chunk_index = rows[-1]["chunk_index"]
    await (
        table.delete(returning=ReturnMethod.minimal)
        .eq("document_id", document_id)
        .gt("chunk_index", last_chunk_index)
        .execute()
    )


async def validate_existing_chunk_version(
    client: AsyncClient,
    source_row: SourceDocumentRow,
    document_id: str,
) -> None:
    response = await (
        client.table("document_chunks")
        .select("metadata")
        .eq("document_id", document_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return
    value = response.data[0]
    if not isinstance(value, dict) or not isinstance(value.get("metadata"), dict):
        raise TypeError("Supabase returned invalid existing chunk metadata")
    metadata = cast(dict[str, object], value["metadata"])
    expected = {
        "parser_version": PARSER_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "content_checksum": source_row["content_checksum"],
    }
    mismatches = [
        key
        for key, expected_value in expected.items()
        if metadata.get(key) != expected_value
    ]
    if mismatches:
        raise ValueError(
            "Existing chunks were produced from a different parser, chunker, or "
            "document. Run ingestion.reset_ingestion before replacing them: "
            + ", ".join(mismatches)
        )
