"""Frozen retrieval evaluation dataset models."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.retrieval.models import RetrievalFilters


class ExpectedPassage(BaseModel):
    model_config = ConfigDict(frozen=True)

    accession_number: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    relevance: int = Field(default=1, ge=1, le=3)
    evidence_group: str = Field(default="answer", min_length=1)

    @property
    def key(self) -> str:
        return f"{self.accession_number}:{self.chunk_index}"


class RetrievalEvalCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    expected_passages: tuple[ExpectedPassage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_expected_keys(self) -> Self:
        keys = [passage.key for passage in self.expected_passages]
        if len(keys) != len(set(keys)):
            raise ValueError("Expected passage keys must be unique within a case")
        return self


class RetrievalEvalDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    cases: tuple[RetrievalEvalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Retrieval evaluation case IDs must be unique")
        return self
