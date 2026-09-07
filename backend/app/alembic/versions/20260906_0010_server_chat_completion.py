"""Add server-only completion before deploying the backend that calls it.

The next migration removes the old RPC and browser write privileges after
all backend instances have switched to this function signature.
"""

from alembic import op

revision = "20260906_0010"
down_revision = "20260905_0009"
branch_labels = None
depends_on = None

FUNCTION_SIGNATURE = (
    "public.complete_chat_turn(uuid,uuid,integer,uuid,text,jsonb,uuid,text,"
    "jsonb,jsonb,jsonb,text)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("""
        CREATE FUNCTION public.complete_chat_turn(
          p_thread_id uuid,
          p_owner_id uuid,
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
          IF p_expected_position IS NULL OR p_expected_position < 0
             OR p_expected_position % 2 <> 0 THEN
            RAISE EXCEPTION 'Expected message position must be non-negative and even'
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
          IF v_owner_id IS DISTINCT FROM p_owner_id THEN
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
        """)
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC, anon, authenticated"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE} TO service_role")
    op.execute("NOTIFY pgrst, 'reload schema'")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {FUNCTION_SIGNATURE}")
    op.execute("NOTIFY pgrst, 'reload schema'")
