"""Operator-only immutability and privilege checks; no model calls."""

from uuid import uuid4

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.qa]


def test_qa_snapshots_are_private_and_immutable(pytestconfig):
    if not pytestconfig.getoption("--qa-live"):
        pytest.skip("Run explicitly with --qa-live against the intended database")
    from evaluation.qa.storage import connection

    with connection() as conn:
        try:
            for role in ("anon", "authenticated", "service_role"):
                row = conn.execute(
                    "SELECT has_schema_privilege(%s,'qa','USAGE') AS allowed", (role,)
                ).fetchone()
                assert not row["allowed"], role
            tables = conn.execute(
                "SELECT relname,relrowsecurity FROM pg_class JOIN pg_namespace ON relnamespace=pg_namespace.oid WHERE nspname='qa' AND relkind='r'"
            ).fetchall()
            assert {r["relname"] for r in tables} == {
                "datasets",
                "cases",
                "runs",
                "results",
            }
            assert all(r["relrowsecurity"] for r in tables)
            dataset_id, case_id = uuid4(), uuid4()
            conn.execute(
                "INSERT INTO qa.datasets (id,name,version,content_sha256,corpus_fingerprint,metadata) VALUES (%s,'qa-immutability',%s,%s,%s,'{}')",
                (dataset_id, str(uuid4()), "a" * 64, "b" * 64),
            )
            conn.execute(
                "INSERT INTO qa.cases (id,dataset_id,code,question,gold_answer,evidence_groups,rubric) VALUES (%s,%s,'QA','question','gold','[]','{}')",
                (case_id, dataset_id),
            )
            for table, ident in (("datasets", dataset_id), ("cases", case_id)):
                for query in (
                    f"UPDATE qa.{table} SET id=id WHERE id=%s",
                    f"DELETE FROM qa.{table} WHERE id=%s",
                ):
                    with (
                        pytest.raises(psycopg.errors.RaiseException),
                        conn.transaction(),
                    ):
                        conn.execute(query, (ident,))
                    assert conn.execute(
                        f"SELECT id FROM qa.{table} WHERE id=%s", (ident,)
                    ).fetchone()
        finally:
            conn.rollback()
