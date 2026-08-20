"""Small, dependency-free information-retrieval metrics."""

import math
from collections.abc import Mapping, Sequence


def ndcg_at_k(
    predicted: Sequence[str],
    relevant: Mapping[str, int],
    *,
    k: int = 10,
) -> float:
    if k <= 0:
        raise ValueError("Metric cutoff must be positive")
    dcg = sum(
        relevant.get(key, 0) / math.log2(rank + 2)
        for rank, key in enumerate(predicted[:k])
    )
    ideal_relevance = sorted(relevant.values(), reverse=True)[:k]
    idcg = sum(
        relevance / math.log2(rank + 2)
        for rank, relevance in enumerate(ideal_relevance)
    )
    return dcg / idcg if idcg else 0.0


def hit_rate_at_k(
    predicted: Sequence[str],
    relevant: Mapping[str, int],
    *,
    k: int = 10,
) -> float:
    if k <= 0:
        raise ValueError("Metric cutoff must be positive")
    return float(any(key in relevant for key in predicted[:k]))


def evidence_group_recall_at_k(
    predicted: Sequence[str],
    groups: Mapping[str, set[str]],
    *,
    k: int = 10,
) -> float:
    if k <= 0:
        raise ValueError("Metric cutoff must be positive")
    if not groups:
        return 0.0
    retrieved = set(predicted[:k])
    matched_groups = sum(bool(expected & retrieved) for expected in groups.values())
    return matched_groups / len(groups)
