"""Transactional verification of the complete-turn PostgreSQL contract."""

from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.config import settings

pytestmark = pytest.mark.integration

FUNCTION_REGPROCEDURE = (
    "public.complete_chat_turn(uuid,integer,uuid,text,jsonb,uuid,text,jsonb,"
    "jsonb,jsonb,text)"
)
CALL_COMPLETE_TURN = """
    SELECT assistant_created_at
    FROM public.complete_chat_turn(
      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
"""


def test_complete_turn_function_is_atomic_rls_aware_and_idempotent() -> None:
    connection = psycopg.connect(_database_url())
    try:
        with connection.cursor() as cursor:
            owner_id = _existing_owner(cursor)
            chunk_id = _existing_chunk(cursor)
            _assert_function_security(cursor)

            thread_id = _insert_thread(cursor, owner_id)
            cursor.execute(
                "SELECT set_config('request.jwt.claim.sub', %s, true)",
                (str(owner_id),),
            )
            cursor.execute("SET LOCAL ROLE authenticated")

            user_message_id = uuid4()
            assistant_message_id = uuid4()
            citation_id = uuid4()
            citation_payload = (
                [
                    {
                        "id": str(citation_id),
                        "chunk_id": str(chunk_id),
                        "citation_index": 0,
                        "excerpt": "A transactionally persisted exact filing excerpt.",
                    }
                ]
                if chunk_id is not None
                else []
            )
            _complete_turn(
                cursor,
                thread_id=thread_id,
                expected_position=0,
                client_message_id="live-database-turn",
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                citations=citation_payload,
                title="First filing question",
            )

            cursor.execute(
                """
                SELECT position, role, message_data, model_usage
                FROM public.chat_messages
                WHERE thread_id = %s
                ORDER BY position
                """,
                (thread_id,),
            )
            messages = cursor.fetchall()
            assert [(row[0], row[1]) for row in messages] == [
                (0, "user"),
                (1, "assistant"),
            ]
            assert messages[0][2]["clientMessageId"] == "live-database-turn"
            assert messages[1][2]["answerStatus"] == "supported"
            assert messages[1][3]["totalTokens"] == 13

            cursor.execute(
                "SELECT title FROM public.chat_threads WHERE id = %s",
                (thread_id,),
            )
            assert cursor.fetchone()[0] == "First filing question"
            if chunk_id is not None:
                cursor.execute(
                    """
                    SELECT id, chunk_id, citation_index, excerpt
                    FROM public.message_citations
                    WHERE message_id = %s
                    """,
                    (assistant_message_id,),
                )
                assert cursor.fetchone() == (
                    citation_id,
                    chunk_id,
                    0,
                    "A transactionally persisted exact filing excerpt.",
                )

            _assert_rejected_call_rolls_back(
                cursor,
                thread_id=thread_id,
                expected_position=2,
                client_message_id="live-database-turn",
                expected_sqlstate="23505",
            )
            _assert_rejected_call_rolls_back(
                cursor,
                thread_id=thread_id,
                expected_position=0,
                client_message_id="position-conflict",
                expected_sqlstate="40001",
            )

            rollback_thread_id = _insert_thread(cursor, owner_id)
            _assert_invalid_citations_roll_back(cursor, rollback_thread_id)
            _assert_other_user_cannot_complete(cursor, thread_id, owner_id)
    finally:
        connection.rollback()
        connection.close()


def _database_url() -> str:
    return settings.database_url.get_secret_value().replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )


def _existing_owner(cursor: psycopg.Cursor) -> UUID:
    cursor.execute(
        """
        SELECT auth_user.id
        FROM auth.users AS auth_user
        JOIN public.users AS app_user ON app_user.id = auth_user.id
        ORDER BY auth_user.created_at
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if row is None:
        pytest.skip("The configured Supabase project has no application user")
    return row[0]


def _existing_chunk(cursor: psycopg.Cursor) -> UUID | None:
    cursor.execute("SELECT id FROM public.document_chunks ORDER BY id LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row is not None else None


def _assert_function_security(cursor: psycopg.Cursor) -> None:
    cursor.execute(
        """
        SELECT
          has_function_privilege('authenticated', %s, 'EXECUTE'),
          has_function_privilege('anon', %s, 'EXECUTE')
        """,
        (FUNCTION_REGPROCEDURE, FUNCTION_REGPROCEDURE),
    )
    assert cursor.fetchone() == (True, False)
    cursor.execute(
        """
        SELECT relname, relrowsecurity
        FROM pg_catalog.pg_class
        WHERE relnamespace = 'public'::regnamespace
          AND relname IN ('chat_threads', 'chat_messages', 'message_citations')
        ORDER BY relname
        """
    )
    assert cursor.fetchall() == [
        ("chat_messages", True),
        ("chat_threads", True),
        ("message_citations", True),
    ]


def _insert_thread(cursor: psycopg.Cursor, owner_id: UUID) -> UUID:
    thread_id = uuid4()
    cursor.execute(
        """
        INSERT INTO public.chat_threads (id, owner_id, title)
        VALUES (%s, %s, 'New chat')
        """,
        (thread_id, owner_id),
    )
    return thread_id


def _complete_turn(
    cursor: psycopg.Cursor,
    *,
    thread_id: UUID,
    expected_position: int,
    client_message_id: str,
    user_message_id: UUID,
    assistant_message_id: UUID,
    citations: list[dict[str, object]],
    title: str,
) -> None:
    cursor.execute(
        CALL_COMPLETE_TURN,
        (
            thread_id,
            expected_position,
            user_message_id,
            "First filing question",
            Jsonb(
                {
                    "clientMessageId": client_message_id,
                    "parts": [{"type": "text", "text": "First filing question"}],
                }
            ),
            assistant_message_id,
            "Supported answer [S1].",
            Jsonb(
                {
                    "answerStatus": "supported",
                    "parts": [{"type": "text", "text": "Supported answer [S1]."}],
                }
            ),
            Jsonb({"inputTokens": 10, "outputTokens": 3, "totalTokens": 13}),
            Jsonb(citations),
            title,
        ),
    )
    assert cursor.fetchone()[0] is not None


def _assert_rejected_call_rolls_back(
    cursor: psycopg.Cursor,
    *,
    thread_id: UUID,
    expected_position: int,
    client_message_id: str,
    expected_sqlstate: str,
) -> None:
    cursor.execute("SAVEPOINT rejected_turn")
    with pytest.raises(psycopg.Error) as caught:
        _complete_turn(
            cursor,
            thread_id=thread_id,
            expected_position=expected_position,
            client_message_id=client_message_id,
            user_message_id=uuid4(),
            assistant_message_id=uuid4(),
            citations=[],
            title="Must not replace the title",
        )
    assert caught.value.sqlstate == expected_sqlstate
    cursor.execute("ROLLBACK TO SAVEPOINT rejected_turn")
    cursor.execute(
        "SELECT count(*) FROM public.chat_messages WHERE thread_id = %s",
        (thread_id,),
    )
    assert cursor.fetchone()[0] == 2


def _assert_invalid_citations_roll_back(
    cursor: psycopg.Cursor,
    thread_id: UUID,
) -> None:
    cursor.execute("SAVEPOINT invalid_citations")
    with pytest.raises(psycopg.Error) as caught:
        cursor.execute(
            CALL_COMPLETE_TURN,
            (
                thread_id,
                0,
                uuid4(),
                "Question",
                Jsonb({"clientMessageId": "invalid-citations"}),
                uuid4(),
                "Answer",
                Jsonb({"answerStatus": "supported"}),
                Jsonb({}),
                Jsonb({"not": "an array"}),
                "Must not be saved",
            ),
        )
    assert caught.value.sqlstate == "22023"
    cursor.execute("ROLLBACK TO SAVEPOINT invalid_citations")
    cursor.execute(
        """
        SELECT
          (SELECT count(*) FROM public.chat_messages WHERE thread_id = %s),
          (SELECT title FROM public.chat_threads WHERE id = %s)
        """,
        (thread_id, thread_id),
    )
    assert cursor.fetchone() == (0, "New chat")


def _assert_other_user_cannot_complete(
    cursor: psycopg.Cursor,
    thread_id: UUID,
    owner_id: UUID,
) -> None:
    cursor.execute("SAVEPOINT forbidden_turn")
    cursor.execute(
        "SELECT set_config('request.jwt.claim.sub', %s, true)",
        (str(uuid4()),),
    )
    with pytest.raises(psycopg.Error) as caught:
        _complete_turn(
            cursor,
            thread_id=thread_id,
            expected_position=2,
            client_message_id="forbidden-turn",
            user_message_id=uuid4(),
            assistant_message_id=uuid4(),
            citations=[],
            title="Must not be saved",
        )
    assert caught.value.sqlstate == "P0002"
    cursor.execute("ROLLBACK TO SAVEPOINT forbidden_turn")
    cursor.execute(
        "SELECT set_config('request.jwt.claim.sub', %s, true)",
        (str(owner_id),),
    )
