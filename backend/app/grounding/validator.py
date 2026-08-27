"""Validate assistant response paths and current-turn filing citations."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from pydantic import ValidationError

from app.assistant.outputs import (
    Citation,
    CitationTableCell,
    CitationTableRow,
    CitationTextHighlight,
    DraftGroundedAnswer,
    GroundedAnswer,
    TableCitationPassage,
    TextCitationPassage,
)
from app.assistant.policy import (
    INSUFFICIENT_EVIDENCE_STATEMENT,
    INVESTMENT_ADVICE_STATEMENT,
)
from app.config import settings
from app.retrieval.display_tables import StoredDisplayTable
from app.retrieval.models import SourcePassage

SOURCE_MARKER_RE = re.compile(r"\[(S[1-9][0-9]*)\]")
SOURCE_LIKE_MARKER_RE = re.compile(r"\[S[^\]]*\]")
EXCERPT_OMISSION_RE = re.compile(r"(?:\.{3}|…)")
NON_RETRIEVAL_STATUSES = frozenset(("conversational", "out_of_scope"))
PROHIBITED_ADVICE_PATTERNS = (
    re.compile(r"\b(?:i|we)\s+(?:would\s+)?recommend\b", re.IGNORECASE),
    re.compile(
        r"\byou\s+should\s+(?:buy|sell|hold|short|invest)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:buy|sell|hold|short)\s+(?:the\s+)?(?:stock|shares|security)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bprice target\b", re.IGNORECASE),
    re.compile(r"\bportfolio allocation\b", re.IGNORECASE),
    re.compile(r"\bgood investment\b", re.IGNORECASE),
)


class GroundingValidationError(ValueError):
    """A draft answer violated the deterministic grounding contract."""


class GroundingFailureError(Exception):
    """The model exhausted its chance to produce a valid answer."""


class GroundingValidator:
    """Validate response paths and resolve current-turn evidence into citations."""

    def validate(
        self,
        draft: DraftGroundedAnswer,
        *,
        evidence: Mapping[str, SourcePassage],
        read_source_ids: AbstractSet[str],
        search_calls: int,
    ) -> GroundedAnswer:
        self._validate_advice_language(draft.answer)
        if draft.status in NON_RETRIEVAL_STATUSES:
            return self._validate_non_retrieval(draft, search_calls)
        if draft.status == "insufficient_evidence":
            return self._validate_insufficient_evidence(draft, search_calls)
        if draft.status == "supported":
            if search_calls == 0:
                raise GroundingValidationError(
                    "A supported answer requires at least one filing search"
                )
            if INVESTMENT_ADVICE_STATEMENT in draft.answer:
                raise GroundingValidationError(
                    "Use investment_advice_refused when the advice refusal is present"
                )
        elif INVESTMENT_ADVICE_STATEMENT not in draft.answer:
            raise GroundingValidationError(
                "Investment-advice responses must include the required refusal sentence"
            )

        citations = self._resolve_citations(
            draft,
            evidence=evidence,
            read_source_ids=read_source_ids,
        )
        if draft.status == "supported" and not citations:
            raise GroundingValidationError(
                "A supported answer requires at least one citation"
            )
        if (
            draft.status == "investment_advice_refused"
            and draft.answer != INVESTMENT_ADVICE_STATEMENT
            and not citations
        ):
            raise GroundingValidationError(
                "Factual context accompanying an investment-advice refusal requires "
                "at least one citation"
            )
        return GroundedAnswer(
            status=draft.status,
            answer=draft.answer,
            citations=citations,
        )

    def _validate_non_retrieval(
        self,
        draft: DraftGroundedAnswer,
        search_calls: int,
    ) -> GroundedAnswer:
        if search_calls:
            raise GroundingValidationError(
                f"A {draft.status} answer cannot follow a filing search"
            )
        if draft.citations or SOURCE_LIKE_MARKER_RE.search(draft.answer):
            raise GroundingValidationError(
                f"A {draft.status} answer cannot contain citations"
            )
        if len(draft.answer) > settings.assistant_max_non_retrieval_answer_characters:
            raise GroundingValidationError(
                f"A {draft.status} answer cannot exceed "
                f"{settings.assistant_max_non_retrieval_answer_characters} characters"
            )
        return GroundedAnswer(
            status=draft.status,
            answer=draft.answer,
            citations=(),
        )

    def _validate_insufficient_evidence(
        self,
        draft: DraftGroundedAnswer,
        search_calls: int,
    ) -> GroundedAnswer:
        if search_calls == 0:
            raise GroundingValidationError(
                "Insufficient evidence may be returned only after searching"
            )
        if draft.citations or SOURCE_LIKE_MARKER_RE.search(draft.answer):
            raise GroundingValidationError(
                "Insufficient-evidence answers cannot contain citations"
            )
        if draft.answer != INSUFFICIENT_EVIDENCE_STATEMENT:
            raise GroundingValidationError(
                "The insufficient-evidence answer must be exactly the required statement"
            )
        return GroundedAnswer(
            status=draft.status,
            answer=draft.answer,
            citations=(),
        )

    def _resolve_citations(
        self,
        draft: DraftGroundedAnswer,
        *,
        evidence: Mapping[str, SourcePassage],
        read_source_ids: AbstractSet[str],
    ) -> tuple[Citation, ...]:
        source_like_markers = SOURCE_LIKE_MARKER_RE.findall(draft.answer)
        marker_ids = SOURCE_MARKER_RE.findall(draft.answer)
        if len(source_like_markers) != len(marker_ids):
            raise GroundingValidationError(
                "Every source marker must use the exact [S<number>] format"
            )
        ordered_marker_ids = tuple(dict.fromkeys(marker_ids))
        references = {item.source_id: item for item in draft.citations}
        if len(references) != len(draft.citations):
            raise GroundingValidationError("Citation source IDs must be unique")
        if set(ordered_marker_ids) != set(references):
            raise GroundingValidationError(
                "Inline source markers and structured citations must match exactly"
            )

        resolved = []
        citation_errors = []
        for index, source_id in enumerate(ordered_marker_ids):
            passage = evidence.get(source_id)
            if passage is None:
                citation_errors.append(
                    f"Citation {source_id} was not retrieved during this turn"
                )
                continue
            if source_id not in read_source_ids:
                citation_errors.append(
                    f"Citation {source_id} must be read before it can be cited"
                )
                continue
            excerpt = references[source_id].excerpt
            excerpt_ranges = _excerpt_raw_ranges(excerpt, passage.text)
            if not excerpt_ranges:
                citation_errors.append(
                    f"Citation {source_id} excerpt fragments are not present in "
                    "order in its passage"
                )
                continue
            resolved.append(
                Citation(
                    source_id=source_id,
                    citation_index=index,
                    chunk_id=passage.chunk_id,
                    document_id=passage.document_id,
                    chunk_index=passage.chunk_index,
                    excerpt=excerpt,
                    company=passage.company,
                    ticker=passage.ticker,
                    filing_type=passage.filing_type,
                    filing_date=passage.filing_date,
                    report_date=passage.report_date,
                    accession_number=passage.accession_number,
                    sec_url=passage.sec_url,
                    page_number=passage.page_number,
                    section_title=passage.section_title,
                    source_start=passage.source_start,
                    source_end=passage.source_end,
                    passage=_citation_passage(passage, excerpt_ranges),
                )
            )
        if citation_errors:
            raise GroundingValidationError(
                "Citation validation failed: " + "; ".join(citation_errors)
            )
        return tuple(resolved)

    def _validate_advice_language(self, answer: str) -> None:
        answer_without_refusal = answer.replace(INVESTMENT_ADVICE_STATEMENT, "")
        for pattern in PROHIBITED_ADVICE_PATTERNS:
            if pattern.search(answer_without_refusal):
                raise GroundingValidationError(
                    "The answer contains prohibited investment-advice language"
                )


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class _NormalizedText:
    text: str
    raw_starts: tuple[int, ...]
    raw_ends: tuple[int, ...]


def _normalized_text_with_offsets(value: str) -> _NormalizedText:
    normalized = []
    raw_starts = []
    raw_ends = []
    previous_end = 0
    for token_index, match in enumerate(re.finditer(r"\S+", value)):
        if token_index:
            normalized.append(" ")
            raw_starts.append(previous_end)
            raw_ends.append(match.start())
        for raw_index, character in enumerate(match.group(), start=match.start()):
            folded = character.casefold()
            normalized.extend(folded)
            raw_starts.extend([raw_index] * len(folded))
            raw_ends.extend([raw_index + 1] * len(folded))
        previous_end = match.end()
    return _NormalizedText(
        text="".join(normalized),
        raw_starts=tuple(raw_starts),
        raw_ends=tuple(raw_ends),
    )


def _excerpt_raw_ranges(
    excerpt: str,
    passage_text: str,
) -> tuple[tuple[int, int], ...]:
    normalized_passage = _normalized_text_with_offsets(passage_text)
    fragments = tuple(
        normalized
        for part in EXCERPT_OMISSION_RE.split(excerpt)
        if (normalized := _normalized_text(part))
        and _without_boundary_punctuation(normalized)
    )
    if not fragments:
        return ()

    if len(fragments) == 1:
        exact_ranges = _all_raw_ranges(fragments[0], normalized_passage)
        if exact_ranges:
            return exact_ranges
        return _all_raw_ranges(
            _without_boundary_punctuation(fragments[0]),
            normalized_passage,
        )

    ranges = []
    search_start = 0
    for fragment in fragments:
        match = _next_fragment_match(fragment, normalized_passage.text, search_start)
        if match is None:
            return ()
        match_start, match_end = match
        ranges.append(_raw_range(normalized_passage, match_start, match_end))
        search_start = match_end
    return tuple(ranges)


def _all_raw_ranges(
    normalized_excerpt: str,
    normalized_passage: _NormalizedText,
) -> tuple[tuple[int, int], ...]:
    if not normalized_excerpt:
        return ()
    ranges = []
    search_start = 0
    while True:
        match_start = normalized_passage.text.find(normalized_excerpt, search_start)
        if match_start < 0:
            break
        match_end = match_start + len(normalized_excerpt)
        ranges.append(_raw_range(normalized_passage, match_start, match_end))
        search_start = match_start + 1
    return tuple(ranges)


def _next_fragment_match(
    fragment: str,
    passage_text: str,
    search_start: int,
) -> tuple[int, int] | None:
    relaxed_fragment = _without_boundary_punctuation(fragment)
    candidates = []
    for priority, value in enumerate(dict.fromkeys((fragment, relaxed_fragment))):
        match_start = passage_text.find(value, search_start)
        if match_start >= 0:
            candidates.append((match_start, priority, match_start + len(value)))
    if not candidates:
        return None
    match_start, _priority, match_end = min(candidates)
    return match_start, match_end


def _without_boundary_punctuation(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and _is_boundary_punctuation_or_space(value[start]):
        start += 1
    while end > start and _is_boundary_punctuation_or_space(value[end - 1]):
        end -= 1
    return value[start:end]


def _is_boundary_punctuation_or_space(character: str) -> bool:
    return character.isspace() or unicodedata.category(character).startswith("P")


def _raw_range(
    normalized_passage: _NormalizedText,
    match_start: int,
    match_end: int,
) -> tuple[int, int]:
    return (
        normalized_passage.raw_starts[match_start],
        normalized_passage.raw_ends[match_end - 1],
    )


def _citation_passage(
    passage: SourcePassage,
    ranges: tuple[tuple[int, int], ...],
) -> TextCitationPassage | TableCitationPassage:
    table_passage = _table_citation_passage(passage.display_table, ranges)
    if table_passage is not None:
        return table_passage
    return TextCitationPassage(
        text=passage.text,
        highlights=tuple(
            CitationTextHighlight(start=start, end=end) for start, end in ranges
        ),
    )


def _table_citation_passage(
    raw_table: dict[str, object] | None,
    excerpt_ranges: tuple[tuple[int, int], ...],
) -> TableCitationPassage | None:
    if raw_table is None:
        return None
    try:
        table = StoredDisplayTable.model_validate(raw_table)
    except ValidationError:
        return None

    highlighted_any = False
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            highlighted = (
                cell.text_start is not None
                and cell.text_end is not None
                and any(
                    start < cell.text_end and end > cell.text_start
                    for start, end in excerpt_ranges
                )
            )
            highlighted_any = highlighted_any or highlighted
            cells.append(
                CitationTableCell(
                    text=cell.text,
                    column_index=cell.column_index,
                    row_span=cell.row_span,
                    column_span=cell.column_span,
                    column_header=cell.column_header,
                    row_header=cell.row_header,
                    highlighted=highlighted,
                )
            )
        rows.append(CitationTableRow(cells=tuple(cells)))
    if not highlighted_any:
        return None
    return TableCitationPassage(
        column_count=table.column_count,
        rows=tuple(rows),
    )
