from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ingestion.chunk_documents import PreparedChunk
from ingestion.create_embeddings import create_embeddings


def test_create_embeddings_batches_inputs_and_preserves_order() -> None:
    client = MagicMock()
    client.embeddings.create = AsyncMock(
        side_effect=[
            _response([[0.1, 0.2, 0.3], [1.1, 1.2, 1.3]], total_tokens=4),
            _response([[2.1, 2.2, 2.3]], total_tokens=1),
        ]
    )
    chunks = [_chunk(0, 2), _chunk(1, 2), _chunk(2, 1)]

    result = asyncio.run(
        create_embeddings(
            client,
            chunks,
            model="text-embedding-3-small",
            dimensions=3,
            batch_size=2,
            max_batch_tokens=4,
        )
    )

    assert result.vectors == [
        [0.1, 0.2, 0.3],
        [1.1, 1.2, 1.3],
        [2.1, 2.2, 2.3],
    ]
    assert result.total_tokens == 5
    assert result.request_count == 2
    assert client.embeddings.create.await_args_list[0].kwargs == {
        "input": ["Chunk 0", "Chunk 1"],
        "model": "text-embedding-3-small",
        "dimensions": 3,
    }
    assert client.embeddings.create.await_args_list[1].kwargs["input"] == ["Chunk 2"]


def test_create_embeddings_rejects_wrong_vector_dimensions() -> None:
    client = MagicMock()
    client.embeddings.create = AsyncMock(
        return_value=_response([[0.1, 0.2]], total_tokens=1)
    )

    with pytest.raises(ValueError, match="unexpected dimensions"):
        asyncio.run(
            create_embeddings(
                client,
                [_chunk(0, 1)],
                model="text-embedding-3-small",
                dimensions=3,
            )
        )


def test_create_embeddings_rejects_oversized_input_before_api_call() -> None:
    client = MagicMock()
    client.embeddings.create = AsyncMock()

    with pytest.raises(ValueError, match="OpenAI's limit"):
        asyncio.run(
            create_embeddings(
                client,
                [_chunk(0, 8_193)],
                model="text-embedding-3-small",
                dimensions=3,
            )
        )

    client.embeddings.create.assert_not_awaited()


def _chunk(index: int, token_count: int) -> PreparedChunk:
    return PreparedChunk(
        chunk_index=index,
        text=f"Chunk {index}",
        token_count=token_count,
        page_number=None,
        section_title=None,
        source_start=None,
        source_end=None,
        metadata={},
    )


def _response(
    vectors: list[list[float]],
    *,
    total_tokens: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in enumerate(vectors)
        ],
        usage=SimpleNamespace(total_tokens=total_tokens),
    )
