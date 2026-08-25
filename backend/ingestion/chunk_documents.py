"""Create structure-aware chunks from native Docling documents."""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import tiktoken
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
    DocChunk,
    HierarchicalChunker,
)
from docling_core.transforms.serializer.base import BaseDocSerializer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc import DocItemLabel, DoclingDocument, TableItem, TextItem

from app.retrieval.display_tables import (
    StoredDisplayTable,
    StoredTableCell,
    StoredTableRow,
)
from ingestion.ingest_documents import SourceDocumentRow, load_source_document_rows

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCLING_DOCUMENTS_DIR = REPOSITORY_ROOT / "data" / "docling_documents"
MARKDOWN_DIR = REPOSITORY_ROOT / "data" / "markdown"
MAX_EMBEDDING_INPUT_TOKENS = 8_192
DOCLING_VERSION = "2.119.0"

logger = logging.getLogger(__name__)


class TokenCounter(Protocol):
    def count_tokens(self, text: str) -> int: ...


class OpenAITokenCounter:
    def __init__(self, model: str) -> None:
        self.model = model
        self._encoding = tiktoken.encoding_for_model(model)

    def count_tokens(self, text: str) -> int:
        return len(self._encoding.encode(text, disallowed_special=()))


class SourceMarkdownSerializerProvider(ChunkingSerializerProvider):
    """Keep each complete table in one hierarchical Markdown chunk."""

    def get_serializer(self, doc: DoclingDocument) -> BaseDocSerializer:
        return ChunkingDocSerializer(
            doc=doc, table_serializer=MarkdownTableSerializer()
        )


@dataclass(frozen=True)
class PreparedChunk:
    chunk_index: int
    text: str
    token_count: int
    page_number: int | None
    section_title: str | None
    source_start: int | None
    source_end: int | None
    metadata: dict[str, object]
    display_table: StoredDisplayTable | None = None


@dataclass(frozen=True)
class CompactedTable:
    text: str
    cell_ranges: dict[int, tuple[int, int]]


class ChunkTooLargeError(ValueError):
    """A structural chunk cannot be sent to the configured embedding model."""


def chunk_document(
    docling_path: Path,
    markdown_path: Path,
    token_counter: TokenCounter,
    *,
    max_tokens: int = MAX_EMBEDDING_INPUT_TOKENS,
) -> list[PreparedChunk]:
    doc = DoclingDocument.load_from_json(docling_path)
    normalized_markdown = markdown_path.read_text(encoding="utf-8")
    chunker = HierarchicalChunker(
        serializer_provider=SourceMarkdownSerializerProvider()
    )
    source_chunks = [DocChunk.model_validate(chunk) for chunk in chunker.chunk(doc)]
    _validate_table_integrity(doc, source_chunks)

    prepared_chunks = []
    source_cursor = 0
    for chunk_index, source_chunk in enumerate(source_chunks):
        chunk = _compact_table_chunk(source_chunk)
        text = chunker.contextualize(chunk)
        display_table = _display_table(source_chunk, chunk, text)
        _validate_display_table(source_chunk, display_table, text)
        token_count = token_counter.count_tokens(text)
        if token_count > max_tokens:
            labels = sorted({item.label.value for item in chunk.meta.doc_items})
            raise ChunkTooLargeError(
                f"Chunk {chunk_index} in {docling_path.name} has {token_count} tokens "
                f"(limit: {max_tokens}, labels: {labels}). Structural chunks, "
                "including tables, are never split."
            )

        source_start = normalized_markdown.find(source_chunk.text, source_cursor)
        if source_start >= 0:
            source_end = source_start + len(source_chunk.text)
            source_cursor = source_end
        else:
            source_start = None
            source_end = None

        headings = chunk.meta.headings or []
        page_numbers = sorted(
            {
                provenance.page_no
                for item in chunk.meta.doc_items
                for provenance in item.prov
            }
        )
        labels = [item.label.value for item in chunk.meta.doc_items]
        table_refs = [
            item.self_ref
            for item in chunk.meta.doc_items
            if item.label == DocItemLabel.TABLE
        ]
        prepared_chunks.append(
            PreparedChunk(
                chunk_index=chunk_index,
                text=text,
                token_count=token_count,
                page_number=page_numbers[0] if len(page_numbers) == 1 else None,
                section_title=headings[-1] if headings else None,
                source_start=source_start,
                source_end=source_end,
                metadata={
                    "chunker": "docling_hierarchical",
                    "docling_version": DOCLING_VERSION,
                    "table_serializer": "compact_rows",
                    "source_table_serializer": "markdown",
                    "doc_item_refs": [item.self_ref for item in chunk.meta.doc_items],
                    "doc_item_labels": labels,
                    "headings": headings,
                    "page_numbers": page_numbers,
                    "contains_table": bool(table_refs),
                    "table_refs": table_refs,
                    "source_offset_basis": "normalized_markdown",
                    "source_offset_found": source_start is not None,
                },
                display_table=display_table,
            )
        )

    if not prepared_chunks:
        raise ValueError(f"Docling produced no chunks for {docling_path}")
    return prepared_chunks


def document_paths(row: SourceDocumentRow) -> tuple[Path, Path]:
    metadata = row["extraction_metadata"]
    source_local_path = metadata.get("source_local_path")
    markdown_local_path = metadata.get("markdown_local_path")
    if not isinstance(source_local_path, str) or not isinstance(
        markdown_local_path, str
    ):
        raise TypeError("Source-document extraction metadata has invalid local paths")

    docling_path = DOCLING_DOCUMENTS_DIR / Path(source_local_path).with_suffix(".json")
    markdown_path = MARKDOWN_DIR / markdown_local_path
    return docling_path, markdown_path


def _validate_table_integrity(
    doc: DoclingDocument,
    chunks: list[DocChunk],
) -> None:
    expected_refs = {table.self_ref for table in doc.tables}
    actual_counts = Counter(
        item.self_ref
        for chunk in chunks
        for item in chunk.meta.doc_items
        if item.label == DocItemLabel.TABLE
    )
    missing_refs = sorted(expected_refs - actual_counts.keys())
    repeated_refs = sorted(ref for ref, count in actual_counts.items() if count != 1)
    if missing_refs or repeated_refs:
        raise ValueError(
            "Hierarchical chunking did not preserve one complete chunk per table: "
            f"missing={missing_refs}, repeated={repeated_refs}"
        )


def _compact_table_chunk(chunk: DocChunk) -> DocChunk:
    if not any(item.label == DocItemLabel.TABLE for item in chunk.meta.doc_items):
        return chunk

    parts = []
    for item in chunk.meta.doc_items:
        if isinstance(item, TableItem):
            parts.append(_compact_table_text(item))
        elif isinstance(item, TextItem) and item.text:
            parts.append(item.text)
    return chunk.model_copy(update={"text": "\n".join(parts)})


def _compact_table_text(table: TableItem) -> str:
    return _compacted_table(table).text


def _compacted_table(table: TableItem) -> CompactedTable:
    rows: dict[int, list[tuple[int, str, int]]] = {}
    for origin_index, cell in enumerate(table.data.table_cells):
        text = " ".join(cell.text.split())
        if text:
            rows.setdefault(cell.start_row_offset_idx, []).append(
                (cell.start_col_offset_idx, text, origin_index)
            )
    parts = ["[TABLE]\n"]
    text_length = len(parts[0])
    cell_ranges = {}
    for line_index, row_index in enumerate(sorted(rows)):
        if line_index:
            parts.append("\n")
            text_length += 1
        for cell_index, (_column_index, text, origin_index) in enumerate(
            sorted(rows[row_index])
        ):
            if cell_index:
                parts.append(" | ")
                text_length += 3
            start = text_length
            parts.append(text)
            text_length += len(text)
            cell_ranges[origin_index] = (start, text_length)
    return CompactedTable(text="".join(parts), cell_ranges=cell_ranges)


def _display_table(
    source_chunk: DocChunk,
    compacted_chunk: DocChunk,
    contextualized_text: str,
) -> StoredDisplayTable | None:
    table_items = [
        item for item in source_chunk.meta.doc_items if isinstance(item, TableItem)
    ]
    nonempty_text_items = [
        item
        for item in source_chunk.meta.doc_items
        if isinstance(item, TextItem) and item.text
    ]
    if len(table_items) != 1 or nonempty_text_items:
        return None

    table = table_items[0]
    if (
        table.data.num_rows <= 0
        or table.data.num_cols <= 0
        or not any(" ".join(cell.text.split()) for cell in table.data.table_cells)
    ):
        return None
    compacted = _compacted_table(table)
    if compacted.text != compacted_chunk.text:
        return None
    chunk_start = contextualized_text.rfind(compacted.text)
    if chunk_start < 0:
        return None

    rows: list[list[StoredTableCell]] = [[] for _ in range(_physical_row_count(table))]
    for origin_index, cell in enumerate(table.data.table_cells):
        text = " ".join(cell.text.split())
        relative_range = compacted.cell_ranges.get(origin_index)
        text_start = (
            chunk_start + relative_range[0] if relative_range is not None else None
        )
        text_end = (
            chunk_start + relative_range[1] if relative_range is not None else None
        )
        rows[cell.start_row_offset_idx].append(
            StoredTableCell(
                text=text,
                column_index=cell.start_col_offset_idx,
                row_span=cell.end_row_offset_idx - cell.start_row_offset_idx,
                column_span=cell.end_col_offset_idx - cell.start_col_offset_idx,
                column_header=cell.column_header,
                row_header=cell.row_header,
                text_start=text_start,
                text_end=text_end,
            )
        )

    return StoredDisplayTable(
        table_ref=table.self_ref,
        column_count=_physical_column_count(table),
        rows=tuple(
            StoredTableRow(cells=tuple(sorted(row, key=lambda cell: cell.column_index)))
            for row in rows
        ),
    )


def _validate_display_table(
    source_chunk: DocChunk,
    display_table: StoredDisplayTable | None,
    chunk_text: str,
) -> None:
    table_items = [
        item for item in source_chunk.meta.doc_items if isinstance(item, TableItem)
    ]
    nonempty_text_items = [
        item
        for item in source_chunk.meta.doc_items
        if isinstance(item, TextItem) and item.text
    ]
    supported_table = (
        len(table_items) == 1
        and not nonempty_text_items
        and table_items[0].data.num_rows > 0
        and table_items[0].data.num_cols > 0
        and any(" ".join(cell.text.split()) for cell in table_items[0].data.table_cells)
    )
    if not supported_table:
        if display_table is not None:
            raise ValueError("Unsupported or empty table chunk has display metadata")
        return
    if display_table is None:
        raise ValueError("Supported table chunk is missing display metadata")

    table = table_items[0]
    if (
        display_table.table_ref != table.self_ref
        or display_table.column_count != _physical_column_count(table)
        or len(display_table.rows) != _physical_row_count(table)
    ):
        raise ValueError("Display table does not match Docling table geometry")

    expected_cells = sorted(
        (
            cell.start_row_offset_idx,
            cell.start_col_offset_idx,
            cell.end_row_offset_idx - cell.start_row_offset_idx,
            cell.end_col_offset_idx - cell.start_col_offset_idx,
            " ".join(cell.text.split()),
            cell.column_header,
            cell.row_header,
        )
        for cell in table.data.table_cells
    )
    actual_cells = sorted(
        (
            row_index,
            cell.column_index,
            cell.row_span,
            cell.column_span,
            cell.text,
            cell.column_header,
            cell.row_header,
        )
        for row_index, row in enumerate(display_table.rows)
        for cell in row.cells
    )
    if actual_cells != expected_cells:
        raise ValueError("Display cells do not match Docling origin cells")
    for row in display_table.rows:
        for cell in row.cells:
            if cell.text:
                if cell.text_start is None or cell.text_end is None:
                    raise ValueError("Non-empty display cell is missing text offsets")
                if chunk_text[cell.text_start : cell.text_end] != cell.text:
                    raise ValueError("Display cell offsets do not map to chunk text")
            elif cell.text_start is not None or cell.text_end is not None:
                raise ValueError("Empty display cell unexpectedly has text offsets")


def _physical_row_count(table: TableItem) -> int:
    return max(
        [table.data.num_rows]
        + [cell.end_row_offset_idx for cell in table.data.table_cells]
    )


def _physical_column_count(table: TableItem) -> int:
    return max(
        [table.data.num_cols]
        + [cell.end_col_offset_idx for cell in table.data.table_cells]
    )


def source_row_for_accession(accession_number: str) -> SourceDocumentRow:
    rows = load_source_document_rows()
    matches = [row for row in rows if row["accession_number"] == accession_number]
    if not matches:
        raise ValueError(f"Accession number is not in the manifest: {accession_number}")
    return matches[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate hierarchical Docling chunks for one SEC filing."
    )
    parser.add_argument("--accession-number", required=True)
    return parser.parse_args()


def main() -> None:
    from app.config import settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    row = source_row_for_accession(args.accession_number)
    docling_path, markdown_path = document_paths(row)
    chunks = chunk_document(
        docling_path,
        markdown_path,
        OpenAITokenCounter(settings.openai_embedding_model),
    )
    table_count = sum(bool(chunk.metadata["contains_table"]) for chunk in chunks)
    mapped_offset_count = sum(chunk.source_start is not None for chunk in chunks)
    logger.info(
        "Validated %d hierarchical chunks for %s (%d table chunks, %d source "
        "offsets, max %d tokens)",
        len(chunks),
        args.accession_number,
        table_count,
        mapped_offset_count,
        max(chunk.token_count for chunk in chunks),
    )


if __name__ == "__main__":
    main()
