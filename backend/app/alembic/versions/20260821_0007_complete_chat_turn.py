"""Persist one validated chat turn atomically.

Revision ID: 20260821_0007
Revises: 20260821_0006
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0007"
down_revision: str | None = "20260821_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION_SIGNATURE = """public.complete_chat_turn(
  uuid, integer, uuid, text, jsonb, uuid, text, jsonb, jsonb, jsonb, text
)"""


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_chat_messages_thread_client_message_id
        ON public.chat_messages (
          thread_id,
          (message_data ->> 'clientMessageId')
        )
        WHERE role = 'user' AND message_data ? 'clientMessageId'
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.complete_chat_turn(
          p_thread_id uuid,
          p_expected_position integer,
          p_user_message_id uuid,
          p_user_content text,
          p_user_message_data jsonb,
          p_assistant_message_id uuid,
          p_assistant_content text,
          p_assistant_message_data jsonb,
          p_model_usage jsonb,
          p_citations jsonb,
          p_first_turn_title text
        )
        RETURNS TABLE (assistant_created_at timestamptz)
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = ''
        AS $$
        DECLARE
          v_owner_id uuid;
          v_next_position integer;
          v_assistant_created_at timestamptz;
        BEGIN
          IF p_expected_position < 0 THEN
            RAISE EXCEPTION 'Expected message position must be non-negative'
              USING ERRCODE = '22023';
          END IF;

          SELECT thread.owner_id
          INTO v_owner_id
          FROM public.chat_threads AS thread
          WHERE thread.id = p_thread_id
          FOR UPDATE;

          IF NOT FOUND THEN
            RAISE EXCEPTION 'Chat thread not found' USING ERRCODE = 'P0002';
          END IF;
          IF v_owner_id IS DISTINCT FROM (SELECT auth.uid()) THEN
            RAISE EXCEPTION 'Chat thread is not owned by the current user'
              USING ERRCODE = '42501';
          END IF;

          SELECT coalesce(max(message.position) + 1, 0)
          INTO v_next_position
          FROM public.chat_messages AS message
          WHERE message.thread_id = p_thread_id;

          IF v_next_position <> p_expected_position THEN
            RAISE EXCEPTION 'Chat message position changed during the turn'
              USING ERRCODE = '40001';
          END IF;

          INSERT INTO public.chat_messages (
            id,
            thread_id,
            position,
            role,
            content,
            message_data
          ) VALUES (
            p_user_message_id,
            p_thread_id,
            p_expected_position,
            'user',
            p_user_content,
            p_user_message_data
          );

          INSERT INTO public.chat_messages (
            id,
            thread_id,
            position,
            role,
            content,
            message_data,
            model_usage
          ) VALUES (
            p_assistant_message_id,
            p_thread_id,
            p_expected_position + 1,
            'assistant',
            p_assistant_content,
            p_assistant_message_data,
            p_model_usage
          )
          RETURNING created_at INTO v_assistant_created_at;

          IF jsonb_typeof(coalesce(p_citations, '[]'::jsonb)) <> 'array' THEN
            RAISE EXCEPTION 'Citations must be a JSON array' USING ERRCODE = '22023';
          END IF;

          INSERT INTO public.message_citations (
            id,
            message_id,
            chunk_id,
            citation_index,
            excerpt
          )
          SELECT
            citation.id,
            p_assistant_message_id,
            citation.chunk_id,
            citation.citation_index,
            citation.excerpt
          FROM jsonb_to_recordset(coalesce(p_citations, '[]'::jsonb)) AS citation(
            id uuid,
            chunk_id uuid,
            citation_index integer,
            excerpt text
          );

          UPDATE public.chat_threads
          SET
            title = CASE
              WHEN p_expected_position = 0 AND title = 'New chat'
                THEN left(p_first_turn_title, 200)
              ELSE title
            END,
            updated_at = clock_timestamp()
          WHERE id = p_thread_id;

          RETURN QUERY SELECT v_assistant_created_at;
        END
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC, anon")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE} TO authenticated, service_role"
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_SIGNATURE}")
    op.drop_index(
        "uq_chat_messages_thread_client_message_id",
        table_name="chat_messages",
    )
