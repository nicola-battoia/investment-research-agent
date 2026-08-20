import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_initial_migration_renders_expected_offline_sql() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    sql = result.stdout
    expected_sql = (
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE TABLE users",
        "FOREIGN KEY(id) REFERENCES auth.users",
        "CREATE TABLE document_chunks",
        "embedding VECTOR(1536)",
        "search_vector TSVECTOR GENERATED ALWAYS AS",
        "CONSTRAINT ck_document_chunks_non_negative_chunk_index",
        "CONSTRAINT ck_chat_messages_valid_role",
        "CONSTRAINT ck_message_citations_non_negative_citation_index",
        "CREATE INDEX ix_document_chunks_embedding_hnsw",
        "CREATE INDEX ix_document_chunks_search_vector_gin",
        "CREATE INDEX ix_document_chunks_metadata_gin",
        "ENABLE ROW LEVEL SECURITY",
        "CREATE POLICY users_select_own",
        "CREATE POLICY chat_threads_select_own",
        "CREATE POLICY chat_messages_select_own",
        "CREATE POLICY message_citations_select_own",
        "CREATE POLICY source_documents_select_authenticated",
        "CREATE POLICY document_chunks_select_authenticated",
        "CREATE FUNCTION public.create_document_copilot_user()",
        "CREATE TRIGGER document_copilot_auth_user_created",
        (
            "REVOKE ALL PRIVILEGES ON TABLE public.users, public.chat_threads, "
            "public.chat_messages, public.message_citations, "
            "public.source_documents, public.document_chunks FROM authenticated"
        ),
        "GRANT SELECT, UPDATE ON TABLE public.users TO authenticated",
        (
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_threads, "
            "public.chat_messages, public.message_citations TO authenticated"
        ),
        (
            "GRANT SELECT ON TABLE public.source_documents, "
            "public.document_chunks TO authenticated"
        ),
        "CREATE FUNCTION public.match_document_chunks_semantic",
        "p_query_embedding vector(1536)",
        "chunk.embedding OPERATOR(public.<=>) p_query_embedding",
        "CREATE FUNCTION public.match_document_chunks_lexical",
        "websearch_to_tsquery('english'::regconfig, p_query_text)",
        "ts_rank_cd(chunk.search_vector, parsed.query, 32)",
        "regexp_replace(btrim(p_query_text), '\\s+', ' OR ', 'g')",
        "parsed.strict_query @@ chunk.search_vector",
        "parsed.retrieval_query @@ chunk.search_vector",
        "SECURITY INVOKER",
        "least(greatest(p_match_count, 0), 100)",
        "extract(year FROM source.report_date)::integer = ANY(p_filing_years)",
        ("GRANT EXECUTE ON FUNCTION public.match_document_chunks_semantic"),
        ("GRANT EXECUTE ON FUNCTION public.match_document_chunks_lexical"),
        ("REVOKE ALL ON FUNCTION public.match_document_chunks_semantic"),
        ("REVOKE ALL ON FUNCTION public.match_document_chunks_lexical"),
    )
    for statement in expected_sql:
        assert statement in sql


def test_grant_correction_migration_renders_expected_downgrade_sql() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "downgrade",
            "20260817_0002:20260817_0001",
            "--sql",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "GRANT ALL PRIVILEGES ON TABLE public.users, public.chat_threads, "
        "public.chat_messages, public.message_citations, "
        "public.source_documents, public.document_chunks TO authenticated"
    ) in result.stdout
