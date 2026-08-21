"""Use a per-query plan for semantic retrieval through PostgREST.

Revision ID: 20260821_0006
Revises: 20260821_0005
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0006"
down_revision: str | None = "20260821_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILTER_SQL = """
  AND (
    (
      cardinality(coalesce($3, ARRAY[]::text[])) = 0
      AND cardinality(coalesce($4, ARRAY[]::text[])) = 0
    )
    OR lower(source.company) = ANY(coalesce($3, ARRAY[]::text[]))
    OR upper(source.ticker) = ANY(coalesce($4, ARRAY[]::text[]))
  )
  AND (
    cardinality(coalesce($5, ARRAY[]::text[])) = 0
    OR upper(source.filing_type) = ANY($5)
  )
  AND (
    cardinality(coalesce($6, ARRAY[]::integer[])) = 0
    OR extract(year FROM source.report_date)::integer = ANY($6)
  )
  AND ($7::date IS NULL OR source.filing_date >= $7)
  AND ($8::date IS NULL OR source.filing_date <= $8)
"""


def upgrade() -> None:
    # PostgREST reuses prepared RPC statements. EXECUTE gives each embedding a
    # custom inner plan so pgvector can choose the cosine HNSW index reliably.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.match_document_chunks_semantic(
          p_query_embedding vector(1536),
          p_match_count integer,
          p_companies text[],
          p_tickers text[],
          p_filing_types text[],
          p_filing_years integer[],
          p_filed_on_or_after date,
          p_filed_on_or_before date
        )
        RETURNS TABLE (chunk_id uuid, score double precision)
        LANGUAGE plpgsql
        STABLE
        SECURITY INVOKER
        SET search_path = ''
        AS $$
        BEGIN
          RETURN QUERY EXECUTE $query$
            SELECT
              chunk.id AS chunk_id,
              1.0 - (chunk.embedding OPERATOR(public.<=>) $1) AS score
            FROM public.document_chunks AS chunk
            JOIN public.source_documents AS source ON source.id = chunk.document_id
            WHERE true
            {FILTER_SQL}
            ORDER BY chunk.embedding OPERATOR(public.<=>) $1, chunk.id
            LIMIT least(greatest($2, 0), 100)
          $query$
          USING
            p_query_embedding,
            p_match_count,
            p_companies,
            p_tickers,
            p_filing_types,
            p_filing_years,
            p_filed_on_or_after,
            p_filed_on_or_before;
        END
        $$
        """
    )


def downgrade() -> None:
    from importlib import import_module

    previous = import_module(
        "app.alembic.versions.20260821_0005_inline_semantic_retrieval"
    )
    op.execute(previous._semantic_function(allow_inlining=True))
