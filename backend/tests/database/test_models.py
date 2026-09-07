from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

from app.database import Base

EXPECTED_TABLES = {
    "users",
    "chat_threads",
    "chat_messages",
    "message_citations",
    "source_documents",
    "document_chunks",
    "datasets",
    "cases",
    "runs",
    "results",
}


def foreign_keys(table_name: str) -> dict[str, tuple[str, str | None]]:
    table = Base.metadata.tables[table_name]
    return {
        foreign_key.parent.name: (foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in table.foreign_keys
    }


def unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def check_constraint_names(table_name: str) -> set[str | None]:
    table = Base.metadata.tables[table_name]
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_registers_all_models_and_relationships() -> None:
    app_tables = {
        table.name
        for table in Base.metadata.tables.values()
        if not table.info.get("external")
    }
    assert app_tables == EXPECTED_TABLES
    assert Base.metadata.tables["auth.users"].info["external"] is True
    configure_mappers()


def test_chat_ownership_ordering_and_citation_links() -> None:
    assert foreign_keys("users") == {"id": ("auth.users.id", "CASCADE")}
    assert foreign_keys("chat_threads") == {"owner_id": ("users.id", "CASCADE")}
    assert foreign_keys("chat_messages") == {
        "thread_id": ("chat_threads.id", "CASCADE")
    }
    assert foreign_keys("message_citations") == {
        "message_id": ("chat_messages.id", "CASCADE"),
        "chunk_id": ("document_chunks.id", "RESTRICT"),
    }
    assert ("thread_id", "position") in unique_column_sets("chat_messages")
    assert ("message_id", "citation_index") in unique_column_sets("message_citations")
    assert ("message_id", "chunk_id") in unique_column_sets("message_citations")
    assert "ck_chat_messages_valid_role" in check_constraint_names("chat_messages")
    messages = Base.metadata.tables["chat_messages"]
    idempotency_index = next(
        index
        for index in messages.indexes
        if index.name == "uq_chat_messages_thread_client_message_id"
    )
    assert idempotency_index.unique is True
    assert str(idempotency_index.dialect_options["postgresql"]["where"]) == (
        "role = 'user' AND message_data ? 'clientMessageId'"
    )


def test_document_and_chunk_integrity() -> None:
    assert ("accession_number",) in unique_column_sets("source_documents")
    assert ("content_checksum",) in unique_column_sets("source_documents")
    assert foreign_keys("document_chunks") == {
        "document_id": ("source_documents.id", "CASCADE")
    }
    assert ("document_id", "chunk_index") in unique_column_sets("document_chunks")

    chunks = Base.metadata.tables["document_chunks"]
    assert chunks.c.embedding.type.dim == 1536
    assert chunks.c.search_vector.computed is not None
    assert chunks.c.document_id.nullable is False
    assert chunks.c.text.nullable is False
    assert chunks.c.display_table.nullable is True
    assert {index.name for index in chunks.indexes} == {
        "ix_document_chunks_embedding_hnsw",
        "ix_document_chunks_metadata_gin",
        "ix_document_chunks_search_vector_gin",
    }
