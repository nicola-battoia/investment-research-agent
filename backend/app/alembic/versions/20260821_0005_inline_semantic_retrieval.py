"""Allow the semantic retrieval function to use the HNSW query plan.

Revision ID: 20260821_0005
Revises: 20260819_0004
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0005"
down_revision: str | None = "20260819_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILTER_SQL = """
  AND (
    (
      cardinality(coalesce(p_companies, ARRAY[]::text[])) = 0
      AND cardinality(coalesce(p_tickers, ARRAY[]::text[])) = 0
    )
    OR lower(source.company) = ANY(coalesce(p_companies, ARRAY[]::text[]))
    OR upper(source.ticker) = ANY(coalesce(p_tickers, ARRAY[]::text[]))
  )
  AND (
    cardinality(coalesce(p_filing_types, ARRAY[]::text[])) = 0
    OR upper(source.filing_type) = ANY(p_filing_types)
  )
  AND (
    cardinality(coalesce(p_filing_years, ARRAY[]::integer[])) = 0
    OR extract(year FROM source.report_date)::integer = ANY(p_filing_years)
  )
  AND (p_filed_on_or_after IS NULL OR source.filing_date >= p_filed_on_or_after)
  AND (p_filed_on_or_before IS NULL OR source.filing_date <= p_filed_on_or_before)
"""


def _semantic_function(*, allow_inlining: bool) -> str:
    # PostgreSQL cannot inline a SQL function that has a SET clause. Inlining is
    # required here so the query planner can apply the HNSW index to the caller's
    # embedding instead of choosing a generic sequential plan.
    search_path = "" if allow_inlining else "SET search_path = ''"
    return f"""
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
        LANGUAGE sql
        STABLE
        SECURITY INVOKER
        {search_path}
        AS $$
          SELECT
            chunk.id AS chunk_id,
            1.0 - (
              chunk.embedding OPERATOR(public.<=>) p_query_embedding
            ) AS score
          FROM public.document_chunks AS chunk
          JOIN public.source_documents AS source ON source.id = chunk.document_id
          WHERE true
          {FILTER_SQL}
          ORDER BY
            chunk.embedding OPERATOR(public.<=>) p_query_embedding,
            chunk.id
          LIMIT least(greatest(p_match_count, 0), 100)
        $$
    """


def upgrade() -> None:
    op.execute(_semantic_function(allow_inlining=True))


def downgrade() -> None:
    op.execute(_semantic_function(allow_inlining=False))
