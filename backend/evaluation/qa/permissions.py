"""Real database permission probes using temporary rows and unconditional rollback.

Run explicitly: python -m evaluation.qa.permissions --output <report.json>
The command exits nonzero when the desired integrity policy is violated.
"""

import argparse
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from evaluation.qa.storage import connection, write_report


def probe(conn, name: str, statement: str, params: tuple, *, allowed: bool) -> dict:
    conn.execute("SAVEPOINT qa_probe")
    sqlstate = None
    try:
        rows = conn.execute(statement, params).fetchall()
        actual = bool(rows)
    except psycopg.Error as error:
        sqlstate = error.sqlstate
        actual = False
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT qa_probe")
        conn.execute("RELEASE SAVEPOINT qa_probe")
    # A syntax error or broken fixture is not evidence of a secure rejection.
    valid_denial = sqlstate in (None, "42501", "P0002")
    return {
        "name": name,
        "expected_allowed": allowed,
        "actual_allowed": actual,
        "passed": actual == allowed and valid_denial,
        "sqlstate": sqlstate,
    }


def assume_role(conn, role: str, user_id: str = "") -> None:
    if role not in ("anon", "authenticated"):
        raise ValueError("Unsupported probe role")
    conn.execute("RESET ROLE")
    conn.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user_id,))
    conn.execute(f"SET LOCAL ROLE {role}")


def audit_permissions() -> list[dict]:
    with connection() as conn:
        try:
            identities = [uuid4(), uuid4()]
            threads = [uuid4(), uuid4()]
            messages = [uuid4(), uuid4()]
            citations = [uuid4(), uuid4()]
            rpc_thread = uuid4()
            chunk = conn.execute(
                "SELECT id FROM public.document_chunks ORDER BY id LIMIT 1"
            ).fetchone()
            if chunk is None:
                raise ValueError("Permission probes require an ingested corpus")
            for owner, thread, message, citation in zip(
                identities, threads, messages, citations, strict=True
            ):
                conn.execute(
                    "INSERT INTO auth.users (id,email) VALUES (%s,%s)",
                    (owner, f"qa-{owner}@example.invalid"),
                )
                conn.execute(
                    "INSERT INTO public.chat_threads (id,owner_id,title) VALUES (%s,%s,'QA temporary')",
                    (thread, owner),
                )
                conn.execute(
                    """INSERT INTO public.chat_messages (id,thread_id,position,role,content,message_data)
                    VALUES (%s,%s,0,'assistant','QA original',%s)""",
                    (
                        message,
                        thread,
                        Jsonb(
                            {
                                "answerStatus": "supported",
                                "parts": [{"type": "text", "text": "QA original"}],
                            }
                        ),
                    ),
                )
                conn.execute(
                    """INSERT INTO public.message_citations (id,message_id,chunk_id,citation_index,excerpt)
                    VALUES (%s,%s,%s,0,'QA original citation')""",
                    (citation, message, chunk["id"]),
                )
            conn.execute(
                "INSERT INTO public.chat_threads (id,owner_id,title) VALUES (%s,%s,'QA RPC')",
                (rpc_thread, identities[0]),
            )
            results = []
            assume_role(conn, "anon")
            results.append(
                probe(
                    conn,
                    "anonymous_cannot_read_chats",
                    "SELECT id FROM public.chat_threads WHERE id=%s",
                    (threads[0],),
                    allowed=False,
                )
            )
            for role in ("anon", "authenticated"):
                assume_role(conn, role, str(identities[0]))
                for table in ("datasets", "cases", "runs", "results"):
                    results.append(
                        probe(
                            conn,
                            f"{role}_cannot_read_qa_{table}",
                            f"SELECT count(*) FROM qa.{table}",
                            (),
                            allowed=False,
                        )
                    )
            for index in (0, 1):
                assume_role(conn, "authenticated", str(identities[index]))
                other = 1 - index
                results.append(
                    probe(
                        conn,
                        f"user_{index}_reads_own_thread",
                        "SELECT id FROM public.chat_threads WHERE id=%s",
                        (threads[index],),
                        allowed=True,
                    )
                )
                for table, ident in (
                    ("chat_threads", threads[other]),
                    ("chat_messages", messages[other]),
                    ("message_citations", citations[other]),
                ):
                    results.append(
                        probe(
                            conn,
                            f"user_{index}_cannot_read_other_{table}",
                            f"SELECT id FROM public.{table} WHERE id=%s",
                            (ident,),
                            allowed=False,
                        )
                    )
                    results.append(
                        probe(
                            conn,
                            f"user_{index}_cannot_delete_other_{table}",
                            f"DELETE FROM public.{table} WHERE id=%s RETURNING id",
                            (ident,),
                            allowed=False,
                        )
                    )
                results.append(
                    probe(
                        conn,
                        f"user_{index}_cannot_edit_other_message",
                        "UPDATE public.chat_messages SET content='QA forged' WHERE id=%s RETURNING id",
                        (messages[other],),
                        allowed=False,
                    )
                )
            assume_role(conn, "authenticated", str(identities[0]))
            results.append(
                probe(
                    conn,
                    "user_can_read_shared_corpus",
                    "SELECT id FROM public.document_chunks WHERE id=%s",
                    (chunk["id"],),
                    allowed=True,
                )
            )
            results.append(
                probe(
                    conn,
                    "user_cannot_edit_corpus",
                    "UPDATE public.document_chunks SET text='QA forged' WHERE id=%s RETURNING id",
                    (chunk["id"],),
                    allowed=False,
                )
            )
            results.append(
                probe(
                    conn,
                    "user_cannot_edit_own_assistant",
                    "UPDATE public.chat_messages SET content='QA forged',message_data=%s WHERE id=%s RETURNING id",
                    (
                        Jsonb(
                            {
                                "answerStatus": "supported",
                                "parts": [{"type": "text", "text": "QA forged"}],
                            }
                        ),
                        messages[0],
                    ),
                    allowed=False,
                )
            )
            results.append(
                probe(
                    conn,
                    "user_cannot_delete_own_assistant",
                    "DELETE FROM public.chat_messages WHERE id=%s RETURNING id",
                    (messages[0],),
                    allowed=False,
                )
            )
            results.append(
                probe(
                    conn,
                    "user_cannot_insert_own_assistant",
                    "INSERT INTO public.chat_messages (id,thread_id,position,role,content,message_data) VALUES (%s,%s,1,'assistant','QA forged','{}') RETURNING id",
                    (uuid4(), threads[0]),
                    allowed=False,
                )
            )
            results.append(
                probe(
                    conn,
                    "user_cannot_insert_own_citation",
                    """INSERT INTO public.message_citations
                    (id,message_id,chunk_id,citation_index,excerpt)
                    SELECT %s,%s,id,1,'QA fabricated excerpt' FROM public.document_chunks
                    WHERE id<>%s ORDER BY id LIMIT 1 RETURNING id""",
                    (uuid4(), messages[0], chunk["id"]),
                    allowed=False,
                )
            )
            results.append(
                probe(
                    conn,
                    "user_cannot_edit_own_citation",
                    "UPDATE public.message_citations SET excerpt='QA fabricated excerpt' WHERE id=%s RETURNING id",
                    (citations[0],),
                    allowed=False,
                )
            )
            results.append(
                probe(
                    conn,
                    "user_cannot_delete_own_citation",
                    "DELETE FROM public.message_citations WHERE id=%s RETURNING id",
                    (citations[0],),
                    allowed=False,
                )
            )
            results.append(
                probe(
                    conn,
                    "user_cannot_complete_fabricated_turn",
                    """
                SELECT * FROM public.complete_chat_turn(%s,%s,0,%s,'QA question',%s,%s,'QA forged assistant',%s,'{}','[]','QA')
            """,
                    (
                        rpc_thread,
                        identities[0],
                        uuid4(),
                        Jsonb({"clientMessageId": "qa-forgery"}),
                        uuid4(),
                        Jsonb({"answerStatus": "supported"}),
                    ),
                    allowed=False,
                )
            )
            for action, sql, params in (
                (
                    "insert",
                    "INSERT INTO public.chat_messages(id,thread_id,position,role,content) VALUES (%s,%s,2,'user','QA forged') RETURNING id",
                    (uuid4(), threads[0]),
                ),
                (
                    "change_role",
                    "UPDATE public.chat_messages SET role='user' WHERE id=%s RETURNING id",
                    (messages[0],),
                ),
            ):
                results.append(
                    probe(
                        conn,
                        f"user_cannot_{action}_saved_history",
                        sql,
                        params,
                        allowed=False,
                    )
                )
            results.append(
                probe(
                    conn,
                    "user_can_delete_own_thread",
                    "DELETE FROM public.chat_threads WHERE id=%s RETURNING id",
                    (threads[0],),
                    allowed=True,
                )
            )
            return results
        finally:
            conn.rollback()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = audit_permissions()
    report = {
        "scope": "PostgreSQL roles/RLS; not an HTTP/JWT test",
        "rolled_back": True,
        "passed": sum(c["passed"] for c in checks),
        "failed": sum(not c["passed"] for c in checks),
        "checks": checks,
    }
    write_report(args.output, report)
    print(
        f"Permissions: {report['passed']} passed, {report['failed']} failed; all fixture/probe writes rolled back"
    )
    for check in checks:
        if not check["passed"]:
            print("FAIL:", check["name"])
    raise SystemExit(1 if report["failed"] else 0)


if __name__ == "__main__":
    main()
