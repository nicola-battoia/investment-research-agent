import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from app.retrieval.models import (
    ExtractedKeywords,
    KeywordGroup,
    RetrievalFilters,
    SourcePassage,
)
from app.retrieval.queries import RankedCandidate
from app.retrieval.retriever import DocumentRetriever

IDS = tuple(UUID(int=value) for value in range(1, 8))
DOCUMENT_ID = UUID(int=100)


def embedding_client(vector: list[float] | None = None) -> SimpleNamespace:
    create = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=vector or [0.1, 0.2, 0.3])]
        )
    )
    return SimpleNamespace(embeddings=SimpleNamespace(create=create))


def keyword_extractor(
    keywords: ExtractedKeywords | None = None,
) -> SimpleNamespace:
    extracted = keywords or ExtractedKeywords(
        groups=(KeywordGroup(terms=("revenue", "net sales")),)
    )
    return SimpleNamespace(extract=AsyncMock(return_value=extracted))


def passage(
    chunk_id: UUID,
    chunk_index: int,
    *,
    section: str | None = "Revenue",
) -> SourcePassage:
    return SourcePassage(
        chunk_id=chunk_id,
        document_id=DOCUMENT_ID,
        chunk_index=chunk_index,
        text=f"Passage {chunk_index}",
        token_count=20,
        page_number=1,
        section_title=section,
        source_start=chunk_index * 10,
        source_end=chunk_index * 10 + 9,
        metadata={"contains_table": False},
        company="Apple Inc.",
        ticker="AAPL",
        filing_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        accession_number="0000320193-24-000123",
        sec_url="https://www.sec.gov/example",
    )


def retriever(client: SimpleNamespace | None = None) -> DocumentRetriever:
    return DocumentRetriever(
        client or SimpleNamespace(),
        embedding_client(),
        keyword_extractor(),
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
    )


def test_search_embeds_once_fuses_deduplicates_and_preserves_hydration_order() -> None:
    service = retriever()
    semantic = [RankedCandidate(IDS[0], 0.9), RankedCandidate(IDS[1], 0.8)]
    lexical = [RankedCandidate(IDS[1], 4.0), RankedCandidate(IDS[2], 3.0)]
    hydrated = {
        IDS[0]: passage(IDS[0], 10),
        IDS[1]: passage(IDS[1], 20),
        IDS[2]: passage(IDS[2], 30),
    }

    async def hydrate_in_requested_order(_client, chunk_ids):
        return [hydrated[chunk_id] for chunk_id in chunk_ids]

    with (
        patch(
            "app.retrieval.retriever.semantic_search",
            AsyncMock(return_value=semantic),
        ) as semantic_search,
        patch(
            "app.retrieval.retriever.lexical_search",
            AsyncMock(return_value=lexical),
        ) as lexical_search,
        patch(
            "app.retrieval.retriever.hydrate_passages",
            AsyncMock(side_effect=hydrate_in_requested_order),
        ) as hydrate,
    ):
        result = asyncio.run(
            service.search(
                "  revenue mix  ",
                RetrievalFilters(tickers=("aapl",)),
                limit=3,
            )
        )

    assert [item.chunk_id for item in result.passages] == [IDS[1], IDS[0], IDS[2]]
    assert result.passages[0].semantic_rank == 2
    assert result.passages[0].lexical_rank == 1
    assert result.context_passages == ()
    assert result.keywords.search_text == "revenue net sales"
    semantic_search.assert_awaited_once()
    lexical_search.assert_awaited_once()
    assert lexical_search.await_args.args[1] == "revenue net sales"
    hydrate.assert_awaited_once_with(service._supabase, [IDS[1], IDS[0], IDS[2]])
    service._embedding_client.embeddings.create.assert_awaited_once_with(
        input=["revenue mix"],
        model="text-embedding-3-small",
        dimensions=3,
    )


def test_search_adds_only_a_missing_same_section_bridge() -> None:
    service = retriever()
    semantic = [RankedCandidate(IDS[0], 0.9), RankedCandidate(IDS[1], 0.8)]
    primary = [passage(IDS[0], 10), passage(IDS[1], 12)]
    bridge = passage(IDS[2], 11)

    with (
        patch(
            "app.retrieval.retriever.semantic_search",
            AsyncMock(return_value=semantic),
        ),
        patch(
            "app.retrieval.retriever.lexical_search",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.retrieval.retriever.hydrate_passages",
            AsyncMock(return_value=primary),
        ),
        patch(
            "app.retrieval.retriever.hydrate_passage_keys",
            AsyncMock(return_value=[bridge]),
        ) as hydrate_keys,
    ):
        result = asyncio.run(service.search("revenue", limit=2))

    assert result.context_passages == (
        bridge.model_copy(update={"passage_kind": "neighbor"}),
    )
    hydrate_keys.assert_awaited_once_with(service._supabase, {DOCUMENT_ID: {11}})


def test_search_discards_a_bridge_that_starts_another_section() -> None:
    service = retriever()
    semantic = [RankedCandidate(IDS[0], 0.9), RankedCandidate(IDS[1], 0.8)]
    primary = [passage(IDS[0], 10), passage(IDS[1], 12)]
    different_section = passage(IDS[2], 11, section="Risk Factors")

    with (
        patch(
            "app.retrieval.retriever.semantic_search",
            AsyncMock(return_value=semantic),
        ),
        patch(
            "app.retrieval.retriever.lexical_search",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.retrieval.retriever.hydrate_passages",
            AsyncMock(return_value=primary),
        ),
        patch(
            "app.retrieval.retriever.hydrate_passage_keys",
            AsyncMock(return_value=[different_section]),
        ),
    ):
        result = asyncio.run(service.search("revenue", limit=2))

    assert result.context_passages == ()


def test_surrounding_chunks_is_bounded_and_marks_neighbors() -> None:
    service = retriever()
    neighbors = [passage(IDS[1], 9), passage(IDS[2], 11)]
    with patch(
        "app.retrieval.retriever.passage_and_surroundings",
        AsyncMock(return_value=(passage(IDS[0], 10), neighbors)),
    ) as surrounding:
        result = asyncio.run(service.surrounding_chunks(IDS[0]))

    assert [item.chunk_index for item in result] == [9, 11]
    assert all(item.passage_kind == "neighbor" for item in result)
    surrounding.assert_awaited_once_with(service._supabase, IDS[0], 1)


@pytest.mark.parametrize(
    ("query", "limit", "candidate_limit", "message"),
    [
        (" ", 10, 50, "cannot be empty"),
        ("query", 0, 50, "Result limit"),
        ("query", 10, 5, "Candidate limit"),
    ],
)
def test_search_rejects_invalid_bounds(
    query: str,
    limit: int,
    candidate_limit: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        asyncio.run(
            retriever().search(
                query,
                limit=limit,
                candidate_limit=candidate_limit,
            )
        )


def test_query_embedding_rejects_wrong_dimensions() -> None:
    service = DocumentRetriever(
        SimpleNamespace(),
        embedding_client([0.1]),
        keyword_extractor(),
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
    )

    with pytest.raises(ValueError, match="unexpected dimensions"):
        asyncio.run(service.candidate_rankings("query"))


@pytest.mark.parametrize(
    "data",
    [
        [],
        [SimpleNamespace(index=1, embedding=[0.1, 0.2, 0.3])],
        [
            SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3]),
            SimpleNamespace(index=1, embedding=[0.4, 0.5, 0.6]),
        ],
    ],
)
def test_query_embedding_rejects_unexpected_response_indexes(
    data: list[SimpleNamespace],
) -> None:
    client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(data=data))
        )
    )
    service = DocumentRetriever(
        SimpleNamespace(),
        client,
        keyword_extractor(),
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
    )

    with pytest.raises(ValueError, match="unexpected query embedding indexes"):
        asyncio.run(service.candidate_rankings("query"))


def test_candidate_branches_execute_concurrently() -> None:
    async def exercise() -> None:
        both_started = asyncio.Event()
        started: set[str] = set()

        async def start(name: str) -> None:
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.1)

        async def create_embedding(**_kwargs):
            await start("embedding")
            return SimpleNamespace(
                data=[SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3])]
            )

        async def extract_keywords(_query: str) -> ExtractedKeywords:
            await start("keywords")
            return ExtractedKeywords(groups=(KeywordGroup(terms=("revenue",)),))

        openai = embedding_client()
        openai.embeddings.create.side_effect = create_embedding
        extractor = keyword_extractor()
        extractor.extract.side_effect = extract_keywords
        service = DocumentRetriever(
            SimpleNamespace(),
            openai,
            extractor,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=3,
        )

        with (
            patch(
                "app.retrieval.retriever.semantic_search",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.retrieval.retriever.lexical_search",
                AsyncMock(return_value=[]),
            ),
        ):
            await service.candidate_rankings("query")

        assert started == {"embedding", "keywords"}

    asyncio.run(exercise())


def test_candidate_details_preserve_branch_scores_and_fused_ranks() -> None:
    service = retriever()
    semantic = [RankedCandidate(IDS[0], 0.91), RankedCandidate(IDS[1], 0.82)]
    lexical = [RankedCandidate(IDS[1], 1.4), RankedCandidate(IDS[2], 0.7)]

    with (
        patch(
            "app.retrieval.retriever.semantic_search",
            AsyncMock(return_value=semantic),
        ),
        patch(
            "app.retrieval.retriever.lexical_search",
            AsyncMock(return_value=lexical),
        ),
    ):
        details = asyncio.run(service.candidate_details("revenue"))

    assert details.semantic == tuple(semantic)
    assert details.lexical == tuple(lexical)
    assert details.hybrid[0].chunk_id == IDS[1]
    assert details.hybrid[0].ranks == {"semantic": 2, "lexical": 1}
    assert details.keywords.search_text == "revenue net sales"
    assert details.timings.semantic_pipeline_ms >= 0
    assert details.timings.lexical_pipeline_ms >= 0
    assert details.timings.fusion_ms >= 0
    assert details.timings.total_ms >= 0


def test_one_failed_branch_fails_the_whole_search() -> None:
    service = retriever()
    with (
        patch(
            "app.retrieval.retriever.semantic_search",
            AsyncMock(side_effect=RuntimeError("database failed")),
        ),
        patch(
            "app.retrieval.retriever.lexical_search",
            AsyncMock(return_value=[]),
        ),
        pytest.raises(RuntimeError, match="database failed"),
    ):
        asyncio.run(service.search("query"))


def test_keyword_extraction_failure_fails_the_whole_search() -> None:
    extractor = keyword_extractor()
    extractor.extract.side_effect = RuntimeError("keyword model failed")
    service = DocumentRetriever(
        SimpleNamespace(),
        embedding_client(),
        extractor,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
    )

    with (
        patch(
            "app.retrieval.retriever.semantic_search",
            AsyncMock(return_value=[]),
        ),
        pytest.raises(RuntimeError, match="keyword model failed"),
    ):
        asyncio.run(service.search("query"))
