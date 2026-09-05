"""Query embedding, ranked-list fusion, and source-passage hydration."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.assistant.tracing import AssistantTrace, embedding_summary
from app.config import settings
from app.retrieval.fusion import FusedRank, reciprocal_rank_fusion
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
from app.telemetry import model_call_span, record_model_input, record_model_response


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
        semantic_weight: float = settings.retrieval_semantic_weight,
        lexical_weight: float = settings.retrieval_lexical_weight,
        rrf_k: int = settings.retrieval_rrf_k,
        trace: AssistantTrace | None = None,
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
        self._trace = trace or AssistantTrace.disabled()

    async def search(
        self,
        query: str,
        filters: RetrievalFilters | None = None,
        *,
        limit: int = settings.retrieval_default_result_limit,
        candidate_limit: int = settings.retrieval_default_candidate_limit,
    ) -> RetrievalResult:
        query = query.strip()
        if not query:
            raise ValueError("Retrieval query cannot be empty")
        if limit <= 0 or limit > settings.retrieval_max_result_limit:
            raise ValueError(
                "Result limit must be between 1 and "
                f"{settings.retrieval_max_result_limit}"
            )
        if (
            candidate_limit < limit
            or candidate_limit > settings.retrieval_max_candidate_limit
        ):
            raise ValueError(
                "Candidate limit must be at least the result limit and at most "
                f"{settings.retrieval_max_candidate_limit}"
            )

        active_filters = filters or RetrievalFilters()
        search_started = time.perf_counter()
        self._trace.emit(
            "retrieval_search_started",
            "retrieval.search.started",
            query=query,
            filters=active_filters,
            result_limit=limit,
            candidate_limit=candidate_limit,
        )
        candidates = await self.candidate_details(
            query,
            active_filters,
            candidate_limit=candidate_limit,
        )
        fused = candidates.hybrid[:limit]
        hydration_started = time.perf_counter()
        passages = await hydrate_passages(
            self._supabase,
            [result.chunk_id for result in fused],
        )
        hydration_ms = (time.perf_counter() - hydration_started) * 1000
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
        result = RetrievalResult(
            passages=ranked_passages,
            context_passages=context_passages,
            keywords=candidates.keywords,
        )
        self._trace.emit(
            "retrieval_search_completed",
            "retrieval.search.completed",
            duration_ms=(time.perf_counter() - search_started) * 1000,
            hydration_ms=hydration_ms,
            timings=candidates.timings,
            keywords=candidates.keywords,
            result_count=len(ranked_passages),
            context_passage_count=len(context_passages),
            ranked_passages=ranked_passages,
            context_passages=context_passages,
        )
        return result

    async def candidate_rankings(
        self,
        query: str,
        filters: RetrievalFilters | None = None,
        *,
        candidate_limit: int = settings.retrieval_default_candidate_limit,
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
        candidate_limit: int = settings.retrieval_default_candidate_limit,
    ) -> RetrievalCandidates:
        """Return scored branch candidates, fused ranks, and diagnostic timings."""
        query = query.strip()
        if not query:
            raise ValueError("Retrieval query cannot be empty")
        if (
            candidate_limit <= 0
            or candidate_limit > settings.retrieval_max_candidate_limit
        ):
            raise ValueError(
                "Candidate limit must be between 1 and "
                f"{settings.retrieval_max_candidate_limit}"
            )
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
            duration_ms = (time.perf_counter() - branch_started) * 1000
            self._trace.emit(
                "retrieval_semantic_candidates",
                "retrieval.semantic.completed",
                duration_ms=duration_ms,
                filters=active_filters,
                candidate_count=len(candidates),
                candidates=candidates,
            )
            return candidates, duration_ms

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
            duration_ms = (time.perf_counter() - branch_started) * 1000
            self._trace.emit(
                "retrieval_lexical_candidates",
                "retrieval.lexical.completed",
                duration_ms=duration_ms,
                filters=active_filters,
                lexical_query=keywords.search_text,
                candidate_count=len(candidates),
                candidates=candidates,
            )
            return keywords, candidates, duration_ms

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
        self._trace.emit(
            "retrieval_fusion_completed",
            "retrieval.fusion.completed",
            duration_ms=fusion_ms,
            semantic_weight=self._weights["semantic"],
            lexical_weight=self._weights["lexical"],
            rrf_k=self._rrf_k,
            fused_count=len(fused),
            fused=fused,
        )
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
        radius: int = settings.assistant_surrounding_chunk_radius,
    ) -> list[SourcePassage]:
        started = time.perf_counter()
        self._trace.emit(
            "retrieval_surrounding_started",
            "retrieval.surrounding.started",
            chunk_id=chunk_id,
            radius=radius,
        )
        _anchor, neighbors = await passage_and_surroundings(
            self._supabase,
            chunk_id,
            radius,
        )
        result = [
            passage.model_copy(update={"passage_kind": "neighbor"})
            for passage in neighbors
        ]
        self._trace.emit(
            "retrieval_surrounding_completed",
            "retrieval.surrounding.completed",
            chunk_id=chunk_id,
            radius=radius,
            duration_ms=(time.perf_counter() - started) * 1000,
            passage_count=len(result),
            passages=result,
        )
        return result

    async def _embed_query(self, query: str) -> list[float]:
        started = time.perf_counter()
        self._trace.emit(
            "retrieval_embedding_request",
            "retrieval.embedding.request",
            model=self._embedding_model,
            dimensions=self._embedding_dimensions,
            input=query,
        )
        with model_call_span(
            "embeddings",
            model=self._embedding_model,
            role="retrieval_embedding",
        ) as span:
            span.set_attribute(
                "gen_ai.request.embedding_dimensions", self._embedding_dimensions
            )
            record_model_input(span, user_input=query)
            response = await self._embedding_client.embeddings.create(
                input=[query],
                model=self._embedding_model,
                dimensions=self._embedding_dimensions,
            )
            record_model_response(span, response)
        data = getattr(response, "data", None)
        if not isinstance(data, list) or len(data) != 1 or data[0].index != 0:
            raise ValueError("OpenAI returned unexpected query embedding indexes")
        embedding = list(data[0].embedding)
        if len(embedding) != self._embedding_dimensions:
            raise ValueError(
                "OpenAI returned an embedding with unexpected dimensions: "
                f"expected {self._embedding_dimensions}, received {len(embedding)}"
            )
        self._trace.emit(
            "retrieval_embedding_response",
            "retrieval.embedding.response",
            model=self._embedding_model,
            duration_ms=(time.perf_counter() - started) * 1000,
            output=(
                embedding_summary(embedding) if self._trace.captures_content else None
            ),
            usage=getattr(response, "usage", None),
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
            self._trace.emit(
                "retrieval_bridge_context_skipped",
                "retrieval.bridge.skipped",
                reason="no_same_section_gap",
            )
            return ()
        started = time.perf_counter()
        bridges = await hydrate_passage_keys(self._supabase, requested)
        expected = {
            (document_id, chunk_index)
            for document_id, indexes in requested.items()
            for chunk_index in indexes
        }
        returned = {(passage.document_id, passage.chunk_index) for passage in bridges}
        if returned != expected:
            raise ValueError("Supabase did not return every requested bridge chunk")
        result = tuple(
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
        self._trace.emit(
            "retrieval_bridge_context_completed",
            "retrieval.bridge.completed",
            duration_ms=(time.perf_counter() - started) * 1000,
            requested=requested,
            requested_count=sum(len(indexes) for indexes in requested.values()),
            passage_count=len(result),
            passages=result,
        )
        return result
