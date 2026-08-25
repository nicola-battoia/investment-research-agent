from unittest.mock import MagicMock

from ingestion.reset_ingestion import ResetSummary, execute_reset, inspect_reset


def test_inspect_reset_counts_all_affected_tables() -> None:
    connection = MagicMock()
    connection.scalar.side_effect = [15, 50, 21, 40_920, 27]

    summary = inspect_reset(connection)

    assert summary == ResetSummary(
        thread_count=15,
        message_count=50,
        citation_count=21,
        chunk_count=40_920,
        source_document_count=27,
    )
    statements = [str(call.args[0]) for call in connection.scalar.call_args_list]
    assert statements == [
        "SELECT count(*) FROM public.chat_threads",
        "SELECT count(*) FROM public.chat_messages",
        "SELECT count(*) FROM public.message_citations",
        "SELECT count(*) FROM public.document_chunks",
        "SELECT count(*) FROM public.source_documents",
    ]


def test_execute_reset_deletes_threads_before_chunks() -> None:
    connection = MagicMock()

    execute_reset(connection)

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements == [
        "DELETE FROM public.chat_threads",
        "DELETE FROM public.document_chunks",
    ]
