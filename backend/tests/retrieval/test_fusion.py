from uuid import UUID

import pytest

from app.retrieval.fusion import reciprocal_rank_fusion

IDS = tuple(UUID(int=value) for value in range(1, 6))


def test_rrf_fuses_ranks_instead_of_raw_scores() -> None:
    results = reciprocal_rank_fusion(
        {
            "semantic": [IDS[0], IDS[1], IDS[2]],
            "lexical": [IDS[1], IDS[0], IDS[3]],
        }
    )

    assert [result.chunk_id for result in results] == [
        IDS[0],
        IDS[1],
        IDS[2],
        IDS[3],
    ]
    assert results[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert results[0].ranks == {"semantic": 1, "lexical": 2}


def test_rrf_deduplicates_each_branch_and_applies_weights() -> None:
    results = reciprocal_rank_fusion(
        {
            "semantic": [IDS[0], IDS[0], IDS[1]],
            "lexical": [IDS[1]],
        },
        k=10,
        weights={"semantic": 2.0, "lexical": 0.5},
    )

    by_id = {result.chunk_id: result for result in results}
    assert by_id[IDS[0]].score == pytest.approx(2 / 11)
    assert by_id[IDS[1]].score == pytest.approx(2 / 12 + 0.5 / 11)
    assert by_id[IDS[1]].ranks["semantic"] == 2


def test_rrf_ties_are_deterministic_and_empty_rankings_are_allowed() -> None:
    results = reciprocal_rank_fusion(
        {"semantic": [IDS[1]], "lexical": [IDS[0]], "empty": []}
    )

    assert [result.chunk_id for result in results] == [IDS[0], IDS[1]]


@pytest.mark.parametrize(
    ("k", "weights", "message"),
    [
        (0, None, "constant"),
        (60, {"unknown": 1.0}, "unknown rankings"),
        (60, {"semantic": -1.0}, "cannot be negative"),
    ],
)
def test_rrf_rejects_invalid_configuration(
    k: int,
    weights: dict[str, float] | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        reciprocal_rank_fusion({"semantic": []}, k=k, weights=weights)
