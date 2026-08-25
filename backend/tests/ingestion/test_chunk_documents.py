from __future__ import annotations

import json

import pytest

from ingestion.chunk_documents import ChunkTooLargeError, chunk_document
from ingestion.sec_parser import (
    ParsedBlock,
    ParsedDocument,
    ParsedSection,
    ParsedTableCell,
    render_markdown,
)


class WordTokenCounter:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


class OversizedTokenCounter:
    def count_tokens(self, text: str) -> int:
        return 9_000


def test_packs_prose_by_section_and_preserves_offsets(tmp_path) -> None:
    document = ParsedDocument(
        form="10-K",
        source_path="sample.htm",
        audit={},
        sections=[
            ParsedSection(
                key="item_1a",
                title="Item 1A. Risk Factors",
                detection_method="body_heading",
                blocks=[
                    _block("b00001", "paragraph", "Competition is intense."),
                    _block("b00002", "paragraph", "Demand may change rapidly."),
                ],
            ),
            ParsedSection(
                key="item_7",
                title="Item 7. Management Discussion",
                detection_method="body_heading",
                blocks=[_block("b00003", "paragraph", "Revenue increased.")],
            ),
        ],
    )
    parsed_path, markdown_path = _write_document(tmp_path, document)

    chunks = chunk_document(
        parsed_path,
        markdown_path,
        WordTokenCounter(),
        min_tokens=1,
        max_tokens=20,
        max_merged_tokens=20,
    )

    assert len(chunks) == 2
    assert chunks[0].text == (
        "Item 1A. Risk Factors\n\nCompetition is intense.\n\nDemand may change rapidly."
    )
    assert chunks[0].metadata["block_ids"] == ["b00001", "b00002"]
    assert chunks[0].source_start is not None
    assert chunks[0].source_end is not None
    assert chunks[0].token_count <= 20
    assert chunks[1].section_title == "Item 7. Management Discussion"


def test_splits_oversized_paragraph_without_overlap(tmp_path) -> None:
    words = " ".join(f"word{index}" for index in range(30))
    document = _document_with_blocks([_block("b00001", "paragraph", words)])
    parsed_path, markdown_path = _write_document(tmp_path, document)

    chunks = chunk_document(
        parsed_path,
        markdown_path,
        WordTokenCounter(),
        min_tokens=1,
        max_tokens=12,
        max_merged_tokens=12,
    )

    assert len(chunks) > 1
    assert all(chunk.token_count <= 12 for chunk in chunks)
    bodies = [chunk.text.split("\n\n", 1)[1] for chunk in chunks]
    assert " ".join(bodies).split() == words.split()


def test_complete_table_can_exceed_prose_limit_and_preserves_geometry(tmp_path) -> None:
    table = ParsedBlock(
        id="b00001",
        kind="table",
        text="[TABLE]\nYear | Revenue\n2025 | $100",
        html_locator="/html/body/table",
        row_count=2,
        column_count=2,
        cells=[
            ParsedTableCell("Year", 0, 0, column_header=True),
            ParsedTableCell("Revenue", 0, 1, column_header=True),
            ParsedTableCell("2025", 1, 0),
            ParsedTableCell("$100", 1, 1),
        ],
    )
    parsed_path, markdown_path = _write_document(
        tmp_path, _document_with_blocks([table])
    )

    chunk = chunk_document(
        parsed_path,
        markdown_path,
        WordTokenCounter(),
        max_tokens=3,
    )[0]

    assert chunk.token_count > 3
    assert chunk.display_table is not None
    assert chunk.display_table.column_count == 2
    for row in chunk.display_table.rows:
        for cell in row.cells:
            assert chunk.text[cell.text_start : cell.text_end] == cell.text


def test_merges_small_prose_forward_and_allows_larger_merge_limit(tmp_path) -> None:
    document = ParsedDocument(
        form="10-K",
        source_path="sample.htm",
        audit={},
        sections=[
            ParsedSection(
                key="item_1b",
                title="Short",
                detection_method="body_heading",
                blocks=[_block("b00001", "paragraph", "None here.")],
            ),
            ParsedSection(
                key="item_1c",
                title="Long",
                detection_method="body_heading",
                blocks=[
                    _block(
                        "b00002",
                        "paragraph",
                        "one two three four five six seven eight nine ten eleven "
                        "twelve thirteen fourteen fifteen sixteen seventeen eighteen",
                    )
                ],
            ),
        ],
    )
    parsed_path, markdown_path = _write_document(tmp_path, document)

    chunks = chunk_document(
        parsed_path,
        markdown_path,
        WordTokenCounter(),
        min_tokens=10,
        max_tokens=20,
        max_merged_tokens=30,
    )

    assert len(chunks) == 1
    assert 20 < chunks[0].token_count <= 30
    assert chunks[0].metadata["merged_for_min_tokens"] is True
    assert chunks[0].metadata["section_keys"] == ["item_1b", "item_1c"]
    assert chunks[0].text.index("Short") < chunks[0].text.index("Long")


def test_merges_trailing_small_prose_backward(tmp_path) -> None:
    document = ParsedDocument(
        form="10-K",
        source_path="sample.htm",
        audit={},
        sections=[
            ParsedSection(
                key="item_1",
                title="Main",
                detection_method="body_heading",
                blocks=[
                    _block(
                        "b00001",
                        "paragraph",
                        "one two three four five six seven eight nine ten eleven twelve",
                    )
                ],
            ),
            ParsedSection(
                key="item_1b",
                title="Tail",
                detection_method="body_heading",
                blocks=[_block("b00002", "paragraph", "None.")],
            ),
        ],
    )
    parsed_path, markdown_path = _write_document(tmp_path, document)

    chunks = chunk_document(
        parsed_path,
        markdown_path,
        WordTokenCounter(),
        min_tokens=10,
        max_tokens=20,
        max_merged_tokens=25,
    )

    assert len(chunks) == 1
    assert chunks[0].token_count >= 10
    assert chunks[0].metadata["section_keys"] == ["item_1", "item_1b"]


def test_forward_merge_preserves_following_table_offsets(tmp_path) -> None:
    table = ParsedBlock(
        id="b00002",
        kind="table",
        text="[TABLE]\nYear | Revenue\n2025 | $100",
        html_locator="/html/body/table",
        row_count=2,
        column_count=2,
        cells=[
            ParsedTableCell("Year", 0, 0, column_header=True),
            ParsedTableCell("Revenue", 0, 1, column_header=True),
            ParsedTableCell("2025", 1, 0),
            ParsedTableCell("$100", 1, 1),
        ],
    )
    document = ParsedDocument(
        form="10-K",
        source_path="sample.htm",
        audit={},
        sections=[
            ParsedSection(
                key="item_7",
                title="Introduction",
                detection_method="body_heading",
                blocks=[_block("b00001", "paragraph", "Short note.")],
            ),
            ParsedSection(
                key="item_8",
                title="Financials",
                detection_method="body_heading",
                blocks=[table],
            ),
        ],
    )
    parsed_path, markdown_path = _write_document(tmp_path, document)

    chunk = chunk_document(
        parsed_path,
        markdown_path,
        WordTokenCounter(),
        min_tokens=10,
        max_tokens=20,
        max_merged_tokens=30,
    )[0]

    assert chunk.display_table is not None
    assert chunk.metadata["section_keys"] == ["item_7", "item_8"]
    for row in chunk.display_table.rows:
        for cell in row.cells:
            assert chunk.text[cell.text_start : cell.text_end] == cell.text


def test_adjacent_small_tables_keep_atomic_minimum_exception(tmp_path) -> None:
    first = _table_block("b00001", "One")
    second = _table_block("b00002", "Two")
    document = ParsedDocument(
        form="10-K",
        source_path="sample.htm",
        audit={},
        sections=[
            ParsedSection(
                key="item_8",
                title="Financials",
                detection_method="body_heading",
                blocks=[first, second],
            )
        ],
    )
    parsed_path, markdown_path = _write_document(tmp_path, document)

    chunks = chunk_document(
        parsed_path,
        markdown_path,
        WordTokenCounter(),
        min_tokens=100,
    )

    assert len(chunks) == 2
    assert all(chunk.token_count < 100 for chunk in chunks)
    assert all(
        chunk.metadata["minimum_token_exception"] == "atomic_table" for chunk in chunks
    )


def test_table_over_embedding_limit_is_rejected(tmp_path) -> None:
    table = ParsedBlock(
        id="b00001",
        kind="table",
        text="[TABLE]\nValue",
        html_locator="/html/body/table",
        row_count=1,
        column_count=1,
        cells=[ParsedTableCell("Value", 0, 0)],
    )
    parsed_path, markdown_path = _write_document(
        tmp_path, _document_with_blocks([table])
    )

    with pytest.raises(ChunkTooLargeError, match="kept atomic"):
        chunk_document(parsed_path, markdown_path, OversizedTokenCounter())


def _block(block_id: str, kind: str, text: str) -> ParsedBlock:
    return ParsedBlock(
        id=block_id,
        kind=kind,  # type: ignore[arg-type]
        text=text,
        html_locator=f"/html/body/{block_id}",
    )


def _table_block(block_id: str, value: str) -> ParsedBlock:
    return ParsedBlock(
        id=block_id,
        kind="table",
        text=f"[TABLE]\nLabel | Value\nRow | {value}",
        html_locator=f"/html/body/{block_id}",
        row_count=2,
        column_count=2,
        cells=[
            ParsedTableCell("Label", 0, 0, column_header=True),
            ParsedTableCell("Value", 0, 1, column_header=True),
            ParsedTableCell("Row", 1, 0),
            ParsedTableCell(value, 1, 1),
        ],
    )


def _document_with_blocks(blocks: list[ParsedBlock]) -> ParsedDocument:
    return ParsedDocument(
        form="10-K",
        source_path="sample.htm",
        audit={},
        sections=[
            ParsedSection(
                key="item_1a",
                title="Item 1A. Risk Factors",
                detection_method="body_heading",
                blocks=blocks,
            )
        ],
    )


def _write_document(tmp_path, document: ParsedDocument):
    markdown = render_markdown(document)
    parsed_path = tmp_path / "document.json"
    markdown_path = tmp_path / "document.md"
    parsed_path.write_text(json.dumps(document.to_dict()), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    return parsed_path, markdown_path
