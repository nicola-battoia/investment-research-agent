"""User-scoped chat thread and message persistence."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from postgrest import APIError
from supabase import AsyncClient

from app.chat.messages import (
    InternalUserMessage,
    assistant_message_data,
)
from app.config import Settings
from app.database.supabase import create_admin_supabase_client

THREAD_COLUMNS = "id,title,created_at,updated_at"
MESSAGE_COLUMNS = "id,thread_id,position,role,content,message_data,created_at"
CITATION_COLUMNS = "id,message_id,chunk_id,citation_index,excerpt"


class ChatThreadNotFoundError(Exception):
    """The requested chat thread does not exist."""


class ChatThreadForbiddenError(Exception):
    """The requested chat thread belongs to another user."""


class ChatPositionConflictError(Exception):
    """Two turns attempted to claim the same message positions."""


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
    app_settings: Settings,
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

    admin = await create_admin_supabase_client(app_settings)
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
    app_settings: Settings,
    thread_id: UUID,
    user_id: UUID,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    thread = await require_owned_thread(client, app_settings, thread_id, user_id)
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
    app_settings: Settings,
    thread_id: UUID,
    user_id: UUID,
    title: str,
) -> dict[str, object]:
    await require_owned_thread(client, app_settings, thread_id, user_id)
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
    app_settings: Settings,
    thread_id: UUID,
    user_id: UUID,
) -> None:
    await require_owned_thread(client, app_settings, thread_id, user_id)
    await (
        client.table("chat_threads")
        .delete()
        .eq("id", str(thread_id))
        .eq("owner_id", str(user_id))
        .execute()
    )


async def append_stub_turn(
    client: AsyncClient,
    thread_id: UUID,
    user_id: UUID,
    user_message: InternalUserMessage,
    assistant_content: str,
) -> UUID:
    last_message_response = await (
        client.table("chat_messages")
        .select("position")
        .eq("thread_id", str(thread_id))
        .order("position", desc=True)
        .limit(1)
        .execute()
    )
    next_position = (
        int(last_message_response.data[0]["position"]) + 1
        if last_message_response.data
        else 0
    )
    user_message_id = uuid4()
    assistant_message_id = uuid4()
    rows = [
        {
            "id": str(user_message_id),
            "thread_id": str(thread_id),
            "position": next_position,
            "role": "user",
            "content": user_message.content,
            "message_data": user_message.message_data,
        },
        {
            "id": str(assistant_message_id),
            "thread_id": str(thread_id),
            "position": next_position + 1,
            "role": "assistant",
            "content": assistant_content,
            "message_data": assistant_message_data(assistant_content),
        },
    ]
    try:
        await client.table("chat_messages").insert(rows).execute()
    except APIError as error:
        if error.code == "23505":
            raise ChatPositionConflictError from error
        raise

    await (
        client.table("chat_threads")
        .update({"updated_at": _now()})
        .eq("id", str(thread_id))
        .eq("owner_id", str(user_id))
        .execute()
    )
    return assistant_message_id


def _now() -> str:
    return datetime.now(UTC).isoformat()
