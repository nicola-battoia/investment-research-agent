"""Create resumable OpenAI embedding checkpoints one filing at a time."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from openai import AsyncOpenAI

from ingestion.checkpoints import (
    DEFAULT_CHECKPOINT_ROOT,
    checkpoint_paths,
    load_document_chunks,
    load_document_embeddings,
    save_document_embeddings,
    select_source_rows,
)
from ingestion.create_embeddings import create_embeddings
from ingestion.ingest_documents import load_source_document_rows

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create paid embeddings from local chunks and save them before any "
            "Supabase upload. Existing valid checkpoints are skipped."
        )
    )
    parser.add_argument(
        "--accession-number",
        help="Embed one filing instead of all filings in the manifest.",
    )
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=DEFAULT_CHECKPOINT_ROOT,
    )
    return parser.parse_args()


async def embed_missing_checkpoints(
    *,
    accession_number: str | None,
    checkpoint_root: Path,
) -> None:
    from app.config import settings

    source_rows = select_source_rows(
        load_source_document_rows(),
        accession_number,
    )
    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        max_retries=3,
    )
    embedded_documents = 0
    skipped_documents = 0
    total_tokens = 0
    for index, source_row in enumerate(source_rows, start=1):
        chunk_checkpoint, chunks = load_document_chunks(
            source_row,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            checkpoint_root=checkpoint_root,
        )
        paths = checkpoint_paths(source_row["accession_number"], checkpoint_root)
        if paths.embeddings_directory.exists():
            embedding_checkpoint, _vectors = load_document_embeddings(
                source_row,
                chunk_checkpoint,
                embedding_model=settings.openai_embedding_model,
                embedding_dimensions=settings.openai_embedding_dimensions,
                checkpoint_root=checkpoint_root,
            )
            skipped_documents += 1
            total_tokens += embedding_checkpoint.embedding_input_tokens
            logger.info(
                "[%d/%d] Validated existing embeddings for %s (%d vectors)",
                index,
                len(source_rows),
                source_row["accession_number"],
                embedding_checkpoint.embedding_count,
            )
            continue

        result = await create_embeddings(
            client,
            chunks,
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
        )
        embedding_checkpoint = save_document_embeddings(
            source_row,
            chunk_checkpoint,
            result.vectors,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            embedding_input_tokens=result.total_tokens,
            embedding_request_count=result.request_count,
            checkpoint_root=checkpoint_root,
        )
        embedded_documents += 1
        total_tokens += embedding_checkpoint.embedding_input_tokens
        logger.info(
            "[%d/%d] Saved %d embeddings for %s (%d API tokens, %d requests)",
            index,
            len(source_rows),
            embedding_checkpoint.embedding_count,
            source_row["accession_number"],
            embedding_checkpoint.embedding_input_tokens,
            embedding_checkpoint.embedding_request_count,
        )
    logger.info(
        "Embedding checkpoints ready: %d new documents, %d reused, "
        "%d total API input tokens represented",
        embedded_documents,
        skipped_documents,
        total_tokens,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    asyncio.run(
        embed_missing_checkpoints(
            accession_number=args.accession_number,
            checkpoint_root=args.checkpoint_root.resolve(),
        )
    )


if __name__ == "__main__":
    main()
