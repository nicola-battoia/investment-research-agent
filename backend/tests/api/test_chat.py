from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest import APIError
from supabase_auth import User

from app.auth.dependencies import AuthenticatedContext, get_authenticated_context
from app.chat.messages import (
    CitationData,
    CitationPart,
    InternalUserMessage,
    MessageMetadata,
    SourceUrlPart,
    TextPart,
    UIMessageResponse,
)
from app.chat.orchestrator import PreparedChatTurn
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
        app_environment="test",
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
                    "message_data": {
                        "answerStatus": "supported",
                        "parts": [{"type": "text", "text": "Stored answer"}],
                    },
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
    assert payload["messages"][0]["metadata"]["answerStatus"] == "supported"


def test_stream_emits_only_completed_ai_sdk_message_events() -> None:
    prepared = PreparedChatTurn(
        thread_id=THREAD_ID,
        user_id=USER_ID,
        user_message=InternalUserMessage(
            client_id="client-message-1",
            content="What changed?",
            message_data={},
        ),
        expected_position=0,
        history_rows=(),
    )
    prepare = AsyncMock(return_value=prepared)
    complete = AsyncMock(
        return_value=UIMessageResponse(
            id=str(ASSISTANT_ID),
            role="assistant",
            parts=[
                TextPart(type="text", text="A grounded answer [S1]."),
                SourceUrlPart(
                    type="source-url",
                    source_id="S1",
                    url="https://www.sec.gov/example",
                    title="Apple 10-K",
                ),
                CitationPart(
                    type="data-citation",
                    id=str(uuid4()),
                    data=CitationData(
                        citation_id=uuid4(),
                        source_id="S1",
                        citation_index=0,
                        chunk_id=uuid4(),
                        document_id=uuid4(),
                        chunk_index=3,
                        excerpt="An exact filing excerpt supporting the grounded answer.",
                        company="Apple Inc.",
                        ticker="AAPL",
                        filing_type="10-K",
                        filing_date=date(2024, 11, 1),
                        report_date=date(2024, 9, 28),
                        accession_number="0000320193-24-000123",
                        sec_url="https://www.sec.gov/example",
                        page_number=12,
                        section_title="Results of Operations",
                        source_start=100,
                        source_end=180,
                    ),
                ),
            ],
            metadata=MessageMetadata(
                created_at=datetime.fromisoformat(CREATED_AT),
                answer_status="supported",
            ),
        )
    )
    request_payload = {
        "id": str(THREAD_ID),
        "message": {
            "id": "client-message-1",
            "role": "user",
            "parts": [{"type": "text", "text": "What changed?"}],
        },
    }

    with (
        patch("app.api.chat.ChatTurnOrchestrator.prepare", prepare),
        patch("app.api.chat.ChatTurnOrchestrator.complete", complete),
        make_client() as client,
    ):
        response = client.post("/chat/stream", json=request_payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    events = response.text.split("\n\n")[:-1]
    assert '"type":"data-turn-status"' in events[0]
    assert f'"type":"start","messageId":"{ASSISTANT_ID}"' in events[1]
    assert '"answerStatus":"supported"' in events[1]
    assert '"type":"text-delta"' in events[3]
    assert '"delta":"A grounded answer [S1]."' in events[3]
    assert any('"type":"source-url"' in event for event in events)
    assert any('"type":"data-citation"' in event for event in events)
    assert '"type":"finish","finishReason":"stop"' in events[-2]
    assert events[-1] == "data: [DONE]"
    assert prepare.await_args.kwargs["user_message"].content == "What changed?"
    complete.assert_awaited_once_with(prepared)


def test_streams_an_insufficient_evidence_turn_without_sources() -> None:
    prepared = PreparedChatTurn(
        thread_id=THREAD_ID,
        user_id=USER_ID,
        user_message=InternalUserMessage(
            client_id="client-message-1",
            content="Unsupported question",
            message_data={},
        ),
        expected_position=0,
        history_rows=(),
    )
    complete = AsyncMock(
        return_value=UIMessageResponse(
            id=str(ASSISTANT_ID),
            role="assistant",
            parts=[
                TextPart(
                    type="text",
                    text=(
                        "The available SEC filing corpus does not contain enough "
                        "evidence to answer that question."
                    ),
                )
            ],
            metadata=MessageMetadata(
                created_at=datetime.fromisoformat(CREATED_AT),
                answer_status="insufficient_evidence",
            ),
        )
    )
    with (
        patch(
            "app.api.chat.ChatTurnOrchestrator.prepare",
            AsyncMock(return_value=prepared),
        ),
        patch("app.api.chat.ChatTurnOrchestrator.complete", complete),
        make_client() as client,
    ):
        response = client.post(
            "/chat/stream",
            json={
                "id": str(THREAD_ID),
                "message": {
                    "id": "client-message-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "Unsupported question"}],
                },
            },
        )

    assert response.status_code == 200
    assert '"answerStatus":"insufficient_evidence"' in response.text
    assert '"type":"source-url"' not in response.text
    assert '"type":"data-citation"' not in response.text


@pytest.mark.parametrize("answer_status", ["conversational", "out_of_scope"])
def test_streams_non_retrieval_turn_without_sources(answer_status: str) -> None:
    prepared = PreparedChatTurn(
        thread_id=THREAD_ID,
        user_id=USER_ID,
        user_message=InternalUserMessage(
            client_id="client-message-1",
            content="Hello",
            message_data={},
        ),
        expected_position=0,
        history_rows=(),
    )
    complete = AsyncMock(
        return_value=UIMessageResponse(
            id=str(ASSISTANT_ID),
            role="assistant",
            parts=[TextPart(type="text", text="A short response.")],
            metadata=MessageMetadata(
                created_at=datetime.fromisoformat(CREATED_AT),
                answer_status=answer_status,
            ),
        )
    )
    with (
        patch(
            "app.api.chat.ChatTurnOrchestrator.prepare",
            AsyncMock(return_value=prepared),
        ),
        patch("app.api.chat.ChatTurnOrchestrator.complete", complete),
        make_client() as client,
    ):
        response = client.post(
            "/chat/stream",
            json={
                "id": str(THREAD_ID),
                "message": {
                    "id": "client-message-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "Hello"}],
                },
            },
        )

    assert response.status_code == 200
    assert f'"answerStatus":"{answer_status}"' in response.text
    assert '"type":"source-url"' not in response.text
    assert '"type":"data-citation"' not in response.text


def test_upstream_stream_failure_has_no_completed_assistant_message() -> None:
    from openai import APIConnectionError

    prepared = PreparedChatTurn(
        thread_id=THREAD_ID,
        user_id=USER_ID,
        user_message=InternalUserMessage(
            client_id="client-message-1",
            content="Question",
            message_data={},
        ),
        expected_position=0,
        history_rows=(),
    )
    with (
        patch(
            "app.api.chat.ChatTurnOrchestrator.prepare",
            AsyncMock(return_value=prepared),
        ),
        patch(
            "app.api.chat.ChatTurnOrchestrator.complete",
            AsyncMock(side_effect=APIConnectionError(request=object())),
        ),
        make_client() as client,
    ):
        response = client.post(
            "/chat/stream",
            json={
                "id": str(THREAD_ID),
                "message": {
                    "id": "client-message-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "Question"}],
                },
            },
        )

    assert response.status_code == 200
    assert '"code":"assistant_unavailable"' in response.text
    assert '"type":"error"' in response.text
    assert '"type":"start"' not in response.text
    assert '"type":"finish"' not in response.text


def test_forbidden_thread_is_rejected_before_streaming() -> None:
    with (
        patch(
            "app.api.chat.ChatTurnOrchestrator.prepare",
            AsyncMock(side_effect=ChatThreadForbiddenError()),
        ),
        make_client() as client,
    ):
        response = client.post(
            "/chat/stream",
            json={
                "id": str(THREAD_ID),
                "message": {
                    "id": "client-message-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "Question"}],
                },
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to this chat thread"


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
