"""Verify Supabase source documents and chunks against local checkpoints."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from sqlalchemy import create_engine, text

from ingestion.checkpoints import (
    DEFAULT_CHECKPOINT_ROOT,
    load_document_chunks,
    load_document_embeddings,
)
from ingestion.chunk_documents import CHUNKER_VERSION
from ingestion.ingest_documents import load_source_document_rows
from ingestion.sec_parser import PARSER_VERSION

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the completed Supabase ingestion against local files."
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
    checkpoint_root = args.checkpoint_root.resolve()
    source_rows = load_source_document_rows()
    expected = {}
    for source_row in source_rows:
        chunk_checkpoint, _chunks = load_document_chunks(
            source_row,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            checkpoint_root=checkpoint_root,
        )
        load_document_embeddings(
            source_row,
            chunk_checkpoint,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            checkpoint_root=checkpoint_root,
        )
        expected[source_row["accession_number"]] = (
            source_row,
            chunk_checkpoint,
        )

    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            records = connection.execute(
                text(
                    """
                    SELECT
                        source.accession_number,
                        source.content_checksum,
                        source.extraction_metadata->>'parser_version'
                            AS source_parser_version,
                        count(chunk.id) AS chunk_count,
                        min(chunk.chunk_index) AS minimum_chunk_index,
                        max(chunk.chunk_index) AS maximum_chunk_index,
                        count(chunk.id) FILTER (
                            WHERE chunk.display_table IS NOT NULL
                        ) AS table_chunk_count,
                        count(chunk.id) FILTER (
                            WHERE chunk.metadata->>'parser_version' = :parser_version
                              AND chunk.metadata->>'chunker_version' = :chunker_version
                              AND chunk.metadata->>'content_checksum'
                                  = source.content_checksum
                        ) AS matching_metadata_count
                    FROM public.source_documents AS source
                    LEFT JOIN public.document_chunks AS chunk
                      ON chunk.document_id = source.id
                    GROUP BY source.id
                    ORDER BY source.accession_number
                    """
                ),
                {
                    "parser_version": PARSER_VERSION,
                    "chunker_version": CHUNKER_VERSION,
                },
            ).mappings()
            actual = {record["accession_number"]: record for record in records}
    finally:
        engine.dispose()

    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise ValueError(
            f"Supabase source-document set differs; missing={missing}, extra={extra}"
        )

    total_chunks = 0
    for accession_number, (source_row, checkpoint) in expected.items():
        record = actual[accession_number]
        expected_maximum = checkpoint.chunk_count - 1
        mismatches = []
        if record["content_checksum"] != source_row["content_checksum"]:
            mismatches.append("content_checksum")
        if record["source_parser_version"] != PARSER_VERSION:
            mismatches.append("source_parser_version")
        if record["chunk_count"] != checkpoint.chunk_count:
            mismatches.append("chunk_count")
        if record["minimum_chunk_index"] != 0:
            mismatches.append("minimum_chunk_index")
        if record["maximum_chunk_index"] != expected_maximum:
            mismatches.append("maximum_chunk_index")
        if record["table_chunk_count"] != checkpoint.table_chunk_count:
            mismatches.append("table_chunk_count")
        if record["matching_metadata_count"] != checkpoint.chunk_count:
            mismatches.append("chunk_metadata")
        if mismatches:
            raise ValueError(
                f"Supabase verification failed for {accession_number}: "
                + ", ".join(mismatches)
            )
        total_chunks += checkpoint.chunk_count
        logger.info(
            "Verified %s: %d chunks (%d tables)",
            accession_number,
            checkpoint.chunk_count,
            checkpoint.table_chunk_count,
        )
    logger.info(
        "Supabase ingestion verified: %d source documents and %d chunks",
        len(expected),
        total_chunks,
    )


if __name__ == "__main__":
    main()
