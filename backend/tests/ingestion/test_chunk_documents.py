from __future__ import annotations

from pathlib import Path

import pytest
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    TableCell,
    TableData,
)

from ingestion.chunk_documents import ChunkTooLargeError, chunk_document


class WordTokenCounter:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


class OversizedTokenCounter:
    def count_tokens(self, text: str) -> int:
        return 9_000


def test_hierarchical_chunks_preserve_headings_tables_and_offsets(tmp_path) -> None:
    docling_path, markdown_path = _write_structured_document(tmp_path)

    chunks = chunk_document(docling_path, markdown_path, WordTokenCounter())

    assert len(chunks) == 2
    paragraph_chunk, table_chunk = chunks
    assert paragraph_chunk.text == "Risk Factors\nRevenue concentration is a risk."
    assert paragraph_chunk.section_title == "Risk Factors"
    assert paragraph_chunk.source_start is not None
    assert paragraph_chunk.source_end is not None
    assert table_chunk.section_title == "Risk Factors"
    assert table_chunk.metadata["contains_table"] is True
    assert table_chunk.metadata["doc_item_labels"] == ["table"]
    assert len(table_chunk.metadata["table_refs"]) == 1
    assert "North America" in table_chunk.text
    assert "$100" in table_chunk.text
    assert "$80" in table_chunk.text
    assert table_chunk.source_start is not None
    assert table_chunk.source_end is not None


def test_oversized_table_is_rejected_instead_of_split(tmp_path) -> None:
    docling_path, markdown_path = _write_table_only_document(tmp_path)

    with pytest.raises(ChunkTooLargeError, match="tables, are never split"):
        chunk_document(
            docling_path,
            markdown_path,
            OversizedTokenCounter(),
            max_tokens=8_192,
        )


def _write_structured_document(tmp_path: Path) -> tuple[Path, Path]:
    doc = DoclingDocument(name="structured-fixture")
    doc.add_heading("Risk Factors", level=1)
    doc.add_text(
        label=DocItemLabel.PARAGRAPH,
        text="Revenue concentration is a risk.",
    )
    doc.add_table(data=_table_data())
    return _write_document(tmp_path, doc)


def _write_table_only_document(tmp_path: Path) -> tuple[Path, Path]:
    doc = DoclingDocument(name="table-fixture")
    doc.add_table(data=_table_data())
    return _write_document(tmp_path, doc)


def _write_document(
    tmp_path: Path,
    doc: DoclingDocument,
) -> tuple[Path, Path]:
    docling_path = tmp_path / "document.json"
    markdown_path = tmp_path / "document.md"
    doc.save_as_json(docling_path)
    doc.save_as_markdown(markdown_path)
    return docling_path, markdown_path


def _table_data() -> TableData:
    values = [
        ["Region", "Revenue"],
        ["North America", "$100"],
        ["Europe", "$80"],
    ]
    cells = [
        TableCell(
            text=value,
            start_row_offset_idx=row_index,
            end_row_offset_idx=row_index + 1,
            start_col_offset_idx=column_index,
            end_col_offset_idx=column_index + 1,
            column_header=row_index == 0,
        )
        for row_index, row in enumerate(values)
        for column_index, value in enumerate(row)
    ]
    return TableData(table_cells=cells, num_rows=len(values), num_cols=2)
