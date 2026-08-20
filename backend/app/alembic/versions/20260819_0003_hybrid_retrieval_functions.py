"""Add bounded semantic and lexical retrieval functions.

Revision ID: 20260819_0003
Revises: 20260817_0002
Create Date: 2026-08-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0003"
down_revision: str | None = "20260817_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEMANTIC_SIGNATURE = (
    "public.match_document_chunks_semantic("
    "vector,integer,text[],text[],text[],integer[],date,date)"
)
LEXICAL_SIGNATURE = (
    "public.match_document_chunks_lexical("
    "text,integer,text[],text[],text[],integer[],date,date)"
)

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


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION public.match_document_chunks_semantic(
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
        SET search_path = ''
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
    )
    op.execute(
        f"""
        CREATE FUNCTION public.match_document_chunks_lexical(
          p_query_text text,
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
        SET search_path = ''
        AS $$
          SELECT
            chunk.id AS chunk_id,
            ts_rank_cd(chunk.search_vector, parsed.query, 32)::double precision
              AS score
          FROM public.document_chunks AS chunk
          JOIN public.source_documents AS source ON source.id = chunk.document_id
          CROSS JOIN LATERAL (
            SELECT websearch_to_tsquery('english'::regconfig, p_query_text) AS query
          ) AS parsed
          WHERE parsed.query @@ chunk.search_vector
          {FILTER_SQL}
          ORDER BY
            ts_rank_cd(chunk.search_vector, parsed.query, 32) DESC,
            chunk.id
          LIMIT least(greatest(p_match_count, 0), 100)
        $$
        """
    )

    for signature in (SEMANTIC_SIGNATURE, LEXICAL_SIGNATURE):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC, anon")
        op.execute(
            f"GRANT EXECUTE ON FUNCTION {signature} TO authenticated, service_role"
        )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {LEXICAL_SIGNATURE}")
    op.execute(f"DROP FUNCTION IF EXISTS {SEMANTIC_SIGNATURE}")
