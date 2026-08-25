"""Create section-aware chunks from parsed SEC filing documents."""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import tiktoken

from app.retrieval.display_tables import (
    StoredDisplayTable,
    StoredTableCell,
    StoredTableRow,
)
from ingestion.ingest_documents import SourceDocumentRow, load_source_document_rows
from ingestion.sec_parser import PARSER_VERSION, ParsedBlock, ParsedDocument

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PARSED_DOCUMENTS_DIR = REPOSITORY_ROOT / "data" / "parsed_documents"
MARKDOWN_DIR = REPOSITORY_ROOT / "data" / "markdown"
MIN_TARGET_TOKENS = 150
MIN_CHUNK_TOKENS = 100
MAX_CHUNK_TOKENS = 500
MAX_MERGED_CHUNK_TOKENS = 600
MAX_EMBEDDING_INPUT_TOKENS = 8_192
CHUNKER_VERSION = "sec_sections_v2"

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'])")

logger = logging.getLogger(__name__)


class TokenCounter(Protocol):
    def count_tokens(self, text: str) -> int: ...


class OpenAITokenCounter:
    def __init__(self, model: str) -> None:
        self.model = model
        self._encoding = tiktoken.encoding_for_model(model)

    def count_tokens(self, text: str) -> int:
        return len(self._encoding.encode(text, disallowed_special=()))


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


@dataclass
class _DraftChunk:
    section_key: str
    section_title: str
    headings: tuple[str, ...]
    parts: list[str] = field(default_factory=list)
    blocks: list[ParsedBlock] = field(default_factory=list)

    @property
    def text(self) -> str:
        return _contextualize(self.headings, "\n\n".join(self.parts))


class ChunkTooLargeError(ValueError):
    """A complete table cannot be sent to the configured embedding model."""


def chunk_document(
    parsed_path: Path,
    markdown_path: Path,
    token_counter: TokenCounter,
    *,
    min_tokens: int = MIN_CHUNK_TOKENS,
    max_tokens: int = MAX_CHUNK_TOKENS,
    max_merged_tokens: int = MAX_MERGED_CHUNK_TOKENS,
) -> list[PreparedChunk]:
    if max_tokens <= 0 or max_tokens > MAX_EMBEDDING_INPUT_TOKENS:
        raise ValueError(
            f"Prose chunk limit must be between 1 and {MAX_EMBEDDING_INPUT_TOKENS}"
        )
    if min_tokens <= 0 or min_tokens > max_merged_tokens:
        raise ValueError("Minimum chunk tokens must be between 1 and the merge limit")
    if max_merged_tokens < max_tokens or max_merged_tokens > MAX_EMBEDDING_INPUT_TOKENS:
        raise ValueError(
            "Merged chunk limit must be at least the prose limit and at most "
            f"{MAX_EMBEDDING_INPUT_TOKENS}"
        )
    document = ParsedDocument.from_dict(
        json.loads(parsed_path.read_text(encoding="utf-8"))
    )
    normalized_markdown = markdown_path.read_text(encoding="utf-8")
    _validate_markdown_offsets(document, normalized_markdown)

    prepared: list[PreparedChunk] = []
    for section in document.sections:
        headings = (section.title,)
        draft: _DraftChunk | None = None
        for block in section.blocks:
            if block.kind == "subheading":
                if draft is not None:
                    prepared.append(_prepare_prose(draft, token_counter, len(prepared)))
                    draft = None
                headings = (section.title, block.text)
                continue
            if block.kind == "table":
                table_intro = None
                if draft is not None and _can_attach_to_table(
                    draft,
                    block,
                    token_counter,
                ):
                    table_intro = draft
                    draft = None
                elif draft is not None:
                    prepared.append(_prepare_prose(draft, token_counter, len(prepared)))
                    draft = None
                prepared.append(
                    _prepare_table(
                        section.key,
                        section.title,
                        headings,
                        block,
                        token_counter,
                        len(prepared),
                        intro=table_intro,
                    )
                )
                continue

            body = f"- {block.text}" if block.kind == "list_item" else block.text
            fragments = _split_oversized_text(
                body,
                headings,
                token_counter,
                max_tokens,
            )
            for fragment in fragments:
                if draft is None:
                    draft = _DraftChunk(
                        section_key=section.key,
                        section_title=section.title,
                        headings=headings,
                    )
                candidate_body = "\n\n".join([*draft.parts, fragment])
                candidate_text = _contextualize(headings, candidate_body)
                if (
                    draft.parts
                    and token_counter.count_tokens(candidate_text) > max_tokens
                ):
                    prepared.append(_prepare_prose(draft, token_counter, len(prepared)))
                    draft = _DraftChunk(
                        section_key=section.key,
                        section_title=section.title,
                        headings=headings,
                    )
                draft.parts.append(fragment)
                if block not in draft.blocks:
                    draft.blocks.append(block)

        if draft is not None:
            prepared.append(_prepare_prose(draft, token_counter, len(prepared)))

    if not prepared:
        raise ValueError(f"Parsed SEC document produced no chunks: {parsed_path}")
    prepared = _merge_small_chunks(
        prepared,
        token_counter,
        min_tokens=min_tokens,
        max_merged_tokens=max_merged_tokens,
    )
    for chunk in prepared:
        if not any(character.isalnum() for character in chunk.text):
            raise ValueError(f"Chunk {chunk.chunk_index} contains no information")
        if (
            not chunk.metadata["contains_table"]
            and not chunk.metadata.get("merged_for_min_tokens")
            and chunk.token_count > max_tokens
        ):
            raise AssertionError(
                f"Prose chunk {chunk.chunk_index} exceeded {max_tokens} tokens"
            )
        if (
            not chunk.metadata["contains_table"]
            and chunk.metadata.get("merged_for_min_tokens")
            and chunk.token_count > max_merged_tokens
        ):
            raise AssertionError(
                f"Merged prose chunk {chunk.chunk_index} exceeded "
                f"{max_merged_tokens} tokens"
            )
        if chunk.token_count < min_tokens and chunk.display_table is None:
            raise AssertionError(
                f"Prose chunk {chunk.chunk_index} is below {min_tokens} tokens"
            )
    return prepared


def _merge_small_chunks(
    chunks: list[PreparedChunk],
    token_counter: TokenCounter,
    *,
    min_tokens: int,
    max_merged_tokens: int,
) -> list[PreparedChunk]:
    pending = list(chunks)
    merged: list[PreparedChunk] = []
    index = 0
    while index < len(pending):
        chunk = pending[index]
        if chunk.token_count >= min_tokens:
            merged.append(chunk)
            index += 1
            continue

        if index + 1 < len(pending):
            combined = _try_merge_chunks(
                chunk,
                pending[index + 1],
                token_counter,
                token_limit=max_merged_tokens,
            )
            if combined is not None:
                pending[index + 1] = combined
                index += 1
                continue

        if merged:
            combined = _try_merge_chunks(
                merged[-1],
                chunk,
                token_counter,
                token_limit=max_merged_tokens,
            )
            if combined is not None:
                merged[-1] = combined
                index += 1
                continue

        # A complete table may already exceed the prose merge limit. Attaching a
        # small neighbor is still safe as long as the embedding limit is respected.
        if index + 1 < len(pending):
            combined = _try_merge_chunks(
                chunk,
                pending[index + 1],
                token_counter,
                token_limit=MAX_EMBEDDING_INPUT_TOKENS,
                require_table=True,
            )
            if combined is not None:
                pending[index + 1] = combined
                index += 1
                continue

        if merged:
            combined = _try_merge_chunks(
                merged[-1],
                chunk,
                token_counter,
                token_limit=MAX_EMBEDDING_INPUT_TOKENS,
                require_table=True,
            )
            if combined is not None:
                merged[-1] = combined
                index += 1
                continue

        if chunk.display_table is not None:
            merged.append(_mark_small_table_exception(chunk))
            index += 1
            continue
        raise ValueError(
            f"Could not merge chunk {chunk.chunk_index} to reach {min_tokens} tokens"
        )

    return [_with_chunk_index(chunk, index) for index, chunk in enumerate(merged)]


def _try_merge_chunks(
    left: PreparedChunk,
    right: PreparedChunk,
    token_counter: TokenCounter,
    *,
    token_limit: int,
    require_table: bool = False,
) -> PreparedChunk | None:
    if left.display_table is not None and right.display_table is not None:
        return None
    if require_table and left.display_table is None and right.display_table is None:
        return None

    separator = "\n\n"
    text = left.text + separator + right.text
    token_count = token_counter.count_tokens(text)
    if token_count > token_limit:
        return None

    display_table = left.display_table
    if right.display_table is not None:
        display_table = _shift_display_table(
            right.display_table,
            len(left.text) + len(separator),
        )
    if display_table is not None:
        _validate_display_offsets(display_table, text)

    section_keys = _ordered_unique([*_section_keys(left), *_section_keys(right)])
    section_titles = _ordered_unique([*_section_titles(left), *_section_titles(right)])
    headings = _ordered_unique(
        [*_metadata_strings(left, "headings"), *_metadata_strings(right, "headings")]
    )
    block_ids = _ordered_unique(
        [
            *_metadata_strings(left, "block_ids"),
            *_metadata_strings(right, "block_ids"),
        ]
    )
    metadata = {
        "parser_version": left.metadata["parser_version"],
        "chunker_version": CHUNKER_VERSION,
        "section_key": section_keys[0],
        "section_keys": section_keys,
        "section_titles": section_titles,
        "headings": headings,
        "block_ids": block_ids,
        "contains_table": display_table is not None,
        "source_offset_basis": "normalized_markdown",
        "merged_for_min_tokens": True,
    }
    return PreparedChunk(
        chunk_index=left.chunk_index,
        text=text,
        token_count=token_count,
        page_number=(
            left.page_number if left.page_number == right.page_number else None
        ),
        section_title=" | ".join(section_titles) or None,
        source_start=_minimum_optional(left.source_start, right.source_start),
        source_end=_maximum_optional(left.source_end, right.source_end),
        metadata=metadata,
        display_table=display_table,
    )


def _shift_display_table(
    table: StoredDisplayTable,
    offset: int,
) -> StoredDisplayTable:
    return StoredDisplayTable(
        table_ref=table.table_ref,
        column_count=table.column_count,
        rows=tuple(
            StoredTableRow(
                cells=tuple(
                    StoredTableCell(
                        text=cell.text,
                        column_index=cell.column_index,
                        row_span=cell.row_span,
                        column_span=cell.column_span,
                        column_header=cell.column_header,
                        row_header=cell.row_header,
                        text_start=(
                            cell.text_start + offset
                            if cell.text_start is not None
                            else None
                        ),
                        text_end=(
                            cell.text_end + offset
                            if cell.text_end is not None
                            else None
                        ),
                    )
                    for cell in row.cells
                )
            )
            for row in table.rows
        ),
    )


def _mark_small_table_exception(chunk: PreparedChunk) -> PreparedChunk:
    return PreparedChunk(
        chunk_index=chunk.chunk_index,
        text=chunk.text,
        token_count=chunk.token_count,
        page_number=chunk.page_number,
        section_title=chunk.section_title,
        source_start=chunk.source_start,
        source_end=chunk.source_end,
        metadata={
            **chunk.metadata,
            "minimum_token_exception": "atomic_table",
        },
        display_table=chunk.display_table,
    )


def _with_chunk_index(chunk: PreparedChunk, chunk_index: int) -> PreparedChunk:
    return PreparedChunk(
        chunk_index=chunk_index,
        text=chunk.text,
        token_count=chunk.token_count,
        page_number=chunk.page_number,
        section_title=chunk.section_title,
        source_start=chunk.source_start,
        source_end=chunk.source_end,
        metadata=chunk.metadata,
        display_table=chunk.display_table,
    )


def _section_keys(chunk: PreparedChunk) -> list[str]:
    keys = _metadata_strings(chunk, "section_keys")
    return keys or [str(chunk.metadata["section_key"])]


def _section_titles(chunk: PreparedChunk) -> list[str]:
    titles = _metadata_strings(chunk, "section_titles")
    if titles:
        return titles
    return [chunk.section_title] if chunk.section_title is not None else []


def _metadata_strings(chunk: PreparedChunk, key: str) -> list[str]:
    value = chunk.metadata.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return value


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _minimum_optional(left: int | None, right: int | None) -> int | None:
    values = [value for value in (left, right) if value is not None]
    return min(values) if values else None


def _maximum_optional(left: int | None, right: int | None) -> int | None:
    values = [value for value in (left, right) if value is not None]
    return max(values) if values else None


def document_paths(row: SourceDocumentRow) -> tuple[Path, Path]:
    metadata = row["extraction_metadata"]
    parsed_local_path = metadata.get("parsed_local_path")
    markdown_local_path = metadata.get("markdown_local_path")
    if not isinstance(parsed_local_path, str) or not isinstance(
        markdown_local_path, str
    ):
        raise TypeError("Source-document extraction metadata has invalid local paths")
    return PARSED_DOCUMENTS_DIR / parsed_local_path, MARKDOWN_DIR / markdown_local_path


def source_row_for_accession(accession_number: str) -> SourceDocumentRow:
    rows = load_source_document_rows()
    matches = [row for row in rows if row["accession_number"] == accession_number]
    if not matches:
        raise ValueError(f"Accession number is not in the manifest: {accession_number}")
    return matches[0]


def _prepare_prose(
    draft: _DraftChunk,
    token_counter: TokenCounter,
    chunk_index: int,
) -> PreparedChunk:
    text = draft.text
    token_count = token_counter.count_tokens(text)
    starts = [
        block.markdown_start
        for block in draft.blocks
        if block.markdown_start is not None
    ]
    ends = [
        block.markdown_end for block in draft.blocks if block.markdown_end is not None
    ]
    return PreparedChunk(
        chunk_index=chunk_index,
        text=text,
        token_count=token_count,
        page_number=None,
        section_title=draft.section_title,
        source_start=min(starts) if starts else None,
        source_end=max(ends) if ends else None,
        metadata=_metadata(
            section_key=draft.section_key,
            headings=draft.headings,
            block_ids=[block.id for block in draft.blocks],
            contains_table=False,
        ),
    )


def _prepare_table(
    section_key: str,
    section_title: str,
    headings: tuple[str, ...],
    block: ParsedBlock,
    token_counter: TokenCounter,
    chunk_index: int,
    *,
    intro: _DraftChunk | None = None,
) -> PreparedChunk:
    table_body, ranges = _table_body_and_ranges(block)
    body = (
        "\n\n".join(["\n\n".join(intro.parts), table_body])
        if intro is not None
        else table_body
    )
    text = _contextualize(headings, body)
    table_start = text.index(table_body)
    token_count = token_counter.count_tokens(text)
    if token_count > MAX_EMBEDDING_INPUT_TOKENS:
        raise ChunkTooLargeError(
            f"Table {block.id} has {token_count} tokens; complete tables are kept "
            f"atomic and the embedding limit is {MAX_EMBEDDING_INPUT_TOKENS}"
        )
    if block.row_count is None or block.column_count is None:
        raise ValueError(f"Table {block.id} is missing geometry")

    rows: list[list[StoredTableCell]] = [[] for _ in range(block.row_count)]
    for cell_index, cell in enumerate(block.cells):
        relative_range = ranges.get(cell_index)
        rows[cell.row_index].append(
            StoredTableCell(
                text=cell.text,
                column_index=cell.column_index,
                row_span=cell.row_span,
                column_span=cell.column_span,
                column_header=cell.column_header,
                row_header=cell.row_header,
                text_start=(
                    table_start + relative_range[0]
                    if relative_range is not None
                    else None
                ),
                text_end=(
                    table_start + relative_range[1]
                    if relative_range is not None
                    else None
                ),
            )
        )
    display_table = StoredDisplayTable(
        table_ref=block.id,
        column_count=block.column_count,
        rows=tuple(
            StoredTableRow(cells=tuple(sorted(row, key=lambda cell: cell.column_index)))
            for row in rows
        ),
    )
    _validate_display_offsets(display_table, text)
    source_starts = (
        [
            candidate.markdown_start
            for candidate in intro.blocks
            if candidate.markdown_start is not None
        ]
        if intro is not None
        else []
    )
    if block.markdown_start is not None:
        source_starts.append(block.markdown_start)
    block_ids = (
        [candidate.id for candidate in intro.blocks] if intro is not None else []
    )
    block_ids.append(block.id)
    return PreparedChunk(
        chunk_index=chunk_index,
        text=text,
        token_count=token_count,
        page_number=None,
        section_title=section_title,
        source_start=min(source_starts) if source_starts else None,
        source_end=block.markdown_end,
        metadata=_metadata(
            section_key=section_key,
            headings=headings,
            block_ids=block_ids,
            contains_table=True,
        ),
        display_table=display_table,
    )


def _metadata(
    *,
    section_key: str,
    headings: tuple[str, ...],
    block_ids: list[str],
    contains_table: bool,
) -> dict[str, object]:
    return {
        "parser_version": PARSER_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "section_key": section_key,
        "headings": list(headings),
        "block_ids": block_ids,
        "contains_table": contains_table,
        "source_offset_basis": "normalized_markdown",
    }


def _can_attach_to_table(
    draft: _DraftChunk,
    block: ParsedBlock,
    token_counter: TokenCounter,
) -> bool:
    if token_counter.count_tokens(draft.text) >= MIN_TARGET_TOKENS:
        return False
    table_body, _ = _table_body_and_ranges(block)
    combined = _contextualize(
        draft.headings,
        "\n\n".join(["\n\n".join(draft.parts), table_body]),
    )
    return token_counter.count_tokens(combined) <= MAX_EMBEDDING_INPUT_TOKENS


def _contextualize(headings: tuple[str, ...], body: str) -> str:
    return "\n".join(headings) + "\n\n" + body


def _split_oversized_text(
    text: str,
    headings: tuple[str, ...],
    token_counter: TokenCounter,
    max_tokens: int,
) -> list[str]:
    if token_counter.count_tokens(_contextualize(headings, text)) <= max_tokens:
        return [text]
    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY_RE.split(text)
        if sentence.strip()
    ]
    if len(sentences) == 1:
        return _split_words(text, headings, token_counter, max_tokens)

    fragments: list[str] = []
    current = ""
    for sentence in sentences:
        if token_counter.count_tokens(_contextualize(headings, sentence)) > max_tokens:
            if current:
                fragments.append(current)
                current = ""
            fragments.extend(
                _split_words(sentence, headings, token_counter, max_tokens)
            )
            continue
        candidate = f"{current} {sentence}".strip()
        if (
            current
            and token_counter.count_tokens(_contextualize(headings, candidate))
            > max_tokens
        ):
            fragments.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        fragments.append(current)
    return fragments


def _split_words(
    text: str,
    headings: tuple[str, ...],
    token_counter: TokenCounter,
    max_tokens: int,
) -> list[str]:
    words = text.split()
    fragments: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if (
            current
            and token_counter.count_tokens(_contextualize(headings, candidate))
            > max_tokens
        ):
            fragments.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
        if (
            token_counter.count_tokens(_contextualize(headings, " ".join(current)))
            > max_tokens
        ):
            raise ChunkTooLargeError(
                "A single whitespace-delimited value exceeds the prose token limit"
            )
    if current:
        fragments.append(" ".join(current))
    return fragments


def _table_body_and_ranges(
    block: ParsedBlock,
) -> tuple[str, dict[int, tuple[int, int]]]:
    indexed_rows: dict[int, list[tuple[int, int]]] = {}
    for index, cell in enumerate(block.cells):
        if cell.text:
            indexed_rows.setdefault(cell.row_index, []).append(
                (cell.column_index, index)
            )

    parts = ["[TABLE]\n"]
    length = len(parts[0])
    ranges: dict[int, tuple[int, int]] = {}
    for line_index, (_, row) in enumerate(sorted(indexed_rows.items())):
        if line_index:
            parts.append("\n")
            length += 1
        for value_index, (_, cell_index) in enumerate(sorted(row)):
            if value_index:
                parts.append(" | ")
                length += 3
            value = block.cells[cell_index].text
            start = length
            parts.append(value)
            length += len(value)
            ranges[cell_index] = (start, length)
    return "".join(parts), ranges


def _validate_markdown_offsets(
    document: ParsedDocument,
    markdown: str,
) -> None:
    for section in document.sections:
        for block in section.blocks:
            if block.markdown_start is None or block.markdown_end is None:
                raise ValueError(f"Parsed block {block.id} is missing Markdown offsets")
            rendered = markdown[block.markdown_start : block.markdown_end]
            if block.kind == "paragraph" and rendered != block.text:
                raise ValueError(f"Markdown offsets do not match paragraph {block.id}")
            if block.kind == "list_item" and rendered != f"- {block.text}":
                raise ValueError(f"Markdown offsets do not match list item {block.id}")
            if block.kind == "subheading" and rendered != f"## {block.text}":
                raise ValueError(f"Markdown offsets do not match subheading {block.id}")
            if block.kind == "table" and not rendered.startswith("|"):
                raise ValueError(f"Markdown offsets do not match table {block.id}")


def _validate_display_offsets(table: StoredDisplayTable, text: str) -> None:
    for row in table.rows:
        for cell in row.cells:
            if cell.text:
                if cell.text_start is None or cell.text_end is None:
                    raise ValueError("Non-empty table cell has no chunk-text range")
                if text[cell.text_start : cell.text_end] != cell.text:
                    raise ValueError("Table cell range does not map to chunk text")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate section-aware chunks for one parsed SEC filing."
    )
    parser.add_argument("--accession-number", required=True)
    return parser.parse_args()


def main() -> None:
    from app.config import settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    row = source_row_for_accession(args.accession_number)
    parsed_path, markdown_path = document_paths(row)
    chunks = chunk_document(
        parsed_path,
        markdown_path,
        OpenAITokenCounter(settings.openai_embedding_model),
    )
    table_count = sum(bool(chunk.metadata["contains_table"]) for chunk in chunks)
    token_counts = [chunk.token_count for chunk in chunks]
    logger.info(
        "Validated %d chunks for %s (%d tables, min %d, max %d tokens)",
        len(chunks),
        args.accession_number,
        table_count,
        min(token_counts),
        max(token_counts),
    )


if __name__ == "__main__":
    main()
