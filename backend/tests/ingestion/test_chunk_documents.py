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


def test_table_display_preserves_geometry_headers_empty_cells_and_text_ranges(
    tmp_path,
) -> None:
    doc = DoclingDocument(name="spanning-table-fixture")
    doc.add_heading("Segment results", level=1)
    doc.add_table(data=_spanning_table_data())
    docling_path, markdown_path = _write_document(tmp_path, doc)

    chunk = chunk_document(docling_path, markdown_path, WordTokenCounter())[0]

    assert chunk.text == (
        "Segment results\n[TABLE]\nRegion | Net sales\n2024 | 2023\n"
        "North America | $100 | $80"
    )
    table = chunk.display_table
    assert table is not None
    assert table.version == 1
    assert table.table_ref == "#/tables/0"
    assert table.column_count == 4
    assert len(table.rows) == 3
    assert sum(len(row.cells) for row in table.rows) == 10

    region = table.rows[0].cells[0]
    assert region.row_span == 2
    assert region.column_span == 1
    assert region.column_header is True
    net_sales = table.rows[0].cells[1]
    assert net_sales.column_span == 2
    assert net_sales.column_header is True
    north_america = table.rows[2].cells[0]
    assert north_america.row_header is True

    empty_cells = [cell for row in table.rows for cell in row.cells if not cell.text]
    assert len(empty_cells) == 3
    assert all(
        cell.text_start is None and cell.text_end is None for cell in empty_cells
    )
    for row in table.rows:
        for cell in row.cells:
            if cell.text:
                assert cell.text_start is not None
                assert cell.text_end is not None
                assert chunk.text[cell.text_start : cell.text_end] == cell.text


def test_empty_table_has_no_display_payload(tmp_path) -> None:
    doc = DoclingDocument(name="empty-table-fixture")
    doc.add_table(
        data=TableData(
            table_cells=[_cell("", 0, 0)],
            num_rows=1,
            num_cols=1,
        )
    )
    docling_path, markdown_path = _write_document(tmp_path, doc)

    chunk = chunk_document(docling_path, markdown_path, WordTokenCounter())[0]

    assert chunk.text == "[TABLE]\n"
    assert chunk.display_table is None


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


def _spanning_table_data() -> TableData:
    cells = [
        TableCell(
            text="Region",
            row_span=2,
            start_row_offset_idx=0,
            end_row_offset_idx=2,
            start_col_offset_idx=0,
            end_col_offset_idx=1,
            column_header=True,
        ),
        TableCell(
            text="Net sales",
            col_span=2,
            start_row_offset_idx=0,
            end_row_offset_idx=1,
            start_col_offset_idx=1,
            end_col_offset_idx=3,
            column_header=True,
        ),
        _cell("", 0, 3),
        _cell("2024", 1, 1, column_header=True),
        _cell("2023", 1, 2, column_header=True),
        _cell("", 1, 3),
        _cell("North America", 2, 0, row_header=True),
        _cell("$100", 2, 1),
        _cell("$80", 2, 2),
        _cell("", 2, 3),
    ]
    # The final empty layout column mirrors a Docling SEC edge case where origin
    # cells extend beyond the declared count. Display geometry remains lossless.
    return TableData(table_cells=cells, num_rows=3, num_cols=3)


def _cell(
    text: str,
    row: int,
    column: int,
    *,
    column_header: bool = False,
    row_header: bool = False,
) -> TableCell:
    return TableCell(
        text=text,
        start_row_offset_idx=row,
        end_row_offset_idx=row + 1,
        start_col_offset_idx=column,
        end_col_offset_idx=column + 1,
        column_header=column_header,
        row_header=row_header,
    )
