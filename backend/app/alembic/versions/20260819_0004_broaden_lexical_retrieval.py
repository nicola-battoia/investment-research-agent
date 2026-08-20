"""Broaden lexical recall while preserving strict-match preference.

Revision ID: 20260819_0004
Revises: 20260819_0003
Create Date: 2026-08-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0004"
down_revision: str | None = "20260819_0003"
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


def _lexical_function(*, broad: bool) -> str:
    parsed_query = (
        """
            SELECT
              websearch_to_tsquery(
                'english'::regconfig,
                p_query_text
              ) AS strict_query,
              websearch_to_tsquery(
                'english'::regconfig,
                regexp_replace(btrim(p_query_text), '\\s+', ' OR ', 'g')
              ) AS retrieval_query
        """
        if broad
        else """
            SELECT
              websearch_to_tsquery(
                'english'::regconfig,
                p_query_text
              ) AS strict_query,
              websearch_to_tsquery(
                'english'::regconfig,
                p_query_text
              ) AS retrieval_query
        """
    )
    return f"""
        CREATE OR REPLACE FUNCTION public.match_document_chunks_lexical(
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
            (
              CASE
                WHEN parsed.strict_query @@ chunk.search_vector THEN 1.0
                ELSE 0.0
              END
              + ts_rank_cd(
                  chunk.search_vector,
                  parsed.retrieval_query,
                  32
                )::double precision
            ) AS score
          FROM public.document_chunks AS chunk
          JOIN public.source_documents AS source ON source.id = chunk.document_id
          CROSS JOIN LATERAL (
            {parsed_query}
          ) AS parsed
          WHERE parsed.retrieval_query @@ chunk.search_vector
          {FILTER_SQL}
          ORDER BY score DESC, chunk.id
          LIMIT least(greatest(p_match_count, 0), 100)
        $$
    """


def upgrade() -> None:
    op.execute(_lexical_function(broad=True))


def downgrade() -> None:
    op.execute(_lexical_function(broad=False))
