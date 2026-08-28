import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from postgrest import APIError

from app.chat.messages import InternalUserMessage
from app.config import Settings
from app.database.chats import (
    ChatPositionConflictError,
    ChatThreadForbiddenError,
    ChatThreadNotFoundError,
    complete_chat_turn,
    list_threads,
    rename_thread,
    require_owned_thread,
)


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_environment="test",
        supabase_url="https://project.supabase.co",
        supabase_anon_key="test-anon-key",
        supabase_service_role_key="test-service-role-key",
        database_url=("postgresql+psycopg://postgres:password@localhost:5432/postgres"),
        azure_openai_endpoint="https://test-resource.openai.azure.com/openai/v1/",
        azure_openai_api_key="test-azure-key",
        azure_openai_assistant_deployment="assistant-gpt-5-6-terra",
        azure_openai_keyword_deployment="keywords-gpt-5-4-nano",
        azure_openai_embedding_deployment="embeddings-text-embedding-3-small",
        openai_embedding_model="text-embedding-3-small",
        openai_embedding_dimensions=1536,
        openai_keyword_model="gpt-5.4-nano",
        openai_assistant_model="gpt-5.6-terra",
        openai_assistant_reasoning_effort="medium",
        openai_assistant_max_output_tokens=3000,
        allowed_origins="http://localhost:5173",
    )


class FakeBuilder:
    def __init__(
        self,
        data: list[dict[str, object]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.data = data or []
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def select(self, columns: str) -> "FakeBuilder":
        self.calls.append(("select", columns))
        return self

    def eq(self, column: str, value: object) -> "FakeBuilder":
        self.calls.append(("eq", (column, value)))
        return self

    def order(self, column: str, *, desc: bool = False) -> "FakeBuilder":
        self.calls.append(("order", (column, desc)))
        return self

    def limit(self, count: int) -> "FakeBuilder":
        self.calls.append(("limit", count))
        return self

    def insert(self, rows: object) -> "FakeBuilder":
        self.calls.append(("insert", rows))
        return self

    def update(self, values: object) -> "FakeBuilder":
        self.calls.append(("update", values))
        return self

    async def execute(self) -> SimpleNamespace:
        if self.error:
            raise self.error
        return SimpleNamespace(data=self.data)


class FakeClient:
    def __init__(self, builders: dict[str, list[FakeBuilder]]) -> None:
        self.builders = builders
        self.used: list[tuple[str, FakeBuilder]] = []

    def table(self, name: str) -> FakeBuilder:
        builder = self.builders[name].pop(0)
        self.used.append((name, builder))
        return builder

    def rpc(self, name: str, params: dict[str, object]) -> FakeBuilder:
        builder = self.builders[name].pop(0)
        builder.calls.append(("rpc", params))
        self.used.append((name, builder))
        return builder


def test_list_threads_is_owner_scoped_and_newest_first() -> None:
    builder = FakeBuilder([{"id": str(uuid4())}])
    client = FakeClient({"chat_threads": [builder]})
    user_id = uuid4()

    result = asyncio.run(list_threads(client, user_id))

    assert result == builder.data
    assert ("eq", ("owner_id", str(user_id))) in builder.calls
    assert ("order", ("updated_at", True)) in builder.calls


def test_owned_thread_does_not_use_admin_client() -> None:
    thread_id = uuid4()
    user_id = uuid4()
    owned = {"id": str(thread_id), "title": "Mine"}
    user_client = FakeClient({"chat_threads": [FakeBuilder([owned])]})
    admin_factory = AsyncMock()

    with patch(
        "app.database.chats.create_admin_supabase_client",
        admin_factory,
    ):
        result = asyncio.run(
            require_owned_thread(user_client, make_settings(), thread_id, user_id)
        )

    assert result is owned
    admin_factory.assert_not_awaited()


@pytest.mark.parametrize(
    ("admin_data", "expected_error"),
    [
        ([], ChatThreadNotFoundError),
        ([{"owner_id": str(uuid4())}], ChatThreadForbiddenError),
    ],
)
def test_missing_user_scoped_thread_distinguishes_missing_from_forbidden(
    admin_data: list[dict[str, object]],
    expected_error: type[Exception],
) -> None:
    user_client = FakeClient({"chat_threads": [FakeBuilder([])]})
    admin_client = FakeClient({"chat_threads": [FakeBuilder(admin_data)]})

    with (
        patch(
            "app.database.chats.create_admin_supabase_client",
            AsyncMock(return_value=admin_client),
        ),
        pytest.raises(expected_error),
    ):
        asyncio.run(
            require_owned_thread(
                user_client,
                make_settings(),
                uuid4(),
                uuid4(),
            )
        )


def test_complete_turn_calls_atomic_rpc_with_messages_citations_and_usage() -> None:
    rpc = FakeBuilder([{"assistant_created_at": "2026-08-21T12:00:00+00:00"}])
    client = FakeClient({"complete_chat_turn": [rpc]})
    thread_id = uuid4()
    user_message_id = uuid4()
    assistant_message_id = uuid4()
    citation_id = uuid4()
    chunk_id = uuid4()

    result = asyncio.run(
        complete_chat_turn(
            client,
            thread_id,
            4,
            InternalUserMessage(
                client_id="client-1",
                content="Question",
                message_data={"clientMessageId": "client-1", "parts": []},
            ),
            user_message_id,
            assistant_message_id,
            "Grounded answer [S1].",
            {"answerStatus": "supported", "parts": []},
            {"totalTokens": 123},
            [
                {
                    "id": str(citation_id),
                    "chunk_id": str(chunk_id),
                    "citation_index": 0,
                    "excerpt": "Exact evidence",
                }
            ],
            "Question",
        )
    )

    params = next(value for action, value in rpc.calls if action == "rpc")
    assert params["p_expected_position"] == 4
    assert params["p_user_message_id"] == str(user_message_id)
    assert params["p_assistant_message_id"] == str(assistant_message_id)
    assert params["p_citations"][0]["chunk_id"] == str(chunk_id)
    assert params["p_model_usage"] == {"totalTokens": 123}
    assert result.assistant_created_at.isoformat() == "2026-08-21T12:00:00+00:00"


def test_rename_thread_sets_updated_at_and_owner_filter() -> None:
    thread_id = uuid4()
    user_id = uuid4()
    owned = FakeBuilder([{"id": str(thread_id), "title": "Old"}])
    updated_row = {"id": str(thread_id), "title": "Renamed"}
    update = FakeBuilder([updated_row])
    client = FakeClient({"chat_threads": [owned, update]})

    result = asyncio.run(
        rename_thread(
            client,
            make_settings(),
            thread_id,
            user_id,
            "Renamed",
        )
    )

    assert result == updated_row
    update_values = next(value for action, value in update.calls if action == "update")
    assert update_values["title"] == "Renamed"
    assert "updated_at" in update_values
    assert ("eq", ("owner_id", str(user_id))) in update.calls


@pytest.mark.parametrize("code", ["23505", "40001"])
def test_duplicate_or_changed_message_position_becomes_conflict(code: str) -> None:
    conflict = APIError({"code": code, "message": "message position conflict"})
    client = FakeClient({"complete_chat_turn": [FakeBuilder(error=conflict)]})

    with pytest.raises(ChatPositionConflictError):
        asyncio.run(
            complete_chat_turn(
                client,
                uuid4(),
                0,
                InternalUserMessage(
                    client_id="client-1",
                    content="Question",
                    message_data={},
                ),
                uuid4(),
                uuid4(),
                "Answer",
                {"parts": []},
                {},
                [],
                "Question",
            )
        )
