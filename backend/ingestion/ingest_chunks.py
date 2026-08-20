"""Chunk, embed, and upsert SEC filing passages into document_chunks."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import UUID

from openai import AsyncOpenAI
from postgrest import ReturnMethod

from app.database.document_chunks import EMBEDDING_DIMENSIONS
from ingestion.chunk_documents import (
    OpenAITokenCounter,
    PreparedChunk,
    chunk_document,
    document_paths,
)
from ingestion.create_embeddings import EmbeddingClient, create_embeddings
from ingestion.ingest_documents import SourceDocumentRow, load_source_document_rows

if TYPE_CHECKING:
    from supabase import AsyncClient


SOURCE_DOCUMENT_COLUMNS = "id,accession_number,content_checksum"
DATABASE_BATCH_SIZE = 10

logger = logging.getLogger(__name__)


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
    embedding: list[float]
    updated_at: str


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


async def ingest_document_chunks(
    source_rows: Sequence[SourceDocumentRow],
    supabase_client: AsyncClient,
    embedding_client: EmbeddingClient,
    *,
    embedding_model: str,
    embedding_dimensions: int,
) -> tuple[int, int]:
    stored_documents = await load_stored_source_documents(
        supabase_client,
        [row["accession_number"] for row in source_rows],
    )
    validate_stored_source_documents(source_rows, stored_documents)
    if embedding_dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Configured embedding dimensions are {embedding_dimensions}, but "
            f"document_chunks.embedding requires {EMBEDDING_DIMENSIONS}"
        )

    token_counter = OpenAITokenCounter(embedding_model)
    total_chunks = 0
    total_tokens = 0
    for document_index, source_row in enumerate(source_rows, start=1):
        accession_number = source_row["accession_number"]
        docling_path, markdown_path = document_paths(source_row)
        chunks = chunk_document(docling_path, markdown_path, token_counter)
        embedding_result = await create_embeddings(
            embedding_client,
            chunks,
            model=embedding_model,
            dimensions=embedding_dimensions,
        )
        rows = build_document_chunk_rows(
            source_row,
            stored_documents[accession_number]["id"],
            chunks,
            embedding_result.vectors,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
        )
        await upsert_document_chunks(supabase_client, rows)
        total_chunks += len(rows)
        total_tokens += embedding_result.total_tokens
        logger.info(
            "[%d/%d] Upserted %d chunks for %s (%d embedding tokens)",
            document_index,
            len(source_rows),
            len(rows),
            accession_number,
            embedding_result.total_tokens,
        )

    return total_chunks, total_tokens


def validate_local_chunks(
    source_rows: Sequence[SourceDocumentRow],
    *,
    embedding_model: str,
) -> tuple[int, int, int]:
    token_counter = OpenAITokenCounter(embedding_model)
    total_chunks = 0
    total_tables = 0
    total_tokens = 0
    for document_index, source_row in enumerate(source_rows, start=1):
        docling_path, markdown_path = document_paths(source_row)
        chunks = chunk_document(docling_path, markdown_path, token_counter)
        table_count = sum(bool(chunk.metadata["contains_table"]) for chunk in chunks)
        total_chunks += len(chunks)
        total_tables += table_count
        total_tokens += sum(chunk.token_count for chunk in chunks)
        logger.info(
            "[%d/%d] Validated %d chunks (%d tables) for %s",
            document_index,
            len(source_rows),
            len(chunks),
            table_count,
            source_row["accession_number"],
        )
    return total_chunks, total_tables, total_tokens


def _database_string(row: dict[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise TypeError(f"Supabase field {field!r} must be a non-empty string")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create embeddings and upsert document_chunks in Supabase."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate all local chunks without calling OpenAI or Supabase.",
    )
    parser.add_argument(
        "--accession-number",
        help="Process one complete filing instead of the full manifest.",
    )
    return parser.parse_args()


def main() -> None:
    from app.config import settings
    from app.database.supabase import create_admin_supabase_client

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    source_rows = load_source_document_rows()
    if args.accession_number:
        source_rows = [
            row
            for row in source_rows
            if row["accession_number"] == args.accession_number
        ]
        if not source_rows:
            raise ValueError(
                f"Accession number is not in the manifest: {args.accession_number}"
            )

    if args.dry_run:
        chunk_count, table_count, token_count = validate_local_chunks(
            source_rows,
            embedding_model=settings.openai_embedding_model,
        )
        logger.info(
            "Dry run complete: %d documents, %d chunks, %d complete tables, "
            "%d estimated embedding tokens; no APIs were called",
            len(source_rows),
            chunk_count,
            table_count,
            token_count,
        )
        return

    async def run() -> tuple[int, int]:
        supabase_client = await create_admin_supabase_client(settings)
        embedding_client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            max_retries=3,
        )
        return await ingest_document_chunks(
            source_rows,
            supabase_client,
            embedding_client,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
        )

    chunk_count, token_count = asyncio.run(run())
    logger.info(
        "Ingestion complete: %d documents, %d chunks, %d embedding tokens",
        len(source_rows),
        chunk_count,
        token_count,
    )


if __name__ == "__main__":
    main()
