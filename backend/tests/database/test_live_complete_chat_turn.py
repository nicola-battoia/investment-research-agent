"""Transactional checks for server-only completion, including migration rehearsal."""

from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.config import settings

pytestmark = pytest.mark.integration
FUNCTION = "public.complete_chat_turn(uuid,uuid,integer,uuid,text,jsonb,uuid,text,jsonb,jsonb,jsonb,text)"
OLD_FUNCTION = "public.complete_chat_turn(uuid,integer,uuid,text,jsonb,uuid,text,jsonb,jsonb,jsonb,text)"
CALL = "SELECT * FROM public.complete_chat_turn(" + ",".join(["%s"] * 12) + ")"


def verify_completion_contract(conn) -> None:
    with conn.cursor() as cur:
        owners = [uuid4(), uuid4()]
        for owner in owners:
            cur.execute(
                "INSERT INTO auth.users(id,email) VALUES (%s,%s)",
                (owner, f"qa-{owner}@example.invalid"),
            )
        thread, empty = uuid4(), uuid4()
        for ident in (thread, empty):
            cur.execute(
                "INSERT INTO public.chat_threads(id,owner_id,title) VALUES (%s,%s,'New chat')",
                (ident, owners[0]),
            )
        cur.execute("SELECT id FROM public.document_chunks ORDER BY id LIMIT 1")
        chunk = cur.fetchone()[0]
        cur.execute(
            "SELECT has_function_privilege('authenticated',%s,'EXECUTE'), has_function_privilege('anon',%s,'EXECUTE'), has_function_privilege('service_role',%s,'EXECUTE'), to_regprocedure(%s)",
            (FUNCTION, FUNCTION, FUNCTION, OLD_FUNCTION),
        )
        assert cur.fetchone() == (False, False, True, None)
        cur.execute(
            "SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (FUNCTION,)
        )
        assert cur.fetchone() == (False,)

        def payload(**changes):
            values = {
                "thread": thread,
                "owner": owners[0],
                "position": 0,
                "user_id": uuid4(),
                "question": "QA question",
                "user_data": Jsonb({"clientMessageId": "qa-first"}),
                "assistant_id": uuid4(),
                "answer": "QA server answer",
                "assistant_data": Jsonb({"answerStatus": "supported"}),
                "usage": Jsonb({"totalTokens": 13}),
                "citations": Jsonb(
                    [
                        {
                            "id": str(uuid4()),
                            "chunk_id": str(chunk),
                            "citation_index": 0,
                            "excerpt": "QA server-supplied excerpt",
                        }
                    ]
                ),
                "title": "QA completed",
            }
            values.update(changes)
            return tuple(values.values())

        def rejected(params, code):
            cur.execute("SAVEPOINT rejected_call")
            with pytest.raises(psycopg.Error) as caught:
                cur.execute(CALL, params)
            assert caught.value.sqlstate == code
            cur.execute("ROLLBACK TO SAVEPOINT rejected_call")
            cur.execute("RELEASE SAVEPOINT rejected_call")

        for role in ("authenticated", "anon"):
            cur.execute(f"SET LOCAL ROLE {role}")
            cur.execute(
                "SELECT set_config('request.jwt.claim.sub',%s,true)", (str(owners[0]),)
            )
            rejected(payload(), "42501")
            cur.execute("RESET ROLE")
        cur.execute("SET LOCAL ROLE service_role")
        # The server token has no browser auth.uid(); ownership is explicit.
        cur.execute("SELECT set_config('request.jwt.claim.sub','',true)")
        rejected(payload(owner=owners[1]), "42501")
        rejected(payload(owner=None), "42501")
        rejected(payload(thread=uuid4()), "P0002")
        for position in (1, -1, None):
            rejected(payload(position=position), "22023")
        first = payload()
        cur.execute(CALL, first)
        assert cur.fetchone()[0] is not None
        rejected(payload(position=0), "40001")
        rejected(payload(position=2), "23505")  # Duplicate client message ID.
        rejected(payload(thread=empty, citations=Jsonb({})), "22023")
        rejected(
            payload(
                thread=empty,
                citations=Jsonb(
                    [
                        {
                            "id": str(uuid4()),
                            "chunk_id": str(uuid4()),
                            "citation_index": 0,
                            "excerpt": "Missing source",
                        }
                    ]
                ),
            ),
            "23503",
        )
        rejected(payload(thread=empty, owner=owners[1]), "42501")
        cur.execute(
            "SELECT count(*) FROM public.chat_messages WHERE thread_id=%s", (thread,)
        )
        assert cur.fetchone() == (2,)
        cur.execute(
            "SELECT model_usage FROM public.chat_messages WHERE id=%s", (first[6],)
        )
        assert cur.fetchone()[0] == {"totalTokens": 13}
        cur.execute(
            "SELECT count(*) FROM public.message_citations WHERE message_id=%s",
            (first[6],),
        )
        assert cur.fetchone() == (1,)
        cur.execute("SELECT title FROM public.chat_threads WHERE id=%s", (empty,))
        assert cur.fetchone() == ("New chat",)
        cur.execute(
            "SELECT count(*) FROM public.chat_messages WHERE thread_id=%s", (empty,)
        )
        assert cur.fetchone() == (0,)
        # Deletion between preparation and completion cannot recreate the chat.
        cur.execute("DELETE FROM public.chat_threads WHERE id=%s", (empty,))
        rejected(payload(thread=empty), "P0002")
        cur.execute("RESET ROLE")
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute(
            "SELECT set_config('request.jwt.claim.sub',%s,true)", (str(owners[0]),)
        )
        cur.execute(
            "DELETE FROM public.chat_threads WHERE id=%s RETURNING id", (thread,)
        )
        assert cur.fetchone() == (thread,)
        cur.execute("RESET ROLE")
        cur.execute(
            "SELECT count(*) FROM public.chat_messages WHERE thread_id=%s", (thread,)
        )
        assert cur.fetchone() == (0,)
        cur.execute(
            "SELECT count(*) FROM public.message_citations WHERE message_id=%s",
            (first[6],),
        )
        assert cur.fetchone() == (0,)


def test_server_only_completion_contract() -> None:
    url = settings.database_url.get_secret_value().replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(
        url, options="-c lock_timeout=5000 -c statement_timeout=30000"
    ) as conn:
        try:
            verify_completion_contract(conn)
        finally:
            conn.rollback()
