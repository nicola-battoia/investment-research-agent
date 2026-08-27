"""Run the frozen retrieval evaluation set without calling the answer model."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from uuid import UUID

from openai import AsyncOpenAI

from app.config import settings
from app.database.supabase import create_admin_supabase_client
from app.retrieval.keywords import OpenAIKeywordExtractor
from app.retrieval.models import SourcePassage
from app.retrieval.queries import RpcClient, hydrate_passages
from app.retrieval.retriever import DocumentRetriever
from evaluation.metrics import (
    evidence_group_recall_at_k,
    hit_rate_at_k,
    ndcg_at_k,
)
from evaluation.models import RetrievalEvalCase, RetrievalEvalDataset

DEFAULT_DATASET = Path(__file__).with_name("retrieval_cases.json")
METHODS = ("semantic", "lexical", "hybrid")
METRIC_CUTOFF = 10


def load_dataset(path: Path) -> RetrievalEvalDataset:
    return RetrievalEvalDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _passage_key(passage: SourcePassage) -> str:
    return f"{passage.accession_number}:{passage.chunk_index}"


async def _stable_keys(
    client: RpcClient,
    chunk_ids: tuple[UUID, ...],
) -> list[str]:
    passages = await hydrate_passages(client, chunk_ids[:METRIC_CUTOFF])
    return [_passage_key(passage) for passage in passages]


async def evaluate_case(
    case: RetrievalEvalCase,
    retriever: DocumentRetriever,
    client: RpcClient,
    *,
    candidate_limit: int,
) -> dict[str, object]:
    started = time.perf_counter()
    rankings = await retriever.candidate_rankings(
        case.query,
        case.filters,
        candidate_limit=candidate_limit,
    )
    stable_rankings = dict(
        zip(
            METHODS,
            await asyncio.gather(
                _stable_keys(client, rankings.semantic),
                _stable_keys(client, rankings.lexical),
                _stable_keys(client, rankings.hybrid),
            ),
            strict=True,
        )
    )
    relevant = {passage.key: passage.relevance for passage in case.expected_passages}
    groups: dict[str, set[str]] = {}
    for passage in case.expected_passages:
        groups.setdefault(passage.evidence_group, set()).add(passage.key)

    metrics = {
        method: {
            "ndcg_at_10": ndcg_at_k(stable_rankings[method], relevant),
            "hit_rate_at_10": hit_rate_at_k(stable_rankings[method], relevant),
            "evidence_group_recall_at_10": evidence_group_recall_at_k(
                stable_rankings[method], groups
            ),
        }
        for method in METHODS
    }
    return {
        "id": case.id,
        "query": case.query,
        "keywords": rankings.keywords.model_dump(mode="json"),
        "lexical_query": rankings.keywords.search_text,
        "filters": case.filters.model_dump(mode="json"),
        "expected_passages": [
            passage.model_dump(mode="json") for passage in case.expected_passages
        ],
        "rankings": stable_rankings,
        "metrics": metrics,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def run_evaluation(
    dataset: RetrievalEvalDataset,
    *,
    candidate_limit: int,
    semantic_weight: float,
    lexical_weight: float,
    rrf_k: int,
) -> dict[str, object]:
    supabase = await create_admin_supabase_client(settings)
    embedding_client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        max_retries=settings.openai_http_max_retries,
    )
    keyword_extractor = OpenAIKeywordExtractor(
        embedding_client,
        model=settings.openai_keyword_model,
    )
    retriever = DocumentRetriever(
        supabase,
        embedding_client,
        keyword_extractor,
        embedding_model=settings.openai_embedding_model,
        embedding_dimensions=settings.openai_embedding_dimensions,
        semantic_weight=semantic_weight,
        lexical_weight=lexical_weight,
        rrf_k=rrf_k,
    )
    cases = []
    for case in dataset.cases:
        cases.append(
            await evaluate_case(
                case,
                retriever,
                supabase,
                candidate_limit=candidate_limit,
            )
        )

    aggregate = {
        method: {
            metric: fmean(float(case["metrics"][method][metric]) for case in cases)
            for metric in (
                "ndcg_at_10",
                "hit_rate_at_10",
                "evidence_group_recall_at_10",
            )
        }
        for method in METHODS
    }
    hybrid_ndcg = aggregate["hybrid"]["ndcg_at_10"]
    accepted = (
        aggregate["hybrid"]["hit_rate_at_10"] == 1.0
        and aggregate["lexical"]["hit_rate_at_10"] > 0.0
        and hybrid_ndcg >= aggregate["semantic"]["ndcg_at_10"]
        and hybrid_ndcg >= aggregate["lexical"]["ndcg_at_10"]
    )
    return {
        "dataset": dataset.name,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "configuration": {
            "embedding_model": settings.openai_embedding_model,
            "embedding_dimensions": settings.openai_embedding_dimensions,
            "keyword_model": settings.openai_keyword_model,
            "candidate_limit": candidate_limit,
            "result_limit": METRIC_CUTOFF,
            "rrf_k": rrf_k,
            "semantic_weight": semantic_weight,
            "lexical_weight": lexical_weight,
        },
        "cases": cases,
        "aggregate": aggregate,
        "accepted": accepted,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate semantic, lexical, and hybrid filing retrieval."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=settings.retrieval_default_candidate_limit,
    )
    parser.add_argument(
        "--semantic-weight",
        type=float,
        default=settings.retrieval_semantic_weight,
    )
    parser.add_argument(
        "--lexical-weight",
        type=float,
        default=settings.retrieval_lexical_weight,
    )
    parser.add_argument("--rrf-k", type=int, default=settings.retrieval_rrf_k)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_dataset(args.dataset)
    result = asyncio.run(
        run_evaluation(
            dataset,
            candidate_limit=args.candidate_limit,
            semantic_weight=args.semantic_weight,
            lexical_weight=args.lexical_weight,
            rrf_k=args.rrf_k,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Evaluated {len(dataset.cases)} cases; accepted={result['accepted']}; "
        f"results={args.output}"
    )
    if not result["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
