"""Parse SEC filing HTML into clean, sectioned, parser-neutral documents."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal, cast

from lxml import html
from lxml.html import HtmlElement

SUPPORTED_FORMS = {"10-K", "F-1", "424B4"}
PARSER_VERSION = "sec_html_v1"

BlockKind = Literal["paragraph", "list_item", "subheading", "table"]

_BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "center",
    "dd",
    "div",
    "dl",
    "dt",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}
_REMOVED_TAGS = {"script", "style", "noscript", "svg", "ix:header", "ix:exclude"}
_BULLET_MARKERS = {"•", "·", "▪", "◦", "‣", "-", "–", "—", "o"}
_SPACE_RE = re.compile(r"\s+")
_ITEM_RE = re.compile(
    r"^(?:part\s+[ivx]+\s+)?item\s+(\d{1,2}[a-z]?)\b[\s.:\-–—]*(.*)$",
    re.IGNORECASE,
)
_PART_RE = re.compile(r"^part\s+([ivx]+)\.?$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^[($€£]?[-+]?\d[\d,.%$€£()\-–— ]*$")

_TEN_K_ITEM_TITLES = {
    "1": "Business",
    "1a": "Risk Factors",
    "1b": "Unresolved Staff Comments",
    "1c": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant’s Common Equity and Related Stockholder Matters",
    "6": "Reserved",
    "7": "Management’s Discussion and Analysis of Financial Condition and Results of Operations",
    "7a": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements With Accountants on Accounting and Financial Disclosure",
    "9a": "Controls and Procedures",
    "9b": "Other Information",
    "9c": "Disclosure Regarding Foreign Jurisdictions That Prevent Inspections",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership of Certain Beneficial Owners and Management",
    "13": "Certain Relationships and Related Transactions, and Director Independence",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}

_PROSPECTUS_TITLES = {
    "prospectus summary": ("prospectus_summary", "Prospectus Summary"),
    "risk factors": ("risk_factors", "Risk Factors"),
    "use of proceeds": ("use_of_proceeds", "Use of Proceeds"),
    "dividend policy": ("dividend_policy", "Dividend Policy"),
    "capitalization": ("capitalization", "Capitalization"),
    "dilution": ("dilution", "Dilution"),
    "management's discussion and analysis of financial condition and results of operations": (
        "mda",
        "Management’s Discussion and Analysis of Financial Condition and Results of Operations",
    ),
    "management discussion and analysis of financial condition and results of operations": (
        "mda",
        "Management’s Discussion and Analysis of Financial Condition and Results of Operations",
    ),
    "business": ("business", "Business"),
    "management": ("management", "Management"),
    "principal shareholders": ("principal_shareholders", "Principal Shareholders"),
    "principal and selling shareholders": (
        "principal_shareholders",
        "Principal and Selling Shareholders",
    ),
    "related party transactions": (
        "related_party_transactions",
        "Related-Party Transactions",
    ),
    "certain relationships and related party transactions": (
        "related_party_transactions",
        "Certain Relationships and Related-Party Transactions",
    ),
    "description of share capital": (
        "description_of_share_capital",
        "Description of Share Capital",
    ),
    "description of share capital and bylaws": (
        "description_of_share_capital",
        "Description of Share Capital and Bylaws",
    ),
    "taxation": ("taxation", "Taxation"),
    "underwriting": ("underwriting", "Underwriting"),
    "legal matters": ("legal_matters", "Legal Matters"),
    "experts": ("experts", "Experts"),
    "financial statements": ("financial_statements", "Financial Statements"),
    "index to financial statements": (
        "financial_statements",
        "Financial Statements",
    ),
    "index to consolidated financial statements": (
        "financial_statements",
        "Consolidated Financial Statements",
    ),
}


@dataclass
class ParsedTableCell:
    text: str
    row_index: int
    column_index: int
    row_span: int = 1
    column_span: int = 1
    column_header: bool = False
    row_header: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "row_span": self.row_span,
            "column_span": self.column_span,
            "column_header": self.column_header,
            "row_header": self.row_header,
        }

    @classmethod
    def from_dict(cls, value: object) -> ParsedTableCell:
        data = _object(value, "table cell")
        return cls(
            text=_string(data, "text", allow_empty=True),
            row_index=_integer(data, "row_index", minimum=0),
            column_index=_integer(data, "column_index", minimum=0),
            row_span=_integer(data, "row_span", minimum=1),
            column_span=_integer(data, "column_span", minimum=1),
            column_header=_boolean(data, "column_header"),
            row_header=_boolean(data, "row_header"),
        )


@dataclass
class ParsedBlock:
    id: str
    kind: BlockKind
    text: str
    html_locator: str
    markdown_start: int | None = None
    markdown_end: int | None = None
    level: int | None = None
    row_count: int | None = None
    column_count: int | None = None
    cells: list[ParsedTableCell] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "html_locator": self.html_locator,
            "markdown_start": self.markdown_start,
            "markdown_end": self.markdown_end,
        }
        if self.level is not None:
            value["level"] = self.level
        if self.kind == "table":
            value.update(
                {
                    "row_count": self.row_count,
                    "column_count": self.column_count,
                    "cells": [cell.to_dict() for cell in self.cells],
                }
            )
        return value

    @classmethod
    def from_dict(cls, value: object) -> ParsedBlock:
        data = _object(value, "block")
        kind = _string(data, "kind")
        if kind not in {"paragraph", "list_item", "subheading", "table"}:
            raise ValueError(f"Unsupported parsed block kind: {kind!r}")
        block = cls(
            id=_string(data, "id"),
            kind=cast(BlockKind, kind),
            text=_string(data, "text"),
            html_locator=_string(data, "html_locator"),
            markdown_start=_optional_integer(data, "markdown_start", minimum=0),
            markdown_end=_optional_integer(data, "markdown_end", minimum=1),
            level=_optional_integer(data, "level", minimum=2),
            row_count=_optional_integer(data, "row_count", minimum=1),
            column_count=_optional_integer(data, "column_count", minimum=1),
            cells=[
                ParsedTableCell.from_dict(cell)
                for cell in _list(data.get("cells", []), "block cells")
            ],
        )
        if (block.markdown_start is None) != (block.markdown_end is None):
            raise ValueError("Parsed block Markdown offsets must both be present")
        if (
            block.markdown_start is not None
            and block.markdown_end is not None
            and block.markdown_end <= block.markdown_start
        ):
            raise ValueError("Parsed block Markdown offsets are invalid")
        if block.kind == "table" and (
            block.row_count is None or block.column_count is None or not block.cells
        ):
            raise ValueError("Parsed table is missing geometry")
        return block


@dataclass
class ParsedSection:
    key: str
    title: str
    detection_method: str
    blocks: list[ParsedBlock] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "title": self.title,
            "detection_method": self.detection_method,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, value: object) -> ParsedSection:
        data = _object(value, "section")
        return cls(
            key=_string(data, "key"),
            title=_string(data, "title"),
            detection_method=_string(data, "detection_method"),
            blocks=[
                ParsedBlock.from_dict(block)
                for block in _list(data.get("blocks"), "section blocks")
            ],
        )


@dataclass
class ParsedDocument:
    form: str
    source_path: str
    sections: list[ParsedSection]
    audit: dict[str, int]
    source_sha256: str | None = None
    markdown_sha256: str | None = None
    schema_version: int = 1
    parser_version: str = PARSER_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "parser_version": self.parser_version,
            "form": self.form,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "markdown_sha256": self.markdown_sha256,
            "sections": [section.to_dict() for section in self.sections],
            "audit": dict(sorted(self.audit.items())),
        }

    @classmethod
    def from_dict(cls, value: object) -> ParsedDocument:
        data = _object(value, "parsed document")
        if _integer(data, "schema_version", minimum=1) != 1:
            raise ValueError("Unsupported parsed-document schema version")
        parser_version = _string(data, "parser_version")
        if parser_version != PARSER_VERSION:
            raise ValueError(
                f"Unsupported parser version {parser_version!r}; expected {PARSER_VERSION!r}"
            )
        form = _string(data, "form")
        if form not in SUPPORTED_FORMS:
            raise ValueError(f"Unsupported SEC form in parsed document: {form!r}")
        audit_value = _object(data.get("audit"), "parse audit")
        audit = {
            str(key): _plain_integer(value, f"parse audit field {key!r}", minimum=0)
            for key, value in audit_value.items()
        }
        sections = [
            ParsedSection.from_dict(section)
            for section in _list(data.get("sections"), "document sections")
        ]
        if not sections or not any(section.blocks for section in sections):
            raise ValueError("Parsed document contains no content blocks")
        return cls(
            form=form,
            source_path=_string(data, "source_path"),
            sections=sections,
            audit=audit,
            source_sha256=_optional_hash(data, "source_sha256"),
            markdown_sha256=_optional_hash(data, "markdown_sha256"),
            parser_version=parser_version,
        )


@dataclass
class _Candidate:
    kind: Literal["paragraph", "list_item", "table"]
    text: str
    html_locator: str
    style: str
    node: HtmlElement
    anchor_heading: tuple[str, str] | None = None
    row_count: int | None = None
    column_count: int | None = None
    cells: list[ParsedTableCell] = field(default_factory=list)


class _Extractor:
    def __init__(
        self,
        root: HtmlElement,
        anchor_headings: dict[str, tuple[str, str]],
    ) -> None:
        self.root = root
        self.anchor_headings = anchor_headings
        self.pending_heading: tuple[str, str] | None = None
        self.candidates: list[_Candidate] = []
        self.audit: Counter[str] = Counter()

    def extract(self) -> list[_Candidate]:
        body_values = self.root.xpath("//body")
        body = body_values[0] if body_values else self.root
        self._walk(cast(HtmlElement, body))
        return self.candidates

    def _walk(self, node: HtmlElement) -> None:
        target = node.get("id") or node.get("name")
        if target and target in self.anchor_headings:
            self.pending_heading = self.anchor_headings[target]

        tag = _tag(node)
        if tag == "table":
            self._emit_table(node)
            return
        if tag in {"ul", "ol"}:
            for item in node.xpath("./li"):
                text = _clean_text(_text_with_breaks(cast(HtmlElement, item)))
                if _has_information(text):
                    self._emit("list_item", text, cast(HtmlElement, item))
                else:
                    self.audit["empty_or_punctuation"] += 1
            return

        block_children = [
            child
            for child in node
            if isinstance(child.tag, str)
            and _tag(cast(HtmlElement, child)) in _BLOCK_TAGS
        ]
        if tag in _BLOCK_TAGS and not block_children:
            self._capture_descendant_anchor(node)
            lines = [
                _clean_text(line)
                for line in _text_with_breaks(node).splitlines()
                if _clean_text(line)
            ]
            for line in lines:
                if _has_information(line):
                    self._emit("paragraph", line, node)
                else:
                    self.audit["empty_or_punctuation"] += 1
            return

        for child in node:
            if isinstance(child.tag, str):
                self._walk(cast(HtmlElement, child))

    def _capture_descendant_anchor(self, node: HtmlElement) -> None:
        if self.pending_heading is not None:
            return
        for value in node.xpath(".//*[@id or @name]"):
            element = cast(HtmlElement, value)
            target = element.get("id") or element.get("name")
            if target and target in self.anchor_headings:
                self.pending_heading = self.anchor_headings[target]
                return

    def _emit(
        self,
        kind: Literal["paragraph", "list_item"],
        text: str,
        node: HtmlElement,
    ) -> None:
        self.candidates.append(
            _Candidate(
                kind=kind,
                text=text,
                html_locator=_locator(node),
                style=_style_context(node),
                node=node,
                anchor_heading=self.pending_heading,
            )
        )
        self.pending_heading = None

    def _emit_table(self, table: HtmlElement) -> None:
        cells, row_count, column_count = _table_cells(table)
        informative_cells = [cell for cell in cells if _has_information(cell.text)]
        if not informative_cells:
            self.audit["empty_table"] += 1
            return

        table_text = " ".join(cell.text for cell in informative_cells)
        internal_links = table.xpath(".//a[starts-with(@href, '#')]")
        if "table of contents" in table_text.casefold() or len(internal_links) >= 2:
            self.audit["navigation_table"] += 1
            return

        rows: dict[int, list[ParsedTableCell]] = {}
        for cell in cells:
            if cell.text:
                rows.setdefault(cell.row_index, []).append(cell)

        if _is_bullet_table(rows):
            for row in rows.values():
                values = [
                    cell.text
                    for cell in sorted(row, key=lambda cell: cell.column_index)
                ]
                text = _clean_text(
                    " ".join(value for value in values if value not in _BULLET_MARKERS)
                )
                if _has_information(text):
                    self._emit("list_item", text, table)
            self.audit["layout_table_to_list"] += 1
            return

        numeric_cells = sum(_looks_numeric(cell.text) for cell in informative_cells)
        explicit_headers = any(cell.column_header or cell.row_header for cell in cells)
        meaningful_columns = len({cell.column_index for cell in informative_cells})
        data_table = (
            row_count >= 2
            and meaningful_columns >= 2
            and (numeric_cells >= 2 or explicit_headers)
        )
        if not data_table and _is_text_layout_table(rows):
            for row in rows.values():
                text = _clean_text(
                    " ".join(
                        cell.text
                        for cell in sorted(row, key=lambda cell: cell.column_index)
                    )
                )
                if _has_information(text):
                    self._emit("paragraph", text, table)
            self.audit["layout_table_to_text"] += 1
            return

        text = _compact_table_text(cells)
        self.candidates.append(
            _Candidate(
                kind="table",
                text=text,
                html_locator=_locator(table),
                style=_style_context(table),
                node=table,
                anchor_heading=self.pending_heading,
                row_count=row_count,
                column_count=column_count,
                cells=cells,
            )
        )
        self.pending_heading = None
        self.audit["data_table"] += 1


def parse_sec_filing(
    source: bytes,
    *,
    form: str,
    source_path: str,
) -> ParsedDocument:
    """Parse one supported filing without making network or database calls."""
    if form not in SUPPORTED_FORMS:
        raise ValueError(
            f"Unsupported SEC form {form!r}; supported forms: {sorted(SUPPORTED_FORMS)}"
        )
    parser = html.HTMLParser(encoding="utf-8", recover=True, remove_comments=True)
    root = html.document_fromstring(source, parser=parser)
    hidden_node_count = _remove_hidden_and_noncontent(cast(HtmlElement, root))

    anchor_headings = _linked_section_targets(cast(HtmlElement, root), form)
    extractor = _Extractor(cast(HtmlElement, root), anchor_headings)
    extractor.audit["hidden_nodes"] = hidden_node_count
    candidates = _remove_furniture(extractor.extract(), extractor.audit)
    sections = _build_sections(candidates, form, extractor.audit)
    if not any(section.blocks for section in sections):
        raise ValueError(f"SEC parser produced no content for {source_path}")

    audit = dict(extractor.audit)
    audit["sections"] = len(sections)
    audit["blocks"] = sum(len(section.blocks) for section in sections)
    return ParsedDocument(
        form=form,
        source_path=source_path,
        sections=sections,
        audit=audit,
    )


def render_markdown(document: ParsedDocument) -> str:
    """Render canonical Markdown and record exact offsets on every block."""
    parts: list[str] = []
    length = 0

    def append(value: str) -> None:
        nonlocal length
        parts.append(value)
        length += len(value)

    for section_index, section in enumerate(document.sections):
        if section_index:
            append("\n")
        append(f"# {section.title}\n\n")
        for block in section.blocks:
            block.markdown_start = length
            if block.kind == "subheading":
                rendered = f"## {block.text}"
            elif block.kind == "list_item":
                rendered = f"- {block.text}"
            elif block.kind == "table":
                rendered = _table_markdown(block)
            else:
                rendered = block.text
            append(rendered)
            block.markdown_end = length
            append("\n\n")
    return "".join(parts).rstrip() + "\n"


def _build_sections(
    candidates: list[_Candidate],
    form: str,
    audit: Counter[str],
) -> list[ParsedSection]:
    sections = [
        ParsedSection(
            key="front_matter",
            title="Front Matter",
            detection_method="default",
        )
    ]
    current = sections[0]
    seen_section_keys: set[str] = set()
    block_number = 0

    for candidate in candidates:
        heading = candidate.anchor_heading
        method = "toc_anchor"
        text_heading = _section_heading(form, candidate.text)
        if heading is None and text_heading is not None and len(candidate.text) <= 180:
            heading = text_heading
            method = "body_heading"

        if heading is not None:
            key, title = heading
            if key not in seen_section_keys:
                current = ParsedSection(key=key, title=title, detection_method=method)
                sections.append(current)
                seen_section_keys.add(key)
                audit[f"section_{method}"] += 1
            elif current.key != key:
                audit["repeated_section_heading"] += 1

            if text_heading == heading or _heading_only_text(candidate.text, title):
                continue

        if candidate.kind != "table" and _is_styled_subheading(candidate):
            kind: BlockKind = "subheading"
            level = 2
        else:
            kind = candidate.kind
            level = None

        block_number += 1
        current.blocks.append(
            ParsedBlock(
                id=f"b{block_number:05d}",
                kind=kind,
                text=candidate.text,
                html_locator=candidate.html_locator,
                level=level,
                row_count=candidate.row_count,
                column_count=candidate.column_count,
                cells=candidate.cells,
            )
        )

    return [section for section in sections if section.blocks]


def _remove_hidden_and_noncontent(root: HtmlElement) -> int:
    removed = 0
    for node in list(root.iter()):
        if not isinstance(node.tag, str):
            continue
        tag = _tag(cast(HtmlElement, node))
        style = (node.get("style") or "").replace(" ", "").casefold()
        hidden = (
            tag in _REMOVED_TAGS
            or node.get("hidden") is not None
            or (node.get("aria-hidden") or "").casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        if hidden:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
                removed += 1
    return removed


def _linked_section_targets(
    root: HtmlElement,
    form: str,
) -> dict[str, tuple[str, str]]:
    targets: dict[str, tuple[str, str]] = {}
    for anchor in root.xpath(".//a[@href]"):
        element = cast(HtmlElement, anchor)
        href = element.get("href") or ""
        if not href.startswith("#") or len(href) == 1:
            continue
        heading = _section_heading(form, _clean_text(element.text_content()))
        if heading is not None:
            targets.setdefault(href[1:], heading)
    return targets


def _section_heading(form: str, text: str) -> tuple[str, str] | None:
    normalized = _heading_normal_form(text)
    if not normalized:
        return None
    if form == "10-K":
        part_match = _PART_RE.fullmatch(normalized)
        if part_match:
            part = part_match.group(1).lower()
            return f"part_{part}", f"Part {part.upper()}"
        item_match = _ITEM_RE.match(normalized)
        if item_match:
            item = item_match.group(1).lower()
            title = _TEN_K_ITEM_TITLES.get(item)
            if title is None:
                return None
            return f"item_{item}", f"Item {item.upper()}. {title}"
        return None

    comparable = normalized.casefold().replace("’", "'")
    comparable = re.sub(r"\s+", " ", comparable).strip(" .:-–—")
    comparable = re.sub(r"\s+\d+$", "", comparable)
    for candidate, heading in sorted(
        _PROSPECTUS_TITLES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if comparable == candidate or comparable.startswith(f"{candidate} ("):
            return heading
    return None


def _heading_normal_form(text: str) -> str:
    value = _clean_text(text).replace("\u2011", "-")
    value = re.sub(r"\.{2,}\s*\d*$", "", value)
    return value.strip()


def _heading_only_text(text: str, title: str) -> bool:
    comparable = _heading_normal_form(text).casefold().replace("’", "'")
    expected = title.casefold().replace("’", "'")
    return comparable == expected or comparable.rstrip(" .:-–—") == expected.rstrip(
        " .:-–—"
    )


def _is_styled_subheading(candidate: _Candidate) -> bool:
    text = candidate.text
    if not 2 <= len(text) <= 180 or len(text.split()) > 24:
        return False
    if text.endswith((".", ";", ",")) or _looks_numeric(text):
        return False
    tag = _tag(candidate.node)
    style = candidate.style
    return (
        tag.startswith("h")
        or "font-weight:700" in style
        or "font-weight:bold" in style
        or "text-align:center" in style
    )


def _remove_furniture(
    candidates: list[_Candidate],
    audit: Counter[str],
) -> list[_Candidate]:
    fingerprints = Counter(
        _fingerprint(candidate.text)
        for candidate in candidates
        if candidate.kind != "table"
    )
    kept: list[_Candidate] = []
    previous: str | None = None
    pending_heading: tuple[str, str] | None = None
    for candidate in candidates:
        if candidate.anchor_heading is None and pending_heading is not None:
            candidate.anchor_heading = pending_heading
        pending_heading = None
        fingerprint = _fingerprint(candidate.text)
        text = candidate.text
        if candidate.kind != "table" and (
            text.casefold() == "table of contents"
            or (text.isdigit() and len(text) <= 4)
        ):
            pending_heading = candidate.anchor_heading
            audit["page_furniture"] += 1
            continue
        if candidate.kind != "table" and _is_filing_chrome(text):
            pending_heading = candidate.anchor_heading
            audit["filing_chrome"] += 1
            continue
        if (
            candidate.kind != "table"
            and len(text) <= 120
            and fingerprints[fingerprint] >= 3
            and _has_furniture_style(candidate.style)
        ):
            pending_heading = candidate.anchor_heading
            audit["repeated_furniture"] += 1
            continue
        if candidate.kind != "table" and fingerprint == previous:
            pending_heading = candidate.anchor_heading
            audit["adjacent_duplicate"] += 1
            continue
        kept.append(candidate)
        previous = fingerprint if candidate.kind != "table" else None
    return kept


def _has_furniture_style(style: str) -> bool:
    return any(
        signal in style
        for signal in ("position:absolute", "position:fixed", "bottom:0", "page-break")
    )


def _is_filing_chrome(text: str) -> bool:
    comparable = text.strip().casefold()
    return comparable in {"form 10-k", "(mark one)", "index"} or comparable.startswith(
        ("commission file no.", "commission file number:")
    )


def _table_cells(
    table: HtmlElement,
) -> tuple[list[ParsedTableCell], int, int]:
    row_elements = table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")
    cells: list[ParsedTableCell] = []
    occupied: set[tuple[int, int]] = set()
    max_column = 0
    for row_index, row_value in enumerate(row_elements):
        row = cast(HtmlElement, row_value)
        column_index = 0
        for cell_value in row.xpath("./th | ./td"):
            cell = cast(HtmlElement, cell_value)
            while (row_index, column_index) in occupied:
                column_index += 1
            row_span = _positive_int(cell.get("rowspan"))
            column_span = _positive_int(cell.get("colspan"))
            text = _clean_text(_text_with_breaks(cell))
            is_header = _tag(cell) == "th"
            cells.append(
                ParsedTableCell(
                    text=text,
                    row_index=row_index,
                    column_index=column_index,
                    row_span=row_span,
                    column_span=column_span,
                    column_header=is_header and row_index == 0,
                    row_header=is_header and column_index == 0 and row_index > 0,
                )
            )
            for occupied_row in range(row_index, row_index + row_span):
                for occupied_column in range(column_index, column_index + column_span):
                    occupied.add((occupied_row, occupied_column))
            column_index += column_span
            max_column = max(max_column, column_index)
    row_count = max(
        len(row_elements),
        max((cell.row_index + cell.row_span for cell in cells), default=0),
    )
    return cells, row_count, max_column


def _is_bullet_table(rows: dict[int, list[ParsedTableCell]]) -> bool:
    bullet_rows = 0
    meaningful_rows = 0
    for row in rows.values():
        values = [
            cell.text
            for cell in sorted(row, key=lambda cell: cell.column_index)
            if cell.text
        ]
        if not values:
            continue
        meaningful_rows += 1
        first = values[0].strip()
        if first in _BULLET_MARKERS or first.rstrip(".") in _BULLET_MARKERS:
            bullet_rows += 1
    return meaningful_rows > 0 and bullet_rows >= max(1, meaningful_rows // 2)


def _is_text_layout_table(rows: dict[int, list[ParsedTableCell]]) -> bool:
    if not rows:
        return False
    return all(
        len([cell for cell in row if _has_information(cell.text)]) <= 2
        for row in rows.values()
    )


def _compact_table_text(cells: list[ParsedTableCell]) -> str:
    rows: dict[int, list[ParsedTableCell]] = {}
    for cell in cells:
        if cell.text:
            rows.setdefault(cell.row_index, []).append(cell)
    lines = [
        " | ".join(
            cell.text for cell in sorted(row, key=lambda cell: cell.column_index)
        )
        for _, row in sorted(rows.items())
    ]
    return "[TABLE]\n" + "\n".join(lines)


def _table_markdown(block: ParsedBlock) -> str:
    if block.row_count is None or block.column_count is None:
        raise ValueError(f"Table block {block.id} has no geometry")
    grid = [["" for _ in range(block.column_count)] for _ in range(block.row_count)]
    for cell in block.cells:
        grid[cell.row_index][cell.column_index] = cell.text.replace("|", "\\|")
    lines = ["| " + " | ".join(row) + " |" for row in grid]
    separator = "| " + " | ".join("---" for _ in range(block.column_count)) + " |"
    lines.insert(1, separator)
    return "\n".join(lines)


def _text_with_breaks(node: HtmlElement) -> str:
    parts: list[str] = []

    def visit(element: HtmlElement) -> None:
        if element.text:
            parts.append(element.text)
        for child_value in element:
            if not isinstance(child_value.tag, str):
                continue
            child = cast(HtmlElement, child_value)
            if _tag(child) == "br":
                parts.append("\n")
            else:
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return "".join(parts)


def _style_context(node: HtmlElement) -> str:
    styles = []
    current: HtmlElement | None = node
    for _ in range(3):
        if current is None:
            break
        style = current.get("style")
        if style:
            styles.append(style.replace(" ", "").casefold())
        parent = current.getparent()
        current = cast(HtmlElement | None, parent)
    return ";".join(styles)


def _clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u00ad", "").replace("\u200b", "")
    return _SPACE_RE.sub(" ", normalized).strip()


def _has_information(text: str) -> bool:
    return any(character.isalnum() for character in text)


def _looks_numeric(text: str) -> bool:
    return bool(_NUMBER_RE.fullmatch(text.strip()))


def _fingerprint(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip().casefold()


def _tag(node: HtmlElement) -> str:
    tag = str(node.tag).casefold()
    return tag.rsplit("}", 1)[-1]


def _locator(node: HtmlElement) -> str:
    return node.getroottree().getpath(node)


def _positive_int(value: str | None) -> int:
    if value is None:
        return 1
    try:
        return max(1, int(value))
    except ValueError:
        return 1


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be a list")
    return value


def _string(
    data: dict[str, object],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TypeError(f"Field {key!r} must be a string")
    return value


def _integer(data: dict[str, object], key: str, *, minimum: int) -> int:
    return _plain_integer(data.get(key), f"Field {key!r}", minimum=minimum)


def _optional_integer(
    data: dict[str, object],
    key: str,
    *,
    minimum: int,
) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    return _plain_integer(value, f"Field {key!r}", minimum=minimum)


def _plain_integer(value: object, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TypeError(
            f"{label} must be an integer greater than or equal to {minimum}"
        )
    return value


def _boolean(data: dict[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"Field {key!r} must be a boolean")
    return value


def _optional_hash(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise TypeError(f"Field {key!r} must be a lowercase SHA-256 digest")
    return value
