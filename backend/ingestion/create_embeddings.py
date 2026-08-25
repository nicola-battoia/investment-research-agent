"""Create OpenAI embeddings for prepared SEC filing chunks."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI

from ingestion.chunk_documents import (
    MAX_EMBEDDING_INPUT_TOKENS,
    OpenAITokenCounter,
    PreparedChunk,
    chunk_document,
    document_paths,
    source_row_for_accession,
)

DEFAULT_BATCH_SIZE = 128
MAX_BATCH_INPUTS = 2_048
MAX_BATCH_TOKENS = 250_000

logger = logging.getLogger(__name__)


class EmbeddingItem(Protocol):
    index: int
    embedding: list[float]


class EmbeddingUsage(Protocol):
    total_tokens: int


class EmbeddingResponse(Protocol):
    data: list[EmbeddingItem]
    usage: EmbeddingUsage


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


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    total_tokens: int
    request_count: int


async def create_embeddings(
    client: EmbeddingClient,
    chunks: Sequence[PreparedChunk],
    *,
    model: str,
    dimensions: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_batch_tokens: int = MAX_BATCH_TOKENS,
) -> EmbeddingResult:
    if not chunks:
        raise ValueError("At least one chunk is required to create embeddings")
    if dimensions <= 0:
        raise ValueError("Embedding dimensions must be positive")

    vectors = []
    total_tokens = 0
    request_count = 0
    for batch in embedding_batches(
        chunks,
        batch_size=batch_size,
        max_batch_tokens=max_batch_tokens,
    ):
        response = await client.embeddings.create(
            input=[chunk.text for chunk in batch],
            model=model,
            dimensions=dimensions,
        )
        ordered_items = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in ordered_items] != list(range(len(batch))):
            raise ValueError("OpenAI returned unexpected embedding indexes")

        batch_vectors = [list(item.embedding) for item in ordered_items]
        invalid_dimensions = [
            len(vector) for vector in batch_vectors if len(vector) != dimensions
        ]
        if invalid_dimensions:
            raise ValueError(
                "OpenAI returned an embedding with unexpected dimensions: "
                f"expected {dimensions}, received {invalid_dimensions[0]}"
            )

        vectors.extend(batch_vectors)
        total_tokens += response.usage.total_tokens
        request_count += 1

    return EmbeddingResult(
        vectors=vectors,
        total_tokens=total_tokens,
        request_count=request_count,
    )


def embedding_batches(
    chunks: Sequence[PreparedChunk],
    *,
    batch_size: int,
    max_batch_tokens: int,
) -> Iterator[list[PreparedChunk]]:
    if batch_size <= 0 or batch_size > MAX_BATCH_INPUTS:
        raise ValueError(f"Batch size must be between 1 and {MAX_BATCH_INPUTS}")
    if max_batch_tokens <= 0:
        raise ValueError("Maximum batch tokens must be positive")

    batch: list[PreparedChunk] = []
    batch_tokens = 0
    for chunk in chunks:
        if not chunk.text:
            raise ValueError(f"Chunk {chunk.chunk_index} has empty text")
        if chunk.token_count > MAX_EMBEDDING_INPUT_TOKENS:
            raise ValueError(
                f"Chunk {chunk.chunk_index} has {chunk.token_count} tokens; "
                f"OpenAI's limit is {MAX_EMBEDDING_INPUT_TOKENS}"
            )
        if chunk.token_count > max_batch_tokens:
            raise ValueError(
                f"Chunk {chunk.chunk_index} exceeds the batch token budget"
            )

        if batch and (
            len(batch) >= batch_size
            or batch_tokens + chunk.token_count > max_batch_tokens
        ):
            yield batch
            batch = []
            batch_tokens = 0

        batch.append(chunk)
        batch_tokens += chunk.token_count

    if batch:
        yield batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded paid embedding smoke test without database writes."
    )
    parser.add_argument("--accession-number", required=True)
    parser.add_argument(
        "--limit-chunks",
        type=int,
        required=True,
        help="Maximum chunks to embed; required to prevent accidental full-corpus cost.",
    )
    return parser.parse_args()


def main() -> None:
    from app.config import settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    if args.limit_chunks <= 0:
        raise ValueError("--limit-chunks must be positive")

    source_row = source_row_for_accession(args.accession_number)
    parsed_path, markdown_path = document_paths(source_row)
    chunks = chunk_document(
        parsed_path,
        markdown_path,
        OpenAITokenCounter(settings.openai_embedding_model),
    )[: args.limit_chunks]
    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        max_retries=3,
    )
    result = asyncio.run(
        create_embeddings(
            client,
            chunks,
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
        )
    )
    logger.info(
        "Embedding smoke test complete: %d chunks, %d dimensions, %d input "
        "tokens, %d request(s); no database rows were written",
        len(result.vectors),
        len(result.vectors[0]),
        result.total_tokens,
        result.request_count,
    )


if __name__ == "__main__":
    main()
