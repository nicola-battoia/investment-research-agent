"""User-scoped chat thread and message persistence."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from postgrest import APIError
from supabase import AsyncClient

from app.chat.messages import InternalUserMessage

THREAD_COLUMNS = "id,title,created_at,updated_at"
MESSAGE_COLUMNS = "id,thread_id,position,role,content,message_data,created_at"
CITATION_COLUMNS = "id,message_id,chunk_id,citation_index,excerpt"


class ChatThreadNotFoundError(Exception):
    """The requested chat thread does not exist."""


class ChatThreadForbiddenError(Exception):
    """The requested chat thread belongs to another user."""


class ChatPositionConflictError(Exception):
    """Two turns attempted to claim the same message positions."""


@dataclass(frozen=True)
class TurnPersistenceResult:
    assistant_created_at: datetime


async def list_threads(
    client: AsyncClient,
    user_id: UUID,
) -> list[dict[str, object]]:
    response = await (
        client.table("chat_threads")
        .select(THREAD_COLUMNS)
        .eq("owner_id", str(user_id))
        .order("updated_at", desc=True)
        .execute()
    )
    return response.data


async def create_thread(
    client: AsyncClient,
    user_id: UUID,
    title: str,
) -> dict[str, object]:
    response = await (
        client.table("chat_threads")
        .insert({"owner_id": str(user_id), "title": title})
        .execute()
    )
    return response.data[0]


async def require_owned_thread(
    client: AsyncClient,
    admin: AsyncClient,
    thread_id: UUID,
    user_id: UUID,
) -> dict[str, object]:
    response = await (
        client.table("chat_threads")
        .select(THREAD_COLUMNS)
        .eq("id", str(thread_id))
        .eq("owner_id", str(user_id))
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]

    existence = await (
        admin.table("chat_threads")
        .select("owner_id")
        .eq("id", str(thread_id))
        .limit(1)
        .execute()
    )
    if not existence.data:
        raise ChatThreadNotFoundError
    raise ChatThreadForbiddenError


async def load_thread(
    client: AsyncClient,
    admin: AsyncClient,
    thread_id: UUID,
    user_id: UUID,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    thread = await require_owned_thread(client, admin, thread_id, user_id)
    message_response = await (
        client.table("chat_messages")
        .select(MESSAGE_COLUMNS)
        .eq("thread_id", str(thread_id))
        .order("position")
        .execute()
    )
    messages = message_response.data
    if not messages:
        return thread, [], []

    citation_response = await (
        client.table("message_citations")
        .select(CITATION_COLUMNS)
        .in_("message_id", [str(message["id"]) for message in messages])
        .order("citation_index")
        .execute()
    )
    return thread, messages, citation_response.data


async def rename_thread(
    client: AsyncClient,
    admin: AsyncClient,
    thread_id: UUID,
    user_id: UUID,
    title: str,
) -> dict[str, object]:
    await require_owned_thread(client, admin, thread_id, user_id)
    response = await (
        client.table("chat_threads")
        .update({"title": title, "updated_at": _now()})
        .eq("id", str(thread_id))
        .eq("owner_id", str(user_id))
        .execute()
    )
    return response.data[0]


async def delete_thread(
    client: AsyncClient,
    admin: AsyncClient,
    thread_id: UUID,
    user_id: UUID,
) -> None:
    await require_owned_thread(client, admin, thread_id, user_id)
    await (
        client.table("chat_threads")
        .delete()
        .eq("id", str(thread_id))
        .eq("owner_id", str(user_id))
        .execute()
    )


async def complete_chat_turn(
    client: AsyncClient,
    thread_id: UUID,
    expected_position: int,
    user_message: InternalUserMessage,
    user_message_id: UUID,
    assistant_message_id: UUID,
    assistant_content: str,
    assistant_message_data: dict[str, object],
    model_usage: dict[str, object],
    citations: list[dict[str, object]],
    first_turn_title: str,
) -> TurnPersistenceResult:
    try:
        response = await client.rpc(
            "complete_chat_turn",
            {
                "p_thread_id": str(thread_id),
                "p_expected_position": expected_position,
                "p_user_message_id": str(user_message_id),
                "p_user_content": user_message.content,
                "p_user_message_data": user_message.message_data,
                "p_assistant_message_id": str(assistant_message_id),
                "p_assistant_content": assistant_content,
                "p_assistant_message_data": assistant_message_data,
                "p_model_usage": model_usage,
                "p_citations": citations,
                "p_first_turn_title": first_turn_title,
            },
        ).execute()
    except APIError as error:
        if error.code in {"23505", "40001"}:
            raise ChatPositionConflictError from error
        if error.code == "P0002":
            raise ChatThreadNotFoundError from error
        raise
    if not isinstance(response.data, list) or len(response.data) != 1:
        raise TypeError("Supabase complete_chat_turn returned an invalid response")
    row = response.data[0]
    if not isinstance(row, dict) or "assistant_created_at" not in row:
        raise TypeError("Supabase complete_chat_turn omitted the assistant timestamp")
    return TurnPersistenceResult(
        assistant_created_at=_parse_datetime(row["assistant_created_at"]),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
