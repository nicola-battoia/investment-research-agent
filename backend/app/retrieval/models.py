"""Public types returned by hybrid retrieval."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _normalized_values(values: tuple[str, ...], *, uppercase: bool) -> tuple[str, ...]:
    normalized = []
    seen = set()
    for value in values:
        item = value.strip()
        if not item:
            raise ValueError("Retrieval filter values cannot be empty")
        item = item.upper() if uppercase else item.casefold()
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return tuple(normalized)


class RetrievalFilters(BaseModel):
    """Explicit filing filters shared by semantic and lexical retrieval."""

    model_config = ConfigDict(frozen=True)

    companies: tuple[str, ...] = ()
    tickers: tuple[str, ...] = ()
    filing_types: tuple[str, ...] = ()
    filing_years: tuple[int, ...] = ()
    filed_on_or_after: date | None = None
    filed_on_or_before: date | None = None

    @field_validator("companies")
    @classmethod
    def normalize_companies(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_values(values, uppercase=False)

    @field_validator("tickers", "filing_types")
    @classmethod
    def normalize_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_values(values, uppercase=True)

    @field_validator("filing_years")
    @classmethod
    def validate_years(cls, years: tuple[int, ...]) -> tuple[int, ...]:
        if any(year < 1900 or year > 2100 for year in years):
            raise ValueError("Filing years must be between 1900 and 2100")
        return tuple(dict.fromkeys(years))

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if (
            self.filed_on_or_after is not None
            and self.filed_on_or_before is not None
            and self.filed_on_or_after > self.filed_on_or_before
        ):
            raise ValueError("Retrieval date range start must not be after its end")
        return self


class KeywordGroup(BaseModel):
    """Closely related filing terms for one evidence-bearing concept."""

    model_config = ConfigDict(frozen=True)

    terms: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        description="Explicit query term plus at most two close lexical forms.",
    )

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, terms: tuple[str, ...]) -> tuple[str, ...]:
        normalized = []
        seen = set()
        for value in terms:
            term = " ".join(value.split()).strip(".,;:!?\"'()[]{}")
            if not term:
                raise ValueError("Extracted keyword terms cannot be empty")
            if len(term) > 80:
                raise ValueError("Extracted keyword terms cannot exceed 80 characters")
            key = term.casefold()
            if key not in seen:
                normalized.append(term)
                seen.add(key)
        return tuple(normalized)


class ExtractedKeywords(BaseModel):
    """Bounded, auditable lexical concepts extracted from a user query."""

    model_config = ConfigDict(frozen=True)

    groups: tuple[KeywordGroup, ...] = Field(
        min_length=1,
        max_length=6,
        description="Distinct evidence-bearing concepts explicitly present in the query.",
    )

    @property
    def search_text(self) -> str:
        terms = []
        seen = set()
        for group in self.groups:
            for term in group.terms:
                key = term.casefold()
                if key not in seen:
                    terms.append(term)
                    seen.add(key)
        return " ".join(terms)


class SourcePassage(BaseModel):
    """One filing passage with citation and retrieval metadata."""

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    document_id: UUID
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    token_count: int = Field(gt=0)
    page_number: int | None = Field(default=None, gt=0)
    section_title: str | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, gt=0)
    metadata: dict[str, object] = Field(default_factory=dict)
    company: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    filing_type: str = Field(min_length=1)
    filing_date: date
    report_date: date
    accession_number: str = Field(min_length=1)
    sec_url: str = Field(min_length=1)
    semantic_rank: int | None = Field(default=None, gt=0)
    lexical_rank: int | None = Field(default=None, gt=0)
    fused_score: float | None = Field(default=None, ge=0)
    passage_kind: Literal["ranked", "neighbor"] = "ranked"

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("Source offsets must both be present or both be absent")
        if (
            self.source_start is not None
            and self.source_end is not None
            and self.source_end <= self.source_start
        ):
            raise ValueError("Source end must be after source start")
        return self


class RetrievalResult(BaseModel):
    """Ranked evidence plus structurally useful neighboring context."""

    model_config = ConfigDict(frozen=True)

    passages: tuple[SourcePassage, ...]
    context_passages: tuple[SourcePassage, ...] = ()
    keywords: ExtractedKeywords
