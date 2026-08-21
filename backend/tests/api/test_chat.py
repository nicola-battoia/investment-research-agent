from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest import APIError
from supabase_auth import User

from app.api.chat import STUB_ASSISTANT_TEXT
from app.auth.dependencies import AuthenticatedContext, get_authenticated_context
from app.config import Settings
from app.database.chats import (
    ChatPositionConflictError,
    ChatThreadForbiddenError,
    ChatThreadNotFoundError,
)
from app.main import create_app

USER_ID = UUID("8b50b43c-571d-4fbc-8a3b-32e3bbfa39da")
THREAD_ID = UUID("1195cdd2-508e-4f18-ac86-8796e983a3e5")
ASSISTANT_ID = UUID("e89a3299-0c82-4026-8d1f-a3db8d032d38")
CREATED_AT = "2026-08-19T09:00:00+00:00"
UPDATED_AT = "2026-08-19T10:00:00+00:00"


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="https://project.supabase.co",
        supabase_anon_key="test-anon-key",
        supabase_service_role_key="test-service-role-key",
        database_url=("postgresql+psycopg://postgres:password@localhost:5432/postgres"),
        openai_api_key="test-openai-key",
        openai_embedding_model="text-embedding-3-small",
        openai_embedding_dimensions=1536,
        openai_keyword_model="gpt-5.4-nano",
        openai_assistant_model="gpt-5.6-terra",
        openai_assistant_reasoning_effort="medium",
        openai_assistant_max_output_tokens=3000,
        allowed_origins="http://localhost:5173",
    )


def thread_row(title: str = "New chat") -> dict[str, object]:
    return {
        "id": str(THREAD_ID),
        "title": title,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
    }


def make_client() -> TestClient:
    application = create_app(make_settings())
    user = User(
        id=str(USER_ID),
        email="analyst@10kclub.example",
        app_metadata={},
        user_metadata={},
        aud="authenticated",
        created_at=datetime.now(UTC),
    )
    application.dependency_overrides[get_authenticated_context] = lambda: (
        AuthenticatedContext(user=user, supabase=object())
    )
    return TestClient(application)


def test_thread_crud_uses_authenticated_owner_and_camel_case_responses() -> None:
    list_threads = AsyncMock(return_value=[thread_row()])
    create_thread = AsyncMock(return_value=thread_row())
    rename_thread = AsyncMock(return_value=thread_row("Renamed"))
    delete_thread = AsyncMock()

    with (
        patch("app.api.chat.chats.list_threads", list_threads),
        patch("app.api.chat.chats.create_thread", create_thread),
        patch("app.api.chat.chats.rename_thread", rename_thread),
        patch("app.api.chat.chats.delete_thread", delete_thread),
        make_client() as client,
    ):
        listed = client.get("/chat/threads")
        created = client.post("/chat/threads", json={})
        renamed = client.patch(
            f"/chat/threads/{THREAD_ID}",
            json={"title": "  Renamed  "},
        )
        deleted = client.delete(f"/chat/threads/{THREAD_ID}")

    assert listed.status_code == 200
    assert listed.json()[0]["updatedAt"] == "2026-08-19T10:00:00Z"
    assert created.status_code == 201
    assert created.json()["title"] == "New chat"
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed"
    assert deleted.status_code == 204
    create_thread.assert_awaited_once()
    assert create_thread.await_args.args[1] == USER_ID
    assert rename_thread.await_args.args[-1] == "Renamed"
    delete_thread.assert_awaited_once()


def test_loads_ordered_history_and_citations() -> None:
    message_id = uuid4()
    citation_id = uuid4()
    chunk_id = uuid4()
    load_thread = AsyncMock(
        return_value=(
            thread_row(),
            [
                {
                    "id": str(message_id),
                    "role": "assistant",
                    "content": "Stored answer",
                    "created_at": CREATED_AT,
                }
            ],
            [
                {
                    "id": str(citation_id),
                    "message_id": str(message_id),
                    "chunk_id": str(chunk_id),
                    "citation_index": 0,
                    "excerpt": "Evidence",
                }
            ],
        )
    )

    with (
        patch("app.api.chat.chats.load_thread", load_thread),
        make_client() as client,
    ):
        response = client.get(f"/chat/threads/{THREAD_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread"]["id"] == str(THREAD_ID)
    assert payload["messages"][0]["parts"] == [
        {"type": "text", "text": "Stored answer"}
    ]
    assert payload["messages"][0]["metadata"]["citations"] == [
        {
            "id": str(citation_id),
            "chunkId": str(chunk_id),
            "citationIndex": 0,
            "excerpt": "Evidence",
        }
    ]


def test_stream_persists_then_emits_ai_sdk_message_events() -> None:
    require_owned = AsyncMock(return_value=thread_row())
    append_turn = AsyncMock(return_value=ASSISTANT_ID)
    request_payload = {
        "id": str(THREAD_ID),
        "message": {
            "id": "client-message-1",
            "role": "user",
            "parts": [{"type": "text", "text": "What changed?"}],
        },
    }

    with (
        patch("app.api.chat.chats.require_owned_thread", require_owned),
        patch("app.api.chat.chats.append_stub_turn", append_turn),
        make_client() as client,
    ):
        response = client.post("/chat/stream", json=request_payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert response.text.split("\n\n")[:-1] == [
        f'data: {{"type":"start","messageId":"{ASSISTANT_ID}"}}',
        f'data: {{"type":"text-start","id":"{ASSISTANT_ID}-text"}}',
        (
            f'data: {{"type":"text-delta","id":"{ASSISTANT_ID}-text",'
            '"delta":"Your message is saved. "}'
        ),
        (
            f'data: {{"type":"text-delta","id":"{ASSISTANT_ID}-text",'
            '"delta":"Document retrieval is not connected yet, "}'
        ),
        (
            f'data: {{"type":"text-delta","id":"{ASSISTANT_ID}-text",'
            '"delta":"but the authenticated chat and streaming path are working."}'
        ),
        f'data: {{"type":"text-end","id":"{ASSISTANT_ID}-text"}}',
        'data: {"type":"finish"}',
        "data: [DONE]",
    ]
    internal_message = append_turn.await_args.args[3]
    assert internal_message.content == "What changed?"
    assert append_turn.await_args.args[4] == STUB_ASSISTANT_TEXT


@pytest.mark.parametrize(
    "message",
    [
        {"id": "m1", "role": "assistant", "parts": [{"type": "text", "text": "x"}]},
        {"id": "m1", "role": "user", "parts": []},
        {"id": "m1", "role": "user", "parts": [{"type": "text", "text": " "}]},
        {"id": "m1", "role": "user", "parts": [{"type": "image", "url": "x"}]},
        {
            "id": "m1",
            "role": "user",
            "parts": [{"type": "text", "text": "x" * 10_001}],
        },
    ],
)
def test_stream_rejects_invalid_ui_messages(message: dict[str, object]) -> None:
    with make_client() as client:
        response = client.post(
            "/chat/stream",
            json={"id": str(THREAD_ID), "message": message},
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ChatThreadForbiddenError(), 403),
        (ChatThreadNotFoundError(), 404),
        (ChatPositionConflictError(), 409),
        (APIError({"code": "XX000", "message": "database unavailable"}), 502),
    ],
)
def test_chat_errors_have_stable_http_statuses(
    error: Exception,
    expected_status: int,
) -> None:
    list_threads = AsyncMock(side_effect=error)
    with (
        patch("app.api.chat.chats.list_threads", list_threads),
        make_client() as client,
    ):
        response = client.get("/chat/threads")

    assert response.status_code == expected_status
    assert isinstance(response.json()["detail"], str)


def test_chat_stream_cors_preflight_allows_auth_and_json_headers() -> None:
    with make_client() as client:
        response = client.options(
            "/chat/stream",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ("http://localhost:5173")
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
