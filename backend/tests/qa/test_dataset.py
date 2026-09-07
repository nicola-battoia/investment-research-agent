import re
from pathlib import Path

import pytest

from evaluation.qa.dataset import (
    GoldenDataset,
    corpus_fingerprint,
    digest,
    evidence_recall,
    load_dataset,
    minimum_calls,
    validate_evidence,
)


def fixture_dataset():
    rows = [
        {
            "accession_number": "filing-a",
            "chunk_index": 0,
            "chunk_id": "chunk-a",
            "text": "An exact paragraph containing the required evidence.",
        },
        {
            "accession_number": "filing-a",
            "chunk_index": 1,
            "chunk_id": "chunk-b",
            "text": "An alternative paragraph containing equivalent evidence.",
        },
    ]
    evidence = [
        {
            "accession_number": r["accession_number"],
            "chunk_index": r["chunk_index"],
            "chunk_id": r["chunk_id"],
            "text_sha256": digest(r["text"]),
            "excerpt": r["text"],
        }
        for r in rows
    ]
    dataset = GoldenDataset.model_validate(
        {
            "name": "test",
            "version": "1",
            "corpus_fingerprint": corpus_fingerprint(rows),
            "metadata": {},
            "cases": [
                {
                    "code": "A",
                    "question": "Question",
                    "gold_answer": "Gold",
                    "rubric": {},
                    "evidence_groups": [
                        {
                            "id": "revenue",
                            "description": "Revenue disclosure",
                            "alternatives": evidence,
                        }
                    ],
                }
            ],
        }
    )
    return dataset, rows


def test_equivalent_evidence_counts_once_and_irrelevant_chunks_do_not_help():
    dataset, _ = fixture_dataset()
    case = dataset.cases[0]
    assert evidence_recall(case, {"chunk-a"})["recall"] == 1
    assert evidence_recall(case, {"chunk-a", "chunk-b"})["recall"] == 1
    assert evidence_recall(case, {"unrelated"})["recall"] == 0


def test_changed_corpus_and_reused_indexes_fail_before_live_calls():
    dataset, rows = fixture_dataset()
    validate_evidence(dataset, rows)
    rows[0]["text"] = "Different contents at the same index."
    with pytest.raises(ValueError, match="fingerprint"):
        validate_evidence(dataset, rows)


def test_restored_uuid_requires_explicit_remapping_even_with_identical_text():
    dataset, rows = fixture_dataset()
    rows[0]["chunk_id"] = "restored-id"
    with pytest.raises(ValueError, match="changed chunk"):
        validate_evidence(dataset, rows)


def test_wrong_excerpt_fails_even_when_chunk_checksum_matches():
    dataset, rows = fixture_dataset()
    dataset.cases[0].evidence_groups[0].alternatives[
        0
    ].excerpt = "This quotation was never in the original source."
    with pytest.raises(ValueError, match="evidence text"):
        validate_evidence(dataset, rows)


def test_read_lower_bound_does_not_count_multiple_chunks_of_same_filing():
    dataset, _ = fixture_dataset()
    assert minimum_calls(dataset.cases[0])["minimum_total_calls"] == 2


def test_markdown_questions_and_gold_answers_match_executable_dataset():
    md = (
        Path(__file__).parents[2] / "evaluation/benchmarks/filings_deep_research_v1.md"
    ).read_text()
    normalize = lambda text: re.sub(r"\s+", " ", text).strip()
    for case in load_dataset().cases:
        section = md.split(f"## {case.code} -", 1)[1].split("\n## ", 1)[0]
        question = section.split("**Question**", 1)[1].split("\n\n**", 1)[0]
        answer = section.split("**Gold answer**", 1)[1].split("**Required evidence", 1)[
            0
        ]
        assert normalize(question) == normalize(case.question), case.code
        assert normalize(answer) == normalize(case.gold_answer), case.code


def test_atomic_labels_reject_restored_uuid():
    from evaluation.models import RetrievalEvalDataset
    from evaluation.run_retrieval import validate_labels

    _, rows = fixture_dataset()
    atomic = RetrievalEvalDataset.model_validate(
        {
            "name": "atomic-test",
            "corpus_fingerprint": corpus_fingerprint(rows),
            "cases": [
                {
                    "id": "case",
                    "query": "question",
                    "expected_passages": [
                        {
                            "accession_number": "filing-a",
                            "chunk_index": 0,
                            "chunk_id": "chunk-a",
                            "text_sha256": digest(rows[0]["text"]),
                        }
                    ],
                }
            ],
        }
    )
    validate_labels(atomic, rows)
    rows[0]["chunk_id"] = "different"
    with pytest.raises(ValueError, match="changed expected passage"):
        validate_labels(atomic, rows)
