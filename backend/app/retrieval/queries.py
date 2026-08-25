"""Bounded Supabase queries and strict retrieval-row parsing."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from app.retrieval.models import RetrievalFilters, SourcePassage

SEMANTIC_RPC = "match_document_chunks_semantic"
LEXICAL_RPC = "match_document_chunks_lexical"
MAX_CANDIDATES = 100
SOURCE_PASSAGE_COLUMNS = (
    "id,document_id,chunk_index,text,token_count,page_number,section_title,"
    "source_start,source_end,metadata,display_table,"
    "source_documents!inner(company,ticker,filing_type,filing_date,report_date,"
    "accession_number,sec_url)"
)


class ExecutableQuery(Protocol):
    async def execute(self) -> object: ...


class RpcClient(Protocol):
    def rpc(self, fn: str, params: dict[str, object]) -> ExecutableQuery: ...

    def table(self, table: str) -> object: ...


@dataclass(frozen=True)
class RankedCandidate:
    chunk_id: UUID
    score: float


def _validated_limit(limit: int) -> int:
    if limit <= 0 or limit > MAX_CANDIDATES:
        raise ValueError(f"Candidate limit must be between 1 and {MAX_CANDIDATES}")
    return limit


def _filter_params(filters: RetrievalFilters, limit: int) -> dict[str, object]:
    return {
        "p_match_count": _validated_limit(limit),
        "p_companies": list(filters.companies),
        "p_tickers": list(filters.tickers),
        "p_filing_types": list(filters.filing_types),
        "p_filing_years": list(filters.filing_years),
        "p_filed_on_or_after": (
            filters.filed_on_or_after.isoformat()
            if filters.filed_on_or_after is not None
            else None
        ),
        "p_filed_on_or_before": (
            filters.filed_on_or_before.isoformat()
            if filters.filed_on_or_before is not None
            else None
        ),
    }


def semantic_rpc_params(
    embedding: Sequence[float],
    filters: RetrievalFilters,
    limit: int,
) -> dict[str, object]:
    return {
        "p_query_embedding": list(embedding),
        **_filter_params(filters, limit),
    }


def lexical_rpc_params(
    query: str,
    filters: RetrievalFilters,
    limit: int,
) -> dict[str, object]:
    if not query.strip():
        raise ValueError("Retrieval query cannot be empty")
    return {
        "p_query_text": query.strip(),
        **_filter_params(filters, limit),
    }


async def semantic_search(
    client: RpcClient,
    embedding: Sequence[float],
    filters: RetrievalFilters,
    limit: int,
) -> list[RankedCandidate]:
    response = await client.rpc(
        SEMANTIC_RPC,
        semantic_rpc_params(embedding, filters, limit),
    ).execute()
    return _ranked_candidates(response, SEMANTIC_RPC)


async def lexical_search(
    client: RpcClient,
    query: str,
    filters: RetrievalFilters,
    limit: int,
) -> list[RankedCandidate]:
    response = await client.rpc(
        LEXICAL_RPC,
        lexical_rpc_params(query, filters, limit),
    ).execute()
    return _ranked_candidates(response, LEXICAL_RPC)


def _ranked_candidates(response: object, source: str) -> list[RankedCandidate]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise TypeError(f"Supabase {source} response must contain a data list")

    candidates = []
    for value in data:
        if not isinstance(value, dict):
            raise TypeError(f"Supabase {source} returned a non-object row")
        chunk_id = value.get("chunk_id")
        score = value.get("score")
        if not isinstance(chunk_id, str):
            raise TypeError(f"Supabase {source} chunk_id must be a string")
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise TypeError(f"Supabase {source} score must be numeric")
        candidates.append(RankedCandidate(UUID(chunk_id), float(score)))
    return candidates


async def hydrate_passages(
    client: RpcClient,
    chunk_ids: Sequence[UUID],
) -> list[SourcePassage]:
    if not chunk_ids:
        return []
    builder = cast(object, client.table("document_chunks"))
    response = (
        await builder.select(SOURCE_PASSAGE_COLUMNS)
        .in_("id", [str(chunk_id) for chunk_id in chunk_ids])
        .execute()
    )
    passages = _source_passages(response)
    by_id = {passage.chunk_id: passage for passage in passages}
    missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in by_id]
    if missing:
        raise ValueError(f"Supabase did not return requested chunks: {missing}")
    return [by_id[chunk_id] for chunk_id in chunk_ids]


async def hydrate_passage_keys(
    client: RpcClient,
    keys: Mapping[UUID, set[int]],
) -> list[SourcePassage]:
    async def fetch(document_id: UUID, indexes: set[int]) -> list[SourcePassage]:
        builder = cast(object, client.table("document_chunks"))
        response = await (
            builder.select(SOURCE_PASSAGE_COLUMNS)
            .eq("document_id", str(document_id))
            .in_("chunk_index", sorted(indexes))
            .execute()
        )
        return _source_passages(response)

    groups = await asyncio.gather(
        *(fetch(document_id, indexes) for document_id, indexes in keys.items())
    )
    return [passage for group in groups for passage in group]


async def passage_and_surroundings(
    client: RpcClient,
    chunk_id: UUID,
    radius: int,
) -> tuple[SourcePassage, list[SourcePassage]]:
    if radius != 1:
        raise ValueError("Surrounding chunk radius must be exactly 1")
    anchor = (await hydrate_passages(client, [chunk_id]))[0]
    builder = cast(object, client.table("document_chunks"))
    response = await (
        builder.select(SOURCE_PASSAGE_COLUMNS)
        .eq("document_id", str(anchor.document_id))
        .gte("chunk_index", max(0, anchor.chunk_index - radius))
        .lte("chunk_index", anchor.chunk_index + radius)
        .execute()
    )
    neighbors = sorted(
        (
            passage
            for passage in _source_passages(response)
            if passage.chunk_id != anchor.chunk_id
        ),
        key=lambda passage: passage.chunk_index,
    )
    return anchor, neighbors


def _source_passages(response: object) -> list[SourcePassage]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise TypeError("Supabase passage response must contain a data list")
    return [_source_passage(value) for value in data]


def _source_passage(value: object) -> SourcePassage:
    if not isinstance(value, dict):
        raise TypeError("Supabase returned a non-object passage row")
    row = dict(value)
    source = row.pop("source_documents", None)
    if not isinstance(source, dict):
        raise TypeError("Supabase passage row is missing source document metadata")
    if not isinstance(row.get("metadata"), dict):
        raise TypeError("Supabase passage metadata must be an object")
    return SourcePassage.model_validate(
        {
            "chunk_id": row.pop("id", None),
            **row,
            **source,
        }
    )
