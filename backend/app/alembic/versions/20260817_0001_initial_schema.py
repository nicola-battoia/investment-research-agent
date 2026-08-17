"""Create the initial Document Copilot schema.

Revision ID: 20260817_0001
Revises:
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260817_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["auth.users.id"],
            name="fk_users_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )

    op.create_table(
        "source_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("filing_type", sa.String(length=16), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("sec_url", sa.Text(), nullable=False),
        sa.Column("normalized_markdown", sa.Text(), nullable=False),
        sa.Column(
            "extraction_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_documents"),
        sa.UniqueConstraint(
            "accession_number",
            name="uq_source_documents_accession_number",
        ),
        sa.UniqueConstraint(
            "content_checksum",
            name="uq_source_documents_content_checksum",
        ),
    )
    op.create_index(
        "ix_source_documents_ticker_report_date",
        "source_documents",
        ["ticker", "report_date"],
    )

    op.create_table(
        "chat_threads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_chat_threads_owner_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_threads"),
    )
    op.create_index(
        "ix_chat_threads_owner_updated_at",
        "chat_threads",
        ["owner_id", "updated_at"],
    )

    op.create_table(
        "document_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=True),
        sa.Column("source_end", sa.Integer(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english'::regconfig, coalesce(text, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name=op.f("ck_document_chunks_non_negative_chunk_index"),
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name=op.f("ck_document_chunks_positive_page_number"),
        ),
        sa.CheckConstraint(
            "token_count > 0",
            name=op.f("ck_document_chunks_positive_token_count"),
        ),
        sa.CheckConstraint(
            "(source_start IS NULL AND source_end IS NULL) OR "
            "(source_start >= 0 AND source_end > source_start)",
            name=op.f("ck_document_chunks_valid_source_offsets"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.id"],
            name="fk_document_chunks_document_id_source_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_index",
        ),
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_document_chunks_search_vector_gin",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_document_chunks_metadata_gin",
        "document_chunks",
        ["metadata"],
        postgresql_using="gin",
    )

    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "message_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "model_usage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_chat_messages_non_negative_position"),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name=op.f("ck_chat_messages_valid_role"),
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["chat_threads.id"],
            name="fk_chat_messages_thread_id_chat_threads",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
        sa.UniqueConstraint(
            "thread_id",
            "position",
            name="uq_chat_messages_thread_position",
        ),
    )
    op.create_index(
        "ix_chat_messages_thread_created_at",
        "chat_messages",
        ["thread_id", "created_at"],
    )

    op.create_table(
        "message_citations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_index", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "citation_index >= 0",
            name=op.f("ck_message_citations_non_negative_citation_index"),
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name="fk_message_citations_chunk_id_document_chunks",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            name="fk_message_citations_message_id_chat_messages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_citations"),
        sa.UniqueConstraint(
            "message_id",
            "chunk_id",
            name="uq_message_citations_message_chunk",
        ),
        sa.UniqueConstraint(
            "message_id",
            "citation_index",
            name="uq_message_citations_message_index",
        ),
    )

    op.execute(
        """
        CREATE FUNCTION public.create_document_copilot_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        BEGIN
          INSERT INTO public.users (id)
          VALUES (NEW.id)
          ON CONFLICT (id) DO NOTHING;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_copilot_auth_user_created
        AFTER INSERT ON auth.users
        FOR EACH ROW EXECUTE FUNCTION public.create_document_copilot_user()
        """
    )
    op.execute(
        """
        INSERT INTO public.users (id)
        SELECT id FROM auth.users
        ON CONFLICT (id) DO NOTHING
        """
    )

    for table_name in (
        "users",
        "chat_threads",
        "chat_messages",
        "message_citations",
        "source_documents",
        "document_chunks",
    ):
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")

    _create_rls_policies()
    _grant_table_access()


def _create_rls_policies() -> None:
    user_owns_record = "(SELECT auth.uid()) = id"
    user_owns_thread = "(SELECT auth.uid()) = owner_id"
    user_owns_message = """
        EXISTS (
          SELECT 1
          FROM public.chat_threads AS thread
          WHERE thread.id = chat_messages.thread_id
            AND thread.owner_id = (SELECT auth.uid())
        )
    """
    user_owns_citation = """
        EXISTS (
          SELECT 1
          FROM public.chat_messages AS message
          JOIN public.chat_threads AS thread ON thread.id = message.thread_id
          WHERE message.id = message_citations.message_id
            AND thread.owner_id = (SELECT auth.uid())
        )
    """

    op.execute(
        f"CREATE POLICY users_select_own ON public.users "
        f"FOR SELECT TO authenticated USING ({user_owns_record})"
    )
    op.execute(
        f"CREATE POLICY users_update_own ON public.users "
        f"FOR UPDATE TO authenticated USING ({user_owns_record}) "
        f"WITH CHECK ({user_owns_record})"
    )
    _create_owned_table_policies("chat_threads", user_owns_thread)
    _create_owned_table_policies("chat_messages", user_owns_message)
    _create_owned_table_policies("message_citations", user_owns_citation)
    op.execute(
        "CREATE POLICY source_documents_select_authenticated "
        "ON public.source_documents FOR SELECT TO authenticated USING (true)"
    )
    op.execute(
        "CREATE POLICY document_chunks_select_authenticated "
        "ON public.document_chunks FOR SELECT TO authenticated USING (true)"
    )


def _create_owned_table_policies(table_name: str, ownership_check: str) -> None:
    op.execute(
        f"CREATE POLICY {table_name}_select_own ON public.{table_name} "
        f"FOR SELECT TO authenticated USING ({ownership_check})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_insert_own ON public.{table_name} "
        f"FOR INSERT TO authenticated WITH CHECK ({ownership_check})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_update_own ON public.{table_name} "
        f"FOR UPDATE TO authenticated USING ({ownership_check}) "
        f"WITH CHECK ({ownership_check})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_delete_own ON public.{table_name} "
        f"FOR DELETE TO authenticated USING ({ownership_check})"
    )


def _grant_table_access() -> None:
    tables = (
        "public.users",
        "public.chat_threads",
        "public.chat_messages",
        "public.message_citations",
        "public.source_documents",
        "public.document_chunks",
    )
    table_list = ", ".join(tables)
    op.execute("GRANT USAGE ON SCHEMA public TO authenticated, service_role")
    op.execute(f"REVOKE ALL ON TABLE {table_list} FROM PUBLIC, anon")
    op.execute("GRANT SELECT, UPDATE ON TABLE public.users TO authenticated")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
        "public.chat_threads, public.chat_messages, public.message_citations "
        "TO authenticated"
    )
    op.execute(
        "GRANT SELECT ON TABLE public.source_documents, public.document_chunks "
        "TO authenticated"
    )
    op.execute(f"GRANT ALL PRIVILEGES ON TABLE {table_list} TO service_role")


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS document_copilot_auth_user_created ON auth.users"
    )
    op.execute("DROP FUNCTION IF EXISTS public.create_document_copilot_user()")

    op.drop_table("message_citations")
    op.drop_index("ix_chat_messages_thread_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_document_chunks_metadata_gin", table_name="document_chunks")
    op.drop_index(
        "ix_document_chunks_search_vector_gin",
        table_name="document_chunks",
    )
    op.drop_index(
        "ix_document_chunks_embedding_hnsw",
        table_name="document_chunks",
        postgresql_using="hnsw",
    )
    op.drop_table("document_chunks")
    op.drop_index("ix_chat_threads_owner_updated_at", table_name="chat_threads")
    op.drop_table("chat_threads")
    op.drop_index(
        "ix_source_documents_ticker_report_date",
        table_name="source_documents",
    )
    op.drop_table("source_documents")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
