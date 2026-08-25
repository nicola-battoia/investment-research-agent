"""Transactionally delete all chat data and document chunks before reingestion."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

CONFIRMATION = "delete-all-chats-and-chunks"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResetSummary:
    thread_count: int
    message_count: int
    citation_count: int
    chunk_count: int
    source_document_count: int


def inspect_reset(connection: Connection) -> ResetSummary:
    return ResetSummary(
        thread_count=_count_rows(connection, "chat_threads"),
        message_count=_count_rows(connection, "chat_messages"),
        citation_count=_count_rows(connection, "message_citations"),
        chunk_count=_count_rows(connection, "document_chunks"),
        source_document_count=_count_rows(connection, "source_documents"),
    )


def execute_reset(connection: Connection) -> None:
    # Citations restrict chunk deletion, while deleting threads cascades through
    # messages and citations. This order keeps the operation referentially valid.
    connection.execute(text("DELETE FROM public.chat_threads"))
    connection.execute(text("DELETE FROM public.document_chunks"))


def _count_rows(connection: Connection, table_name: str) -> int:
    allowed_tables = {
        "chat_threads",
        "chat_messages",
        "message_citations",
        "document_chunks",
        "source_documents",
    }
    if table_name not in allowed_tables:
        raise ValueError(f"Unsupported reset table: {table_name}")
    value = connection.scalar(text(f"SELECT count(*) FROM public.{table_name}"))
    if not isinstance(value, int):
        raise TypeError(f"Database returned an invalid count for {table_name}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete every chat thread (cascading to messages and citations) and "
            "every document chunk in one transaction."
        )
    )
    parser.add_argument(
        "--confirm",
        help=f"Required destructive confirmation: {CONFIRMATION}",
    )
    return parser.parse_args()


def main() -> None:
    from app.config import settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with engine.begin() as connection:
            before = inspect_reset(connection)
            logger.info(
                "Reset would delete %d threads, %d messages, %d citations, and "
                "%d chunks; %d source documents would remain",
                before.thread_count,
                before.message_count,
                before.citation_count,
                before.chunk_count,
                before.source_document_count,
            )
            if args.confirm != CONFIRMATION:
                logger.info(
                    "Dry run only. To execute, pass --confirm %s",
                    CONFIRMATION,
                )
                return

            execute_reset(connection)
            after = inspect_reset(connection)
            if (
                after.thread_count
                or after.message_count
                or after.citation_count
                or after.chunk_count
            ):
                raise RuntimeError(f"Reset verification failed: {after}")
            if after.source_document_count != before.source_document_count:
                raise RuntimeError("Reset unexpectedly changed source_documents")
            logger.info(
                "Reset complete and verified; %d source documents remain",
                after.source_document_count,
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
