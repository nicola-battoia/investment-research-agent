"""Upload validated local embedding checkpoints to Supabase."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from postgrest import CountMethod

from ingestion.checkpoints import (
    DEFAULT_CHECKPOINT_ROOT,
    load_document_chunks,
    load_document_embeddings,
    select_source_rows,
)
from ingestion.ingest_documents import SourceDocumentRow, load_source_document_rows
from ingestion.supabase_chunks import (
    build_document_chunk_rows,
    load_stored_source_documents,
    upsert_document_chunks,
    validate_existing_chunk_version,
    validate_stored_source_documents,
)

if TYPE_CHECKING:
    from supabase import AsyncClient

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload document_chunks from validated local checkpoints without "
            "calling OpenAI. Completed documents are verified and skipped."
        )
    )
    parser.add_argument(
        "--accession-number",
        help="Upload one filing instead of all filings in the manifest.",
    )
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=DEFAULT_CHECKPOINT_ROOT,
    )
    return parser.parse_args()


async def upload_document_checkpoints(
    source_rows: list[SourceDocumentRow],
    *,
    checkpoint_root: Path,
) -> tuple[int, int]:
    from app.config import settings
    from app.database.supabase import create_admin_supabase_client

    client = await create_admin_supabase_client(settings)
    stored_documents = await load_stored_source_documents(
        client,
        [row["accession_number"] for row in source_rows],
    )
    validate_stored_source_documents(source_rows, stored_documents)

    uploaded_documents = 0
    skipped_documents = 0
    for index, source_row in enumerate(source_rows, start=1):
        accession_number = source_row["accession_number"]
        document_id = stored_documents[accession_number]["id"]
        chunk_checkpoint, chunks = load_document_chunks(
            source_row,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            checkpoint_root=checkpoint_root,
        )
        _embedding_checkpoint, vectors = load_document_embeddings(
            source_row,
            chunk_checkpoint,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            checkpoint_root=checkpoint_root,
        )
        await validate_existing_chunk_version(client, source_row, document_id)
        if await _document_upload_is_complete(
            client,
            document_id,
            expected_chunk_count=len(chunks),
        ):
            skipped_documents += 1
            logger.info(
                "[%d/%d] Verified existing upload for %s (%d chunks)",
                index,
                len(source_rows),
                accession_number,
                len(chunks),
            )
            continue

        rows = build_document_chunk_rows(
            source_row,
            document_id,
            chunks,
            vectors,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
        )
        await upsert_document_chunks(client, rows)
        if not await _document_upload_is_complete(
            client,
            document_id,
            expected_chunk_count=len(chunks),
        ):
            raise RuntimeError(
                f"Supabase upload verification failed: {accession_number}"
            )
        uploaded_documents += 1
        logger.info(
            "[%d/%d] Uploaded and verified %s (%d chunks)",
            index,
            len(source_rows),
            accession_number,
            len(chunks),
        )
    return uploaded_documents, skipped_documents


async def _document_upload_is_complete(
    client: AsyncClient,
    document_id: str,
    *,
    expected_chunk_count: int,
) -> bool:
    table = client.table("document_chunks")
    count_response = await (
        table.select("id", count=CountMethod.exact, head=True)
        .eq("document_id", document_id)
        .execute()
    )
    count = count_response.count
    if not isinstance(count, int):
        raise TypeError("Supabase did not return an exact document chunk count")
    if count != expected_chunk_count:
        return False

    last_response = await (
        table.select("chunk_index")
        .eq("document_id", document_id)
        .order("chunk_index", desc=True)
        .limit(1)
        .execute()
    )
    if not isinstance(last_response.data, list) or len(last_response.data) != 1:
        raise TypeError("Supabase returned an invalid final document chunk")
    last_row = last_response.data[0]
    if not isinstance(last_row, dict):
        raise TypeError("Supabase returned an invalid final document chunk")
    return last_row.get("chunk_index") == expected_chunk_count - 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    source_rows = select_source_rows(
        load_source_document_rows(),
        args.accession_number,
    )
    uploaded, skipped = asyncio.run(
        upload_document_checkpoints(
            source_rows,
            checkpoint_root=args.checkpoint_root.resolve(),
        )
    )
    logger.info(
        "Supabase chunk upload complete: %d documents uploaded, %d reused",
        uploaded,
        skipped,
    )


if __name__ == "__main__":
    main()
