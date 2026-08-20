import pytest

from evaluation.metrics import (
    evidence_group_recall_at_k,
    hit_rate_at_k,
    ndcg_at_k,
)


def test_retrieval_metrics_reward_relevant_results_near_the_top() -> None:
    relevant = {"a": 3, "b": 1}

    assert ndcg_at_k(["a", "x", "b"], relevant) > ndcg_at_k(["x", "b", "a"], relevant)
    assert hit_rate_at_k(["x", "a"], relevant, k=1) == 0.0
    assert hit_rate_at_k(["x", "a"], relevant, k=2) == 1.0


def test_evidence_group_recall_accepts_alternative_passages() -> None:
    groups = {"revenue": {"a", "b"}, "risk": {"c"}}

    assert evidence_group_recall_at_k(["b", "x", "c"], groups) == 1.0
    assert evidence_group_recall_at_k(["a"], groups) == 0.5


@pytest.mark.parametrize("metric", [ndcg_at_k, hit_rate_at_k])
def test_metrics_reject_non_positive_cutoffs(metric) -> None:
    with pytest.raises(ValueError, match="positive"):
        metric([], {}, k=0)
