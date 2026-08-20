"""Interactive diagnostics for one live hybrid-retrieval query."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from openai import AsyncOpenAI

from app.database.supabase import create_admin_supabase_client
from app.retrieval.fusion import FusedRank
from app.retrieval.keywords import OpenAIKeywordExtractor
from app.retrieval.models import RetrievalFilters, SourcePassage
from app.retrieval.queries import RankedCandidate, RpcClient, hydrate_passages
from app.retrieval.retriever import (
    DEFAULT_CANDIDATE_LIMIT,
    DocumentRetriever,
    RetrievalCandidates,
)

logger = logging.getLogger("retrieval-inspector")


@dataclass(frozen=True)
class InspectionResult:
    """Candidates and hydrated chunks from each retrieval ranking."""

    candidates: RetrievalCandidates
    semantic_passages: tuple[SourcePassage, ...]
    lexical_passages: tuple[SourcePassage, ...]
    hybrid_passages: tuple[SourcePassage, ...]


def configure_logging() -> None:
    """Show readable retrieval diagnostics in an interactive window."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(logging.INFO)


async def build_live_retriever() -> tuple[DocumentRetriever, RpcClient]:
    """Construct the same live retriever used by the application."""
    from app.config import settings

    supabase = await create_admin_supabase_client(settings)
    openai_client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        max_retries=3,
    )
    retriever = DocumentRetriever(
        supabase,
        openai_client,
        OpenAIKeywordExtractor(
            openai_client,
            model=settings.openai_keyword_model,
        ),
        embedding_model=settings.openai_embedding_model,
        embedding_dimensions=settings.openai_embedding_dimensions,
    )
    logger.info(
        "Models: embedding=%s (%d dimensions), keywords=%s",
        settings.openai_embedding_model,
        settings.openai_embedding_dimensions,
        settings.openai_keyword_model,
    )
    return retriever, supabase


async def inspect_retrieval(
    query: str,
    filters: RetrievalFilters | None = None,
    *,
    show: int = 5,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    snippet_chars: int = 320,
    retriever: DocumentRetriever | None = None,
    client: RpcClient | None = None,
) -> InspectionResult:
    """Run and log keyword, semantic, lexical, fusion, and chunk results."""
    if show <= 0 or show > candidate_limit:
        raise ValueError("Show count must be between 1 and the candidate limit")
    if snippet_chars < 80:
        raise ValueError("Snippet length must be at least 80 characters")
    if (retriever is None) != (client is None):
        raise ValueError("Pass both retriever and client, or neither")

    configure_logging()
    active_filters = filters or RetrievalFilters()
    logger.info("\nQUERY\n%s", query.strip())
    logger.info(
        "\nFILTERS\n%s",
        json.dumps(active_filters.model_dump(mode="json"), sort_keys=True),
    )

    if retriever is None or client is None:
        retriever, client = await build_live_retriever()

    candidates = await retriever.candidate_details(
        query,
        active_filters,
        candidate_limit=candidate_limit,
    )
    logger.info("\nKEYWORDS")
    for index, group in enumerate(candidates.keywords.groups, start=1):
        logger.info("%d. %s", index, " | ".join(group.terms))
    logger.info("FTS query: %s", candidates.keywords.search_text)
    logger.info(
        "\nTIMINGS\nsemantic=%.1fms  lexical=%.1fms  fusion=%.2fms  total=%.1fms",
        candidates.timings.semantic_pipeline_ms,
        candidates.timings.lexical_pipeline_ms,
        candidates.timings.fusion_ms,
        candidates.timings.total_ms,
    )
    logger.info(
        "Candidates: semantic=%d  lexical=%d  hybrid=%d",
        len(candidates.semantic),
        len(candidates.lexical),
        len(candidates.hybrid),
    )

    requested_ids = _unique_ids(
        [candidate.chunk_id for candidate in candidates.semantic[:show]],
        [candidate.chunk_id for candidate in candidates.lexical[:show]],
        [candidate.chunk_id for candidate in candidates.hybrid[:show]],
    )
    hydrated = await hydrate_passages(client, requested_ids)
    by_id = {passage.chunk_id: passage for passage in hydrated}

    semantic_passages = tuple(
        by_id[candidate.chunk_id].model_copy(update={"semantic_rank": rank})
        for rank, candidate in enumerate(candidates.semantic[:show], start=1)
    )
    lexical_passages = tuple(
        by_id[candidate.chunk_id].model_copy(update={"lexical_rank": rank})
        for rank, candidate in enumerate(candidates.lexical[:show], start=1)
    )
    hybrid_passages = tuple(
        by_id[candidate.chunk_id].model_copy(
            update={
                "semantic_rank": candidate.ranks.get("semantic"),
                "lexical_rank": candidate.ranks.get("lexical"),
                "fused_score": candidate.score,
            }
        )
        for candidate in candidates.hybrid[:show]
    )

    _log_branch(
        "SEMANTIC", candidates.semantic[:show], semantic_passages, snippet_chars
    )
    _log_branch("LEXICAL", candidates.lexical[:show], lexical_passages, snippet_chars)
    _log_hybrid(candidates.hybrid[:show], hybrid_passages, snippet_chars)

    return InspectionResult(
        candidates=candidates,
        semantic_passages=semantic_passages,
        lexical_passages=lexical_passages,
        hybrid_passages=hybrid_passages,
    )


def _unique_ids(*rankings: list[UUID]) -> list[UUID]:
    ordered: list[UUID] = []
    seen: set[UUID] = set()
    for ranking in rankings:
        for chunk_id in ranking:
            if chunk_id not in seen:
                ordered.append(chunk_id)
                seen.add(chunk_id)
    return ordered


def _log_branch(
    name: str,
    candidates: tuple[RankedCandidate, ...],
    passages: tuple[SourcePassage, ...],
    snippet_chars: int,
) -> None:
    logger.info("\n%s RESULTS", name)
    for rank, (candidate, passage) in enumerate(
        zip(candidates, passages, strict=True),
        start=1,
    ):
        _log_passage(rank, candidate.score, passage, snippet_chars)


def _log_hybrid(
    candidates: tuple[FusedRank, ...],
    passages: tuple[SourcePassage, ...],
    snippet_chars: int,
) -> None:
    logger.info("\nHYBRID RESULTS")
    for rank, (candidate, passage) in enumerate(
        zip(candidates, passages, strict=True),
        start=1,
    ):
        component_ranks = ", ".join(
            f"{branch}={component_rank}"
            for branch, component_rank in sorted(candidate.ranks.items())
        )
        _log_passage(
            rank,
            candidate.score,
            passage,
            snippet_chars,
            suffix=f" ranks[{component_ranks}]",
        )


def _log_passage(
    rank: int,
    score: float,
    passage: SourcePassage,
    snippet_chars: int,
    *,
    suffix: str = "",
) -> None:
    location = passage.section_title or "unknown section"
    if passage.page_number is not None:
        location = f"{location}, page {passage.page_number}"
    logger.info(
        "#%d score=%.6f key=%s:%d %s %s%s",
        rank,
        score,
        passage.accession_number,
        passage.chunk_index,
        passage.ticker,
        location,
        suffix,
    )
    text = " ".join(passage.text.split())
    ellipsis = "…" if len(text) > snippet_chars else ""
    logger.info("   %s%s", text[:snippet_chars], ellipsis)
