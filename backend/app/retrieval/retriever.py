"""Query embedding, ranked-list fusion, and source-passage hydration."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.retrieval.fusion import DEFAULT_RRF_K, FusedRank, reciprocal_rank_fusion
from app.retrieval.keywords import KeywordExtractor
from app.retrieval.models import (
    ExtractedKeywords,
    RetrievalFilters,
    RetrievalResult,
    SourcePassage,
)
from app.retrieval.queries import (
    RankedCandidate,
    RpcClient,
    hydrate_passage_keys,
    hydrate_passages,
    lexical_search,
    passage_and_surroundings,
    semantic_search,
)

DEFAULT_RESULT_LIMIT = 10
DEFAULT_CANDIDATE_LIMIT = 50
DEFAULT_SEMANTIC_WEIGHT = 20.0
DEFAULT_LEXICAL_WEIGHT = 1.0
MAX_RESULT_LIMIT = 20


@dataclass(frozen=True)
class RetrievalRankings:
    semantic: tuple[UUID, ...]
    lexical: tuple[UUID, ...]
    hybrid: tuple[UUID, ...]
    keywords: ExtractedKeywords


@dataclass(frozen=True)
class RetrievalTimings:
    semantic_pipeline_ms: float
    lexical_pipeline_ms: float
    fusion_ms: float
    total_ms: float


@dataclass(frozen=True)
class RetrievalCandidates:
    semantic: tuple[RankedCandidate, ...]
    lexical: tuple[RankedCandidate, ...]
    hybrid: tuple[FusedRank, ...]
    keywords: ExtractedKeywords
    timings: RetrievalTimings


class EmbeddingItem(Protocol):
    index: int
    embedding: list[float]


class EmbeddingResponse(Protocol):
    data: list[EmbeddingItem]


class EmbeddingsResource(Protocol):
    async def create(
        self,
        *,
        input: list[str],
        model: str,
        dimensions: int,
    ) -> EmbeddingResponse: ...


class EmbeddingClient(Protocol):
    embeddings: EmbeddingsResource


class DocumentRetriever:
    """Request-scoped hybrid retriever suitable for later agent injection."""

    def __init__(
        self,
        supabase: RpcClient,
        embedding_client: EmbeddingClient,
        keyword_extractor: KeywordExtractor,
        *,
        embedding_model: str,
        embedding_dimensions: int,
        semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
        lexical_weight: float = DEFAULT_LEXICAL_WEIGHT,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        if not embedding_model:
            raise ValueError("Embedding model is required")
        if embedding_dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive")
        if semantic_weight < 0 or lexical_weight < 0:
            raise ValueError("Retrieval weights cannot be negative")
        if semantic_weight == 0 and lexical_weight == 0:
            raise ValueError("At least one retrieval weight must be positive")
        if rrf_k <= 0:
            raise ValueError("RRF smoothing constant must be positive")

        self._supabase = supabase
        self._embedding_client = embedding_client
        self._keyword_extractor = keyword_extractor
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._weights = {
            "semantic": semantic_weight,
            "lexical": lexical_weight,
        }
        self._rrf_k = rrf_k

    async def search(
        self,
        query: str,
        filters: RetrievalFilters | None = None,
        *,
        limit: int = DEFAULT_RESULT_LIMIT,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> RetrievalResult:
        query = query.strip()
        if not query:
            raise ValueError("Retrieval query cannot be empty")
        if limit <= 0 or limit > MAX_RESULT_LIMIT:
            raise ValueError(f"Result limit must be between 1 and {MAX_RESULT_LIMIT}")
        if candidate_limit < limit or candidate_limit > 100:
            raise ValueError(
                "Candidate limit must be at least the result limit and at most 100"
            )

        active_filters = filters or RetrievalFilters()
        candidates = await self.candidate_details(
            query,
            active_filters,
            candidate_limit=candidate_limit,
        )
        fused = candidates.hybrid[:limit]
        passages = await hydrate_passages(
            self._supabase,
            [result.chunk_id for result in fused],
        )
        ranked_passages = tuple(
            passage.model_copy(
                update={
                    "semantic_rank": result.ranks.get("semantic"),
                    "lexical_rank": result.ranks.get("lexical"),
                    "fused_score": result.score,
                    "passage_kind": "ranked",
                }
            )
            for result, passage in zip(fused, passages, strict=True)
        )
        context_passages = await self._bridge_context(ranked_passages)
        return RetrievalResult(
            passages=ranked_passages,
            context_passages=context_passages,
            keywords=candidates.keywords,
        )

    async def candidate_rankings(
        self,
        query: str,
        filters: RetrievalFilters | None = None,
        *,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> RetrievalRankings:
        """Return the three candidate rankings for retrieval evaluation."""
        candidates = await self.candidate_details(
            query,
            filters,
            candidate_limit=candidate_limit,
        )
        return RetrievalRankings(
            semantic=tuple(candidate.chunk_id for candidate in candidates.semantic),
            lexical=tuple(candidate.chunk_id for candidate in candidates.lexical),
            hybrid=tuple(result.chunk_id for result in candidates.hybrid),
            keywords=candidates.keywords,
        )

    async def candidate_details(
        self,
        query: str,
        filters: RetrievalFilters | None = None,
        *,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> RetrievalCandidates:
        """Return scored branch candidates, fused ranks, and diagnostic timings."""
        query = query.strip()
        if not query:
            raise ValueError("Retrieval query cannot be empty")
        if candidate_limit <= 0 or candidate_limit > 100:
            raise ValueError("Candidate limit must be between 1 and 100")
        active_filters = filters or RetrievalFilters()
        started = time.perf_counter()

        async def semantic_branch() -> tuple[list[RankedCandidate], float]:
            branch_started = time.perf_counter()
            embedding = await self._embed_query(query)
            candidates = await semantic_search(
                self._supabase,
                embedding,
                active_filters,
                candidate_limit,
            )
            return candidates, (time.perf_counter() - branch_started) * 1000

        async def lexical_branch() -> tuple[
            ExtractedKeywords,
            list[RankedCandidate],
            float,
        ]:
            branch_started = time.perf_counter()
            keywords = await self._keyword_extractor.extract(query)
            candidates = await lexical_search(
                self._supabase,
                keywords.search_text,
                active_filters,
                candidate_limit,
            )
            return keywords, candidates, (time.perf_counter() - branch_started) * 1000

        (semantic, semantic_ms), (keywords, lexical, lexical_ms) = await asyncio.gather(
            semantic_branch(),
            lexical_branch(),
        )
        fusion_started = time.perf_counter()
        fused = reciprocal_rank_fusion(
            {
                "semantic": [candidate.chunk_id for candidate in semantic],
                "lexical": [candidate.chunk_id for candidate in lexical],
            },
            k=self._rrf_k,
            weights=self._weights,
        )
        fusion_ms = (time.perf_counter() - fusion_started) * 1000
        return RetrievalCandidates(
            semantic=tuple(semantic),
            lexical=tuple(lexical),
            hybrid=tuple(fused),
            keywords=keywords,
            timings=RetrievalTimings(
                semantic_pipeline_ms=semantic_ms,
                lexical_pipeline_ms=lexical_ms,
                fusion_ms=fusion_ms,
                total_ms=(time.perf_counter() - started) * 1000,
            ),
        )

    async def surrounding_chunks(
        self,
        chunk_id: UUID,
        *,
        radius: int = 1,
    ) -> list[SourcePassage]:
        _anchor, neighbors = await passage_and_surroundings(
            self._supabase,
            chunk_id,
            radius,
        )
        return [
            passage.model_copy(update={"passage_kind": "neighbor"})
            for passage in neighbors
        ]

    async def _embed_query(self, query: str) -> list[float]:
        response = await self._embedding_client.embeddings.create(
            input=[query],
            model=self._embedding_model,
            dimensions=self._embedding_dimensions,
        )
        data = getattr(response, "data", None)
        if not isinstance(data, list) or len(data) != 1 or data[0].index != 0:
            raise ValueError("OpenAI returned unexpected query embedding indexes")
        embedding = list(data[0].embedding)
        if len(embedding) != self._embedding_dimensions:
            raise ValueError(
                "OpenAI returned an embedding with unexpected dimensions: "
                f"expected {self._embedding_dimensions}, received {len(embedding)}"
            )
        return embedding

    async def _bridge_context(
        self,
        passages: Sequence[SourcePassage],
    ) -> tuple[SourcePassage, ...]:
        requested: dict[UUID, set[int]] = {}
        expected_sections: dict[tuple[UUID, int], str] = {}
        for index, left in enumerate(passages):
            if left.section_title is None:
                continue
            for right in passages[index + 1 :]:
                if (
                    left.document_id == right.document_id
                    and left.section_title == right.section_title
                    and abs(left.chunk_index - right.chunk_index) == 2
                ):
                    bridge_index = min(left.chunk_index, right.chunk_index) + 1
                    requested.setdefault(left.document_id, set()).add(bridge_index)
                    expected_sections[(left.document_id, bridge_index)] = (
                        left.section_title
                    )

        if not requested:
            return ()
        bridges = await hydrate_passage_keys(self._supabase, requested)
        expected = {
            (document_id, chunk_index)
            for document_id, indexes in requested.items()
            for chunk_index in indexes
        }
        returned = {(passage.document_id, passage.chunk_index) for passage in bridges}
        if returned != expected:
            raise ValueError("Supabase did not return every requested bridge chunk")
        return tuple(
            passage.model_copy(update={"passage_kind": "neighbor"})
            for passage in sorted(
                (
                    passage
                    for passage in bridges
                    if passage.section_title
                    == expected_sections[(passage.document_id, passage.chunk_index)]
                ),
                key=lambda passage: (str(passage.document_id), passage.chunk_index),
            )
        )
