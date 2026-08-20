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
    append_stub_turn,
    list_threads,
    rename_thread,
    require_owned_thread,
)


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


def test_append_stub_turn_inserts_ordered_pair_and_touches_thread() -> None:
    last_position = FakeBuilder([{"position": 4}])
    message_insert = FakeBuilder()
    thread_update = FakeBuilder()
    client = FakeClient(
        {
            "chat_messages": [last_position, message_insert],
            "chat_threads": [thread_update],
        }
    )
    thread_id = uuid4()
    user_id = uuid4()

    assistant_id = asyncio.run(
        append_stub_turn(
            client,
            thread_id,
            user_id,
            InternalUserMessage(
                client_id="client-1",
                content="Question",
                message_data={"parts": []},
            ),
            "Stub answer",
        )
    )

    inserted_rows = next(
        value for action, value in message_insert.calls if action == "insert"
    )
    assert [row["position"] for row in inserted_rows] == [5, 6]
    assert [row["role"] for row in inserted_rows] == ["user", "assistant"]
    assert inserted_rows[1]["id"] == str(assistant_id)
    updated_values = next(
        value for action, value in thread_update.calls if action == "update"
    )
    assert "updated_at" in updated_values
    assert ("eq", ("owner_id", str(user_id))) in thread_update.calls


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


def test_duplicate_message_position_becomes_conflict() -> None:
    conflict = APIError({"code": "23505", "message": "duplicate position"})
    client = FakeClient(
        {
            "chat_messages": [FakeBuilder([]), FakeBuilder(error=conflict)],
            "chat_threads": [],
        }
    )

    with pytest.raises(ChatPositionConflictError):
        asyncio.run(
            append_stub_turn(
                client,
                uuid4(),
                uuid4(),
                InternalUserMessage(
                    client_id="client-1",
                    content="Question",
                    message_data={},
                ),
                "Stub answer",
            )
        )
