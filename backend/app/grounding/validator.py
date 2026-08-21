"""Validate model citations against evidence retrieved in the current turn."""

from __future__ import annotations

import re
from collections.abc import Mapping
from collections.abc import Set as AbstractSet

from app.assistant.outputs import Citation, DraftGroundedAnswer, GroundedAnswer
from app.assistant.policy import (
    INSUFFICIENT_EVIDENCE_STATEMENT,
    INVESTMENT_ADVICE_STATEMENT,
)
from app.retrieval.models import SourcePassage

SOURCE_MARKER_RE = re.compile(r"\[(S[1-9][0-9]*)\]")
SOURCE_LIKE_MARKER_RE = re.compile(r"\[S[^\]]*\]")
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
    """The model exhausted its chance to produce a grounded answer."""


class GroundingValidator:
    """Resolve only current-turn, explicitly read evidence into citations."""

    def validate(
        self,
        draft: DraftGroundedAnswer,
        *,
        evidence: Mapping[str, SourcePassage],
        read_source_ids: AbstractSet[str],
        search_calls: int,
    ) -> GroundedAnswer:
        self._validate_advice_language(draft.answer)
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
        for index, source_id in enumerate(ordered_marker_ids):
            passage = evidence.get(source_id)
            if passage is None:
                raise GroundingValidationError(
                    f"Citation {source_id} was not retrieved during this turn"
                )
            if source_id not in read_source_ids:
                raise GroundingValidationError(
                    f"Citation {source_id} must be read before it can be cited"
                )
            excerpt = references[source_id].excerpt
            if _normalized_text(excerpt) not in _normalized_text(passage.text):
                raise GroundingValidationError(
                    f"Citation {source_id} excerpt is not present in its passage"
                )
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
                )
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
