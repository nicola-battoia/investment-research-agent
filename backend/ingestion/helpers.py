"""Report token counts for the Markdown ingestion corpus."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean, median

from ingestion.chunk_documents import (
    OpenAITokenCounter,
    PreparedChunk,
    TokenCounter,
    chunk_document,
    document_paths,
)
from ingestion.ingest_documents import SourceDocumentRow, load_source_document_rows


@dataclass(frozen=True)
class MarkdownTokenCount:
    markdown_path: str
    token_count: int


@dataclass(frozen=True)
class MarkdownTokenStats:
    documents: tuple[MarkdownTokenCount, ...]
    total_token_count: int
    mean_token_count: float


@dataclass(frozen=True)
class ChunkTokenStats:
    chunk_count: int
    total_token_count: int
    minimum_token_count: int
    maximum_token_count: int
    mean_token_count: float
    median_token_count: float
    chunks_at_most_20_tokens: int
    chunks_at_most_50_tokens: int
    chunks_at_most_100_tokens: int
    chunks_below_100_tokens: int
    chunks_below_target: int
    table_chunk_count: int
    atomic_table_minimum_exceptions: int
    merged_for_minimum_count: int
    merged_prose_over_500_count: int
    punctuation_only_count: int
    exact_duplicate_extra_count: int
    estimated_vector_bytes: int


def calculate_markdown_token_stats(
    source_rows: Sequence[SourceDocumentRow],
    token_counter: TokenCounter,
) -> MarkdownTokenStats:
    """Count tokens per manifest document and summarize the corpus."""
    if not source_rows:
        raise ValueError("At least one source document is required")

    documents = tuple(
        MarkdownTokenCount(
            markdown_path=str(row["extraction_metadata"]["markdown_local_path"]),
            token_count=token_counter.count_tokens(row["normalized_markdown"]),
        )
        for row in source_rows
    )
    total_token_count = sum(document.token_count for document in documents)
    return MarkdownTokenStats(
        documents=documents,
        total_token_count=total_token_count,
        mean_token_count=total_token_count / len(documents),
    )


def print_markdown_token_stats(stats: MarkdownTokenStats) -> None:
    path_width = max(
        len("Markdown document"),
        *(len(document.markdown_path) for document in stats.documents),
    )
    print(f"{'Markdown document':<{path_width}}  {'Tokens':>12}")
    print(f"{'-' * path_width}  {'-' * 12}")
    for document in stats.documents:
        print(f"{document.markdown_path:<{path_width}}  {document.token_count:>12,}")
    print()
    print(f"Total tokens: {stats.total_token_count:,}")
    print(f"Mean tokens per document: {stats.mean_token_count:,.2f}")


def calculate_chunk_token_stats(
    chunks: Sequence[PreparedChunk],
    *,
    embedding_dimensions: int = 1_536,
) -> ChunkTokenStats:
    if not chunks:
        raise ValueError("At least one chunk is required")
    if embedding_dimensions <= 0:
        raise ValueError("Embedding dimensions must be positive")
    counts = [chunk.token_count for chunk in chunks]
    text_counts = Counter(chunk.text for chunk in chunks)
    return ChunkTokenStats(
        chunk_count=len(chunks),
        total_token_count=sum(counts),
        minimum_token_count=min(counts),
        maximum_token_count=max(counts),
        mean_token_count=fmean(counts),
        median_token_count=median(counts),
        chunks_at_most_20_tokens=sum(count <= 20 for count in counts),
        chunks_at_most_50_tokens=sum(count <= 50 for count in counts),
        chunks_at_most_100_tokens=sum(count <= 100 for count in counts),
        chunks_below_100_tokens=sum(count < 100 for count in counts),
        chunks_below_target=sum(count < 150 for count in counts),
        table_chunk_count=sum(
            bool(chunk.metadata.get("contains_table")) for chunk in chunks
        ),
        atomic_table_minimum_exceptions=sum(
            chunk.metadata.get("minimum_token_exception") == "atomic_table"
            for chunk in chunks
        ),
        merged_for_minimum_count=sum(
            bool(chunk.metadata.get("merged_for_min_tokens")) for chunk in chunks
        ),
        merged_prose_over_500_count=sum(
            chunk.token_count > 500 and not bool(chunk.metadata.get("contains_table"))
            for chunk in chunks
        ),
        punctuation_only_count=sum(
            not any(character.isalnum() for character in chunk.text) for chunk in chunks
        ),
        exact_duplicate_extra_count=sum(
            count - 1 for count in text_counts.values() if count > 1
        ),
        estimated_vector_bytes=len(chunks) * embedding_dimensions * 4,
    )


def print_chunk_token_stats(stats: ChunkTokenStats) -> None:
    print("\nChunk metrics")
    print(f"Chunks: {stats.chunk_count:,}")
    print(f"Tokens: {stats.total_token_count:,}")
    print(
        "Length (tokens): "
        f"min {stats.minimum_token_count:,}, "
        f"max {stats.maximum_token_count:,}, "
        f"mean {stats.mean_token_count:,.2f}, "
        f"median {stats.median_token_count:,.2f}"
    )
    print(
        "Small chunks: "
        f"≤20 {stats.chunks_at_most_20_tokens:,}, "
        f"≤50 {stats.chunks_at_most_50_tokens:,}, "
        f"≤100 {stats.chunks_at_most_100_tokens:,}, "
        f"<150 {stats.chunks_below_target:,}"
    )
    print(
        f"Below 100: {stats.chunks_below_100_tokens:,} "
        f"({stats.atomic_table_minimum_exceptions:,} atomic table exceptions)"
    )
    print(
        f"Minimum-size merges: {stats.merged_for_minimum_count:,} "
        f"({stats.merged_prose_over_500_count:,} prose chunks above 500)"
    )
    print(f"Tables: {stats.table_chunk_count:,}")
    print(f"Punctuation-only: {stats.punctuation_only_count:,}")
    print(
        f"Exact duplicate extras across corpus: {stats.exact_duplicate_extra_count:,}"
    )
    print(
        "Estimated raw vector storage: "
        f"{stats.estimated_vector_bytes / (1024 * 1024):,.1f} MiB"
    )


def main() -> None:
    from app.config import settings

    source_rows = load_source_document_rows()
    token_counter = OpenAITokenCounter(settings.openai_embedding_model)
    print(f"Tokenizer model: {settings.openai_embedding_model}\n")
    print_markdown_token_stats(
        calculate_markdown_token_stats(source_rows, token_counter)
    )
    chunks = []
    for row in source_rows:
        parsed_path, markdown_path = document_paths(row)
        chunks.extend(chunk_document(parsed_path, markdown_path, token_counter))
    print_chunk_token_stats(
        calculate_chunk_token_stats(
            chunks,
            embedding_dimensions=settings.openai_embedding_dimensions,
        )
    )


if __name__ == "__main__":
    main()
