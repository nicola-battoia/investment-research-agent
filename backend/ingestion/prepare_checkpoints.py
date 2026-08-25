"""Create or validate durable chunk checkpoints for parsed SEC filings."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ingestion.checkpoints import (
    DEFAULT_CHECKPOINT_ROOT,
    prepare_document_checkpoint,
    select_source_rows,
)
from ingestion.ingest_documents import load_source_document_rows

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save validated chunks locally without calling external APIs."
    )
    parser.add_argument(
        "--accession-number",
        help="Prepare one filing instead of all filings in the manifest.",
    )
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=DEFAULT_CHECKPOINT_ROOT,
    )
    return parser.parse_args()


def main() -> None:
    from app.config import settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    source_rows = select_source_rows(
        load_source_document_rows(),
        args.accession_number,
    )
    total_chunks = 0
    total_tokens = 0
    created_count = 0
    for index, source_row in enumerate(source_rows, start=1):
        checkpoint, _chunks, created = prepare_document_checkpoint(
            source_row,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            checkpoint_root=args.checkpoint_root.resolve(),
        )
        total_chunks += checkpoint.chunk_count
        total_tokens += checkpoint.chunk_token_count
        created_count += created
        logger.info(
            "[%d/%d] %s %s: %d chunks, %d tokens",
            index,
            len(source_rows),
            "Saved" if created else "Validated",
            checkpoint.accession_number,
            checkpoint.chunk_count,
            checkpoint.chunk_token_count,
        )
    logger.info(
        "Chunk checkpoints ready: %d documents (%d new), %d chunks, %d tokens",
        len(source_rows),
        created_count,
        total_chunks,
        total_tokens,
    )


if __name__ == "__main__":
    main()
