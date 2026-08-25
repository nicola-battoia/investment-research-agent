from __future__ import annotations

from typing import cast

import pytest

from ingestion.chunk_documents import PreparedChunk
from ingestion.helpers import (
    calculate_chunk_token_stats,
    calculate_markdown_token_stats,
)
from ingestion.ingest_documents import SourceDocumentRow


class CharacterTokenCounter:
    def count_tokens(self, text: str) -> int:
        return len(text)


def test_calculate_markdown_token_stats_counts_each_document() -> None:
    rows = [
        _source_row("2024/aapl.md", "four"),
        _source_row("2024/msft.md", "six!!!"),
    ]

    stats = calculate_markdown_token_stats(rows, CharacterTokenCounter())

    assert [
        (document.markdown_path, document.token_count) for document in stats.documents
    ] == [
        ("2024/aapl.md", 4),
        ("2024/msft.md", 6),
    ]
    assert stats.total_token_count == 10
    assert stats.mean_token_count == 5.0


def test_calculate_markdown_token_stats_rejects_empty_corpus() -> None:
    with pytest.raises(ValueError, match="At least one source document"):
        calculate_markdown_token_stats([], CharacterTokenCounter())


def test_calculate_chunk_token_stats_reports_distribution_and_storage() -> None:
    chunks = [
        _chunk(0, 20),
        _chunk(1, 100, contains_table=True),
        _chunk(2, 300),
    ]

    stats = calculate_chunk_token_stats(chunks, embedding_dimensions=3)

    assert stats.chunk_count == 3
    assert stats.total_token_count == 420
    assert stats.minimum_token_count == 20
    assert stats.maximum_token_count == 300
    assert stats.mean_token_count == 140
    assert stats.median_token_count == 100
    assert stats.chunks_at_most_20_tokens == 1
    assert stats.chunks_below_100_tokens == 1
    assert stats.chunks_below_target == 2
    assert stats.table_chunk_count == 1
    assert stats.atomic_table_minimum_exceptions == 0
    assert stats.merged_for_minimum_count == 0
    assert stats.merged_prose_over_500_count == 0
    assert stats.punctuation_only_count == 0
    assert stats.exact_duplicate_extra_count == 0
    assert stats.estimated_vector_bytes == 36


def _source_row(markdown_path: str, markdown: str) -> SourceDocumentRow:
    return cast(
        SourceDocumentRow,
        {
            "normalized_markdown": markdown,
            "extraction_metadata": {"markdown_local_path": markdown_path},
        },
    )


def _chunk(
    index: int,
    token_count: int,
    *,
    contains_table: bool = False,
) -> PreparedChunk:
    return PreparedChunk(
        chunk_index=index,
        text=f"Chunk {index}",
        token_count=token_count,
        page_number=None,
        section_title=None,
        source_start=None,
        source_end=None,
        metadata={"contains_table": contains_table},
    )
