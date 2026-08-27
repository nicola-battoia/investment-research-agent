from datetime import date
from uuid import UUID

import pytest

from app.assistant.outputs import CitationReference, DraftGroundedAnswer
from app.assistant.policy import (
    INSUFFICIENT_EVIDENCE_STATEMENT,
    INVESTMENT_ADVICE_STATEMENT,
)
from app.grounding.validator import GroundingValidationError, GroundingValidator
from app.retrieval.models import SourcePassage

FIRST_TEXT = (
    "Services net sales increased because of higher advertising and cloud services "
    "revenue during the fiscal year."
)
SECOND_TEXT = (
    "The company reported that foreign exchange had an unfavorable effect on total "
    "net sales during the period."
)


def passage(
    value: int,
    text: str,
    *,
    display_table: dict[str, object] | None = None,
) -> SourcePassage:
    return SourcePassage(
        chunk_id=UUID(int=value),
        document_id=UUID(int=100),
        chunk_index=value,
        text=text,
        token_count=30,
        page_number=12,
        section_title="Results of Operations",
        source_start=value * 100,
        source_end=value * 100 + len(text),
        metadata={},
        display_table=display_table,
        company="Apple Inc.",
        ticker="AAPL",
        filing_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        accession_number="0000320193-24-000123",
        sec_url="https://www.sec.gov/example",
    )


@pytest.fixture
def evidence() -> dict[str, SourcePassage]:
    return {
        "S1": passage(1, FIRST_TEXT),
        "S2": passage(2, SECOND_TEXT),
    }


def test_resolves_valid_citations_in_first_marker_order(
    evidence: dict[str, SourcePassage],
) -> None:
    draft = DraftGroundedAnswer(
        status="supported",
        answer=(
            "Foreign exchange reduced sales [S2]. Services increased from cloud and "
            "advertising revenue [S1]. Foreign exchange remained a headwind [S2]."
        ),
        citations=(
            CitationReference(
                source_id="S1",
                excerpt=(
                    "Services net sales increased because of higher advertising and "
                    "cloud services revenue"
                ),
            ),
            CitationReference(
                source_id="S2",
                excerpt="foreign exchange had an unfavorable effect on total net sales",
            ),
        ),
    )

    answer = GroundingValidator().validate(
        draft,
        evidence=evidence,
        read_source_ids={"S1", "S2"},
        search_calls=1,
    )

    assert answer.status == "supported"
    assert [citation.source_id for citation in answer.citations] == ["S2", "S1"]
    assert [citation.citation_index for citation in answer.citations] == [0, 1]
    assert answer.citations[0].chunk_id == evidence["S2"].chunk_id
    resolved_passage = answer.citations[0].passage
    assert resolved_passage is not None
    assert resolved_passage.kind == "text"
    assert resolved_passage.text == SECOND_TEXT
    assert (
        SECOND_TEXT[
            resolved_passage.highlights[0].start : resolved_passage.highlights[0].end
        ]
        == "foreign exchange had an unfavorable effect on total net sales"
    )


def test_text_passage_highlights_every_normalized_occurrence() -> None:
    phrase = "Recurring revenue increased strongly."
    full_text = f"{phrase}\n\n{phrase}"

    answer = _validated_citation(
        passage(1, full_text),
        phrase.lower(),
    )

    resolved = answer.citations[0].passage
    assert resolved is not None
    assert resolved.kind == "text"
    assert len(resolved.highlights) == 2
    assert [
        full_text[highlight.start : highlight.end] for highlight in resolved.highlights
    ] == [phrase, phrase]


def test_accepts_changed_punctuation_at_excerpt_boundaries() -> None:
    full_text = (
        "As of June 30, 2024, we employed approximately 228,000 people on a "
        "full-time basis, 126,000 in the U.S. and 102,000 internationally."
    )
    excerpt = (
        "“As of June 30, 2024, we employed approximately 228,000 people on a "
        "full-time basis.”"
    )

    answer = _validated_citation(passage(1, full_text), excerpt)

    resolved = answer.citations[0].passage
    assert resolved is not None
    assert resolved.kind == "text"
    assert len(resolved.highlights) == 1
    highlight = resolved.highlights[0]
    assert (
        full_text[highlight.start : highlight.end]
        == "As of June 30, 2024, we employed approximately 228,000 people on a "
        "full-time basis"
    )


@pytest.mark.parametrize("ellipsis", ["...", "…"])
def test_accepts_ordered_omitted_fragments_at_all_excerpt_positions(
    ellipsis: str,
) -> None:
    excerpt = (
        f"{ellipsis} Services net sales {ellipsis} cloud services revenue {ellipsis}"
    )

    answer = _validated_citation(passage(1, FIRST_TEXT), excerpt)

    resolved = answer.citations[0].passage
    assert resolved is not None
    assert resolved.kind == "text"
    assert [
        FIRST_TEXT[highlight.start : highlight.end]
        for highlight in resolved.highlights
    ] == ["Services net sales", "cloud services revenue"]


def test_rejects_omitted_fragments_that_are_not_in_source_order() -> None:
    excerpt = "cloud services revenue ... Services net sales"

    with pytest.raises(GroundingValidationError, match="not present in order"):
        _validated_citation(passage(1, FIRST_TEXT), excerpt)


@pytest.mark.parametrize(
    "excerpt",
    [
        "Services net sales increased, because of higher advertising",
        "........................",
    ],
)
def test_relaxed_matching_still_requires_substantive_exact_fragments(
    excerpt: str,
) -> None:
    with pytest.raises(GroundingValidationError, match="not present in order"):
        _validated_citation(passage(1, FIRST_TEXT), excerpt)


def test_accepts_relaxed_excerpts_from_logged_failure() -> None:
    apple_text = (
        "2025 | 2024 | 2023\nNet sales:\n"
        "U.S. | $ | 151,790 | $ | 142,196 | $ | 138,573\n"
        "China (1) | 64,377 | 66,952 | 72,559\n"
        "Other countries | 199,994 | 181,887 | 172,153\n"
        "Total net sales | $ | 416,161 | $ | 391,035 | $ | 383,285"
    )
    microsoft_text = (
        "As of June 30, 2024, we employed approximately 228,000 people on a "
        "full-time basis, 126,000 in the U.S. and 102,000 internationally."
    )
    draft = DraftGroundedAnswer(
        status="supported",
        answer="Apple revenue [S1]. Microsoft headcount [S2].",
        citations=(
            CitationReference(
                source_id="S1",
                excerpt=(
                    "2025 | 2024 | 2023 Net sales: ... Total net sales | $ | "
                    "416,161 | $ | 391,035 | $ | 383,285"
                ),
            ),
            CitationReference(
                source_id="S2",
                excerpt=(
                    "As of June 30, 2024, we employed approximately 228,000 people "
                    "on a full-time basis."
                ),
            ),
        ),
    )

    answer = GroundingValidator().validate(
        draft,
        evidence={"S1": passage(1, apple_text), "S2": passage(2, microsoft_text)},
        read_source_ids={"S1", "S2"},
        search_calls=1,
    )

    assert [citation.source_id for citation in answer.citations] == ["S1", "S2"]
    assert len(answer.citations[0].passage.highlights) == 2
    assert len(answer.citations[1].passage.highlights) == 1


@pytest.mark.parametrize(
    ("excerpt", "highlighted_rows"),
    [
        ("Revenue | $100 million | $80 million", {1}),
        (
            "Metric | 2024 | 2023 Revenue | $100 million | $80 million",
            {0, 1},
        ),
        (
            "Revenue | $100 million | $80 million Margin | 45 percent | 40 percent",
            {1, 2},
        ),
        (
            "... Metric | 2024 | 2023 ... Margin | 45 percent | 40 percent ...",
            {0, 2},
        ),
    ],
)
def test_table_passage_highlights_excerpt_cells(
    excerpt: str,
    highlighted_rows: set[int],
) -> None:
    table_text, display_table = _table_fixture()

    answer = _validated_citation(
        passage(1, table_text, display_table=display_table),
        excerpt,
    )

    resolved = answer.citations[0].passage
    assert resolved is not None
    assert resolved.kind == "table"
    assert resolved.column_count == 3
    assert len(resolved.rows) == 3
    actual_rows = {
        row_index
        for row_index, row in enumerate(resolved.rows)
        if any(cell.highlighted for cell in row.cells)
    }
    assert actual_rows == highlighted_rows


@pytest.mark.parametrize(
    "display_table",
    [
        {"version": 2},
        {
            "version": 1,
            "table_ref": "#/tables/0",
            "column_count": 1,
            "rows": [
                {
                    "cells": [
                        {
                            "text": "Recurring revenue increased strongly.",
                            "column_index": 0,
                            "row_span": 1,
                            "column_span": 1,
                            "column_header": False,
                            "row_header": False,
                            "text_start": None,
                            "text_end": None,
                        }
                    ]
                }
            ],
        },
    ],
)
def test_table_metadata_safely_falls_back_to_text(
    display_table: dict[str, object],
) -> None:
    text = "Recurring revenue increased strongly."

    answer = _validated_citation(
        passage(1, text, display_table=display_table),
        text,
    )

    resolved = answer.citations[0].passage
    assert resolved is not None
    assert resolved.kind == "text"


@pytest.mark.parametrize(
    ("draft", "error"),
    [
        (
            DraftGroundedAnswer(
                status="supported",
                answer="A claim has no marker.",
                citations=(),
            ),
            "requires at least one citation",
        ),
        (
            DraftGroundedAnswer(
                status="supported",
                answer="A claim [S9].",
                citations=(CitationReference(source_id="S9", excerpt="x" * 20),),
            ),
            "was not retrieved",
        ),
        (
            DraftGroundedAnswer(
                status="supported",
                answer="A claim [S1].",
                citations=(),
            ),
            "must match exactly",
        ),
        (
            DraftGroundedAnswer(
                status="supported",
                answer="A claim [S1].",
                citations=(
                    CitationReference(
                        source_id="S1", excerpt="not in the filing passage"
                    ),
                ),
            ),
            "not present",
        ),
        (
            DraftGroundedAnswer(
                status="supported",
                answer="A claim [S1].",
                citations=(
                    CitationReference(
                        source_id="S1",
                        excerpt="Services net sales increased because of higher advertising",
                    ),
                ),
            ),
            "must be read",
        ),
    ],
)
def test_rejects_invalid_supported_answers(
    draft: DraftGroundedAnswer,
    error: str,
    evidence: dict[str, SourcePassage],
) -> None:
    read_ids = set() if "must be read" in error else {"S1", "S2"}
    with pytest.raises(GroundingValidationError, match=error):
        GroundingValidator().validate(
            draft,
            evidence=evidence,
            read_source_ids=read_ids,
            search_calls=1,
        )


def test_reports_all_invalid_citation_excerpts_together(
    evidence: dict[str, SourcePassage],
) -> None:
    draft = DraftGroundedAnswer(
        status="supported",
        answer="One unsupported claim [S1]. Another unsupported claim [S2].",
        citations=(
            CitationReference(source_id="S1", excerpt="first invented excerpt value"),
            CitationReference(source_id="S2", excerpt="second invented excerpt value"),
        ),
    )

    with pytest.raises(GroundingValidationError) as error:
        GroundingValidator().validate(
            draft,
            evidence=evidence,
            read_source_ids={"S1", "S2"},
            search_calls=1,
        )

    message = str(error.value)
    assert "Citation S1 excerpt fragments are not present in order" in message
    assert "Citation S2 excerpt fragments are not present in order" in message


def test_accepts_clear_uncited_insufficient_evidence_refusal() -> None:
    answer = GroundingValidator().validate(
        DraftGroundedAnswer(
            status="insufficient_evidence",
            answer=INSUFFICIENT_EVIDENCE_STATEMENT,
        ),
        evidence={},
        read_source_ids=set(),
        search_calls=3,
    )

    assert answer.status == "insufficient_evidence"
    assert answer.citations == ()


@pytest.mark.parametrize(
    ("status", "text"),
    [
        ("conversational", "Hello! I’m Document Copilot. How can I help?"),
        (
            "out_of_scope",
            "I focus on SEC-filing research. Ask me about a company filing instead.",
        ),
    ],
)
def test_accepts_short_non_retrieval_answers(status: str, text: str) -> None:
    answer = GroundingValidator().validate(
        DraftGroundedAnswer(status=status, answer=text),
        evidence={},
        read_source_ids=set(),
        search_calls=0,
    )

    assert answer.status == status
    assert answer.answer == text
    assert answer.citations == ()


@pytest.mark.parametrize("status", ["conversational", "out_of_scope"])
@pytest.mark.parametrize(
    ("search_calls", "answer", "citations", "error"),
    [
        (1, "A short reply.", (), "cannot follow a filing search"),
        (0, "A reply with a marker [S1].", (), "cannot contain citations"),
        (
            0,
            "A reply with a reference.",
            (CitationReference(source_id="S1", excerpt="x" * 20),),
            "cannot contain citations",
        ),
        (0, "x" * 1_001, (), "cannot exceed 1000 characters"),
        (0, "You should buy the stock.", (), "prohibited"),
    ],
)
def test_rejects_invalid_non_retrieval_answers(
    status: str,
    search_calls: int,
    answer: str,
    citations: tuple[CitationReference, ...],
    error: str,
) -> None:
    with pytest.raises(GroundingValidationError, match=error):
        GroundingValidator().validate(
            DraftGroundedAnswer(
                status=status,
                answer=answer,
                citations=citations,
            ),
            evidence={},
            read_source_ids=set(),
            search_calls=search_calls,
        )


@pytest.mark.parametrize(
    ("search_calls", "answer", "citations", "error"),
    [
        (0, INSUFFICIENT_EVIDENCE_STATEMENT, (), "only after searching"),
        (1, "I do not know.", (), "exactly the required statement"),
        (
            1,
            f"Apple reported growth. {INSUFFICIENT_EVIDENCE_STATEMENT}",
            (),
            "exactly the required statement",
        ),
        (
            1,
            f"{INSUFFICIENT_EVIDENCE_STATEMENT} [S1]",
            (),
            "cannot contain citations",
        ),
    ],
)
def test_rejects_invalid_insufficient_evidence_refusals(
    search_calls: int,
    answer: str,
    citations: tuple[CitationReference, ...],
    error: str,
) -> None:
    with pytest.raises(GroundingValidationError, match=error):
        GroundingValidator().validate(
            DraftGroundedAnswer(
                status="insufficient_evidence",
                answer=answer,
                citations=citations,
            ),
            evidence={},
            read_source_ids=set(),
            search_calls=search_calls,
        )


def test_accepts_cited_facts_followed_by_advice_refusal(
    evidence: dict[str, SourcePassage],
) -> None:
    answer = GroundingValidator().validate(
        DraftGroundedAnswer(
            status="investment_advice_refused",
            answer=(
                "Services increased from advertising and cloud services [S1]. "
                f"{INVESTMENT_ADVICE_STATEMENT}"
            ),
            citations=(
                CitationReference(
                    source_id="S1",
                    excerpt="higher advertising and cloud services revenue during the fiscal year",
                ),
            ),
        ),
        evidence=evidence,
        read_source_ids={"S1"},
        search_calls=1,
    )

    assert answer.status == "investment_advice_refused"
    assert len(answer.citations) == 1


def test_rejects_direct_investment_recommendation() -> None:
    with pytest.raises(GroundingValidationError, match="prohibited"):
        GroundingValidator().validate(
            DraftGroundedAnswer(
                status="investment_advice_refused",
                answer=f"You should buy the stock. {INVESTMENT_ADVICE_STATEMENT}",
            ),
            evidence={},
            read_source_ids=set(),
            search_calls=0,
        )


def test_rejects_uncited_context_attached_to_advice_refusal() -> None:
    with pytest.raises(
        GroundingValidationError, match="requires at least one citation"
    ):
        GroundingValidator().validate(
            DraftGroundedAnswer(
                status="investment_advice_refused",
                answer=f"Apple reported growth. {INVESTMENT_ADVICE_STATEMENT}",
            ),
            evidence={},
            read_source_ids=set(),
            search_calls=0,
        )


def _validated_citation(source: SourcePassage, excerpt: str):
    return GroundingValidator().validate(
        DraftGroundedAnswer(
            status="supported",
            answer="The filing supports this statement [S1].",
            citations=(CitationReference(source_id="S1", excerpt=excerpt),),
        ),
        evidence={"S1": source},
        read_source_ids={"S1"},
        search_calls=1,
    )


def _table_fixture() -> tuple[str, dict[str, object]]:
    values = [
        ["Metric", "2024", "2023"],
        ["Revenue", "$100 million", "$80 million"],
        ["Margin", "45 percent", "40 percent"],
    ]
    text = "[TABLE]\n" + "\n".join(" | ".join(row) for row in values)
    search_start = 0
    rows = []
    for row_index, row in enumerate(values):
        cells = []
        for column_index, value in enumerate(row):
            start = text.index(value, search_start)
            end = start + len(value)
            search_start = end
            cells.append(
                {
                    "text": value,
                    "column_index": column_index,
                    "row_span": 1,
                    "column_span": 1,
                    "column_header": row_index == 0,
                    "row_header": column_index == 0 and row_index > 0,
                    "text_start": start,
                    "text_end": end,
                }
            )
        rows.append({"cells": cells})
    return text, {
        "version": 1,
        "table_ref": "#/tables/0",
        "column_count": 3,
        "rows": rows,
    }
