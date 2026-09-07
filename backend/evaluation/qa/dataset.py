"""Versioned golden cases and exact evidence validation."""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_DATASET = (
    Path(__file__).parents[1] / "benchmarks" / "filings_deep_research_v1.json"
)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accession_number: str
    chunk_index: int = Field(ge=0)
    chunk_id: str
    text_sha256: str
    excerpt: str = Field(min_length=20)
    section_title: str | None = None


class EvidenceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    alternatives: list[Evidence] = Field(min_length=1)


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    question: str
    gold_answer: str
    evidence_groups: list[EvidenceGroup] = Field(min_length=1)
    rubric: dict[str, Any]

    @model_validator(mode="after")
    def unique_groups(self) -> "GoldenCase":
        ids = [group.id for group in self.evidence_groups]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence group IDs must be unique")
        return self


class GoldenDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str
    corpus_fingerprint: str
    metadata: dict[str, Any]
    cases: list[GoldenCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> "GoldenDataset":
        ids = [case.code for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Case codes must be unique")
        return self


def load_dataset(path: Path = DEFAULT_DATASET) -> GoldenDataset:
    return GoldenDataset.model_validate_json(path.read_text())


def corpus_fingerprint(rows: list[dict]) -> str:
    # Database UUIDs are recorded separately; stable content can survive a restore.
    identity = sorted(
        (row["accession_number"], row["chunk_index"], digest(row["text"]))
        for row in rows
    )
    return digest(json.dumps(identity, separators=(",", ":")))


def validate_evidence(dataset: GoldenDataset, rows: list[dict]) -> None:
    if corpus_fingerprint(rows) != dataset.corpus_fingerprint:
        raise ValueError("Corpus fingerprint changed; remap and version the dataset")
    by_key = {(row["accession_number"], row["chunk_index"]): row for row in rows}
    for case in dataset.cases:
        for group in case.evidence_groups:
            for evidence in group.alternatives:
                row = by_key.get((evidence.accession_number, evidence.chunk_index))
                if row is None or str(row["chunk_id"]) != evidence.chunk_id:
                    raise ValueError(
                        f"{case.code}/{group.id}: missing or changed chunk"
                    )
                if (
                    digest(row["text"]) != evidence.text_sha256
                    or evidence.excerpt not in row["text"]
                ):
                    raise ValueError(f"{case.code}/{group.id}: evidence text changed")


def evidence_recall(case: GoldenCase, chunk_ids: set[str]) -> dict:
    matched = [
        group.id
        for group in case.evidence_groups
        if any(item.chunk_id in chunk_ids for item in group.alternatives)
    ]
    return {
        "matched_groups": matched,
        "required_groups": len(case.evidence_groups),
        "recall": len(matched) / len(case.evidence_groups),
    }


def minimum_calls(case: GoldenCase) -> dict:
    # A read can cover several chunks but only one filing. This is a lower bound.
    documents = {
        item.accession_number
        for group in case.evidence_groups
        for item in group.alternatives
    }
    # Alternatives spanning documents do not make every alternative mandatory.
    mandatory = {
        next(iter(accessions))
        for group in case.evidence_groups
        if len(accessions := {e.accession_number for e in group.alternatives}) == 1
    }
    return {
        "evidence_documents": len(documents),
        "minimum_read_calls": len(mandatory),
        "minimum_total_calls": len(mandatory) + 1,
    }
