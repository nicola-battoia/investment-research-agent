from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from postgrest import CountMethod

from ingestion.upload_checkpoints import _document_upload_is_complete


def test_document_upload_is_complete_checks_count_and_last_index() -> None:
    count_query = MagicMock()
    count_query.eq.return_value = count_query
    count_query.execute = AsyncMock(return_value=SimpleNamespace(count=140))
    last_query = MagicMock()
    last_query.eq.return_value = last_query
    last_query.order.return_value = last_query
    last_query.limit.return_value = last_query
    last_query.execute = AsyncMock(
        return_value=SimpleNamespace(data=[{"chunk_index": 139}])
    )
    table = MagicMock()
    table.select.side_effect = [count_query, last_query]
    client = MagicMock()
    client.table.return_value = table

    complete = asyncio.run(
        _document_upload_is_complete(
            client,
            "document-id",
            expected_chunk_count=140,
        )
    )

    assert complete is True
    client.table.assert_called_once_with("document_chunks")
    assert table.select.call_args_list[0].args == ("id",)
    assert table.select.call_args_list[0].kwargs == {
        "count": CountMethod.exact,
        "head": True,
    }
    last_query.order.assert_called_once_with("chunk_index", desc=True)


def test_document_upload_is_incomplete_when_count_differs() -> None:
    count_query = MagicMock()
    count_query.eq.return_value = count_query
    count_query.execute = AsyncMock(return_value=SimpleNamespace(count=139))
    table = MagicMock()
    table.select.return_value = count_query
    client = MagicMock()
    client.table.return_value = table

    complete = asyncio.run(
        _document_upload_is_complete(
            client,
            "document-id",
            expected_chunk_count=140,
        )
    )

    assert complete is False
    table.select.assert_called_once()
