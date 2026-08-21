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


def passage(value: int, text: str) -> SourcePassage:
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
