"""Export one real chunking and embedding run for human inspection."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ingestion.ingest_chunks import DocumentChunkRow, build_document_chunk_rows

from ingestion.chunk_documents import (
    CHUNKER_VERSION,
    OpenAITokenCounter,
    PreparedChunk,
    chunk_document,
    document_paths,
    source_row_for_accession,
)
from ingestion.create_embeddings import (
    EmbeddingClient,
    EmbeddingResult,
    create_embeddings,
)
from ingestion.ingest_documents import SourceDocumentRow

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "data" / "ingestion_runs"

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Chunk and embed one filing, then export review files without writing "
            "to Supabase."
        )
    )
    parser.add_argument("--accession-number", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Parent directory for the document-specific review bundle.",
    )
    return parser.parse_args()


async def export_document_run(
    source_row: SourceDocumentRow,
    *,
    output_root: Path,
    embedding_model: str,
    embedding_deployment: str,
    embedding_dimensions: int,
    embedding_client: EmbeddingClient,
) -> Path:
    parsed_path, markdown_path = document_paths(source_row)
    token_counter = OpenAITokenCounter(embedding_model)
    chunks = chunk_document(parsed_path, markdown_path, token_counter)

    embedding_result = await create_embeddings(
        embedding_client,
        chunks,
        model=embedding_deployment,
        dimensions=embedding_dimensions,
    )

    preview_document_id = str(
        uuid5(NAMESPACE_URL, f"sec:{source_row['accession_number']}")
    )
    generated_at = datetime.now(UTC)
    rows = build_document_chunk_rows(
        source_row,
        preview_document_id,
        chunks,
        embedding_result.vectors,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        updated_at=generated_at,
    )
    output_dir = output_root / _document_slug(source_row)
    _write_review_bundle(
        output_dir,
        source_row=source_row,
        chunks=chunks,
        rows=rows,
        embedding_result=embedding_result,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        generated_at=generated_at,
        source_markdown=markdown_path.read_text(encoding="utf-8"),
        parsed_path=parsed_path,
        markdown_path=markdown_path,
        preview_document_id=preview_document_id,
    )
    return output_dir


def _write_review_bundle(
    output_dir: Path,
    *,
    source_row: SourceDocumentRow,
    chunks: Sequence[PreparedChunk],
    rows: Sequence[DocumentChunkRow],
    embedding_result: EmbeddingResult,
    embedding_model: str,
    embedding_dimensions: int,
    generated_at: datetime,
    source_markdown: str,
    parsed_path: Path,
    markdown_path: Path,
    preview_document_id: str,
) -> None:
    if output_dir.exists():
        raise FileExistsError(
            f"Review bundle already exists; move it before rerunning: {output_dir}"
        )
    output_dir.mkdir(parents=True)

    example_row = _representative_row(rows)
    token_counts = [chunk.token_count for chunk in chunks]
    prose_token_counts = [
        chunk.token_count
        for chunk in chunks
        if not bool(chunk.metadata["contains_table"])
    ]
    table_token_counts = [
        chunk.token_count for chunk in chunks if bool(chunk.metadata["contains_table"])
    ]
    small_chunk_count = sum(count <= 20 for count in token_counts)
    run_summary = {
        "generated_at": generated_at.isoformat(),
        "database_written": False,
        "document": {
            "company": source_row["company"],
            "ticker": source_row["ticker"],
            "form": source_row["filing_type"],
            "filing_date": source_row["filing_date"],
            "accession_number": source_row["accession_number"],
            "content_checksum": source_row["content_checksum"],
            "source_markdown": str(markdown_path.relative_to(REPOSITORY_ROOT)),
            "parsed_document": str(parsed_path.relative_to(REPOSITORY_ROOT)),
        },
        "chunking": {
            "chunk_count": len(chunks),
            "table_chunk_count": len(table_token_counts),
            "prose_chunk_count": len(prose_token_counts),
            "total_tokens": sum(token_counts),
            "min_tokens": min(token_counts),
            "max_tokens": max(token_counts),
            "prose_max_tokens": max(prose_token_counts, default=0),
            "table_max_tokens": max(table_token_counts, default=0),
            "mean_tokens": statistics.fmean(token_counts),
            "median_tokens": statistics.median(token_counts),
            "chunks_at_most_20_tokens": small_chunk_count,
            "chunks_at_most_20_tokens_percent": (small_chunk_count / len(chunks) * 100),
            "chunks_below_100_tokens": sum(count < 100 for count in token_counts),
            "atomic_table_minimum_exceptions": sum(
                chunk.metadata.get("minimum_token_exception") == "atomic_table"
                for chunk in chunks
            ),
        },
        "embedding": {
            "model": embedding_model,
            "dimensions": embedding_dimensions,
            "api_input_tokens": embedding_result.total_tokens,
            "api_request_count": embedding_result.request_count,
            "vector_count": len(embedding_result.vectors),
        },
        "row_example": {
            "chunk_index": example_row["chunk_index"],
            "preview_document_id": preview_document_id,
            "note": (
                "The document_id is a valid deterministic preview UUID, not a "
                "source_documents ID read from Supabase."
            ),
        },
    }

    (output_dir / "README.md").write_text(
        _render_readme(source_row, run_summary), encoding="utf-8"
    )
    (output_dir / "source_document.md").write_text(source_markdown, encoding="utf-8")
    (output_dir / "chunks.md").write_text(_render_chunks(chunks), encoding="utf-8")
    _write_json_lines(
        output_dir / "chunks.jsonl",
        [_chunk_record(chunk) for chunk in chunks],
    )
    _write_json_lines(
        output_dir / "embeddings.jsonl",
        [
            {
                "chunk_index": chunk.chunk_index,
                "model": embedding_model,
                "dimensions": embedding_dimensions,
                "embedding": vector,
            }
            for chunk, vector in zip(chunks, embedding_result.vectors, strict=True)
        ],
    )
    (output_dir / "example_document_chunk_row.json").write_text(
        json.dumps(example_row, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "run.json").write_text(
        json.dumps(run_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _document_slug(source_row: SourceDocumentRow) -> str:
    form = source_row["filing_type"].lower().replace("-", "")
    return "_".join(
        [
            source_row["ticker"].lower(),
            form,
            source_row["filing_date"],
            source_row["accession_number"],
            CHUNKER_VERSION,
        ]
    )


def _representative_row(rows: Sequence[DocumentChunkRow]) -> DocumentChunkRow:
    for row in rows:
        if row["token_count"] >= 150 and row["display_table"] is None:
            return row
    return rows[0]


def _render_readme(
    source_row: SourceDocumentRow,
    run_summary: dict[str, Any],
) -> str:
    chunking = run_summary["chunking"]
    embedding = run_summary["embedding"]
    row_example = run_summary["row_example"]
    return f"""# Ingestion run: {source_row["ticker"]} {source_row["filing_type"]}

This directory contains one real execution of the custom SEC chunking pipeline and the OpenAI embedding step. Nothing was written to Supabase.

## Document

- Company: {source_row["company"]}
- Filing date: {source_row["filing_date"]}
- Accession number: `{source_row["accession_number"]}`
- Source text used by the chunker: [source_document.md](source_document.md)

## Results

- Chunks: {chunking["chunk_count"]} ({chunking["prose_chunk_count"]} prose, {chunking["table_chunk_count"]} tables)
- Chunk tokens: min {chunking["min_tokens"]}, max {chunking["max_tokens"]}, mean {chunking["mean_tokens"]:.2f}, median {chunking["median_tokens"]}
- Maximum prose chunk: {chunking["prose_max_tokens"]} tokens (the prose cap is 500)
- Maximum complete-table chunk: {chunking["table_max_tokens"]} tokens (tables may exceed 500 so their rows and columns remain intact)
- Chunks at or below 20 tokens: {chunking["chunks_at_most_20_tokens"]} ({chunking["chunks_at_most_20_tokens_percent"]:.2f}%)
- Chunks below 100 tokens: {chunking["chunks_below_100_tokens"]} ({chunking["atomic_table_minimum_exceptions"]} atomic table exceptions)
- Total chunk tokens: {chunking["total_tokens"]}
- Embedding model: `{embedding["model"]}`
- Embedding dimensions: {embedding["dimensions"]}
- OpenAI input tokens: {embedding["api_input_tokens"]} in {embedding["api_request_count"]} request(s)

## Files

- [chunks.md](chunks.md): the easiest way to inspect every chunk and its complete text.
- [source_document.md](source_document.md): the normalized human-readable filing for comparison.
- [chunks.jsonl](chunks.jsonl): one structured chunk per line, without vectors.
- [embeddings.jsonl](embeddings.jsonl): the real embedding vector for every chunk.
- [example_document_chunk_row.json](example_document_chunk_row.json): one complete row in the shape used by `document_chunks`, including its real embedding.
- [run.json](run.json): machine-readable run metadata and aggregate metrics.

The example row uses chunk {row_example["chunk_index"]}. Its `document_id` is the deterministic preview UUID `{row_example["preview_document_id"]}`. A real ingestion replaces that value with the matching `source_documents.id` from Supabase.
"""


def _render_chunks(chunks: Sequence[PreparedChunk]) -> str:
    parts = [
        "# Generated chunks\n",
        (
            "Each section below is the exact text sent to the embedding model. "
            "Source offsets refer to `source_document.md`.\n"
        ),
    ]
    for chunk in chunks:
        block_ids = ", ".join(str(value) for value in chunk.metadata["block_ids"])
        parts.extend(
            [
                f"## Chunk {chunk.chunk_index}\n",
                f"- Tokens: {chunk.token_count}\n",
                f"- Section: {chunk.section_title or 'None'}\n",
                f"- Contains table: {chunk.metadata['contains_table']}\n",
                f"- Block IDs: `{block_ids}`\n",
                f"- Source offsets: {chunk.source_start}–{chunk.source_end}\n",
                "````text\n",
                chunk.text,
                "\n````\n",
            ]
        )
    return "\n".join(parts)


def _chunk_record(chunk: PreparedChunk) -> dict[str, Any]:
    return {
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "token_count": chunk.token_count,
        "page_number": chunk.page_number,
        "section_title": chunk.section_title,
        "source_start": chunk.source_start,
        "source_end": chunk.source_end,
        "metadata": chunk.metadata,
        "display_table": (
            chunk.display_table.model_dump(mode="json")
            if chunk.display_table is not None
            else None
        ),
    }


def _write_json_lines(path: Path, records: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            output.write("\n")


def main() -> None:
    from app.config import settings
    from app.services import AzureOpenAIService

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    source_row = source_row_for_accession(args.accession_number)

    async def run() -> Path:
        async with AzureOpenAIService(settings) as azure_openai:
            return await export_document_run(
                source_row,
                output_root=args.output_root.resolve(),
                embedding_model=settings.openai_embedding_model,
                embedding_deployment=settings.azure_openai_embedding_deployment,
                embedding_dimensions=settings.openai_embedding_dimensions,
                embedding_client=azure_openai.client,
            )

    output_dir = asyncio.run(run())
    logger.info("Saved review bundle to %s", output_dir)


if __name__ == "__main__":
    main()
