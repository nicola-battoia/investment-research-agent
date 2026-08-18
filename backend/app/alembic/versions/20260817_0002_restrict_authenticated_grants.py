"""Restrict authenticated table grants to the application API surface.

Revision ID: 20260817_0002
Revises: 20260817_0001
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260817_0002"
down_revision: str | None = "20260817_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "public.users",
    "public.chat_threads",
    "public.chat_messages",
    "public.message_citations",
    "public.source_documents",
    "public.document_chunks",
)


def upgrade() -> None:
    table_list = ", ".join(TABLES)

    # Supabase grants broad privileges on new public tables by default.
    op.execute(f"REVOKE ALL PRIVILEGES ON TABLE {table_list} FROM authenticated")
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


def downgrade() -> None:
    table_list = ", ".join(TABLES)
    op.execute(f"GRANT ALL PRIVILEGES ON TABLE {table_list} TO authenticated")
