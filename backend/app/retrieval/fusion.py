"""Reciprocal Rank Fusion for incomparable retrieval score scales."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.config import settings


@dataclass(frozen=True)
class FusedRank:
    chunk_id: UUID
    score: float
    ranks: dict[str, int]


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[UUID]],
    *,
    k: int = settings.retrieval_rrf_k,
    weights: Mapping[str, float] | None = None,
) -> list[FusedRank]:
    """Fuse named rankings, counting each ID at most once per branch."""
    if k <= 0:
        raise ValueError("RRF smoothing constant must be positive")

    branch_weights = weights or {}
    unknown_weights = branch_weights.keys() - rankings.keys()
    if unknown_weights:
        raise ValueError(
            f"RRF weights name unknown rankings: {sorted(unknown_weights)}"
        )
    if any(weight < 0 for weight in branch_weights.values()):
        raise ValueError("RRF weights cannot be negative")

    scores: dict[UUID, float] = defaultdict(float)
    component_ranks: dict[UUID, dict[str, int]] = defaultdict(dict)
    for branch, ranking in rankings.items():
        weight = branch_weights.get(
            branch,
            settings.retrieval_unconfigured_branch_weight,
        )
        seen: set[UUID] = set()
        rank = 0
        for chunk_id in ranking:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            rank += 1
            scores[chunk_id] += weight / (k + rank)
            component_ranks[chunk_id][branch] = rank

    return sorted(
        (
            FusedRank(
                chunk_id=chunk_id,
                score=score,
                ranks=component_ranks[chunk_id],
            )
            for chunk_id, score in scores.items()
        ),
        key=lambda result: (
            -result.score,
            min(result.ranks.values()),
            str(result.chunk_id),
        ),
    )
