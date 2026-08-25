import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.assistant.outputs import (
    AnswerStatus,
    AssistantRunResult,
    AssistantUsage,
    Citation,
    GroundedAnswer,
)
from app.chat.messages import InternalUserMessage
from app.chat.orchestrator import ChatTurnOrchestrator, derive_thread_title
from app.config import Settings
from app.database.chats import ChatPositionConflictError, TurnPersistenceResult

USER_ID = UUID("8b50b43c-571d-4fbc-8a3b-32e3bbfa39da")
THREAD_ID = UUID("1195cdd2-508e-4f18-ac86-8796e983a3e5")
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="https://project.supabase.co",
        supabase_anon_key="test-anon-key",
        supabase_service_role_key="test-service-role-key",
        database_url="postgresql+psycopg://postgres:password@localhost:5432/postgres",
        openai_api_key="test-openai-key",
        openai_embedding_model="text-embedding-3-small",
        openai_embedding_dimensions=1536,
        openai_keyword_model="gpt-5.4-nano",
        openai_assistant_model="gpt-5.6-terra",
        openai_assistant_reasoning_effort="medium",
        openai_assistant_max_output_tokens=3000,
        allowed_origins="http://localhost:5173",
    )


def user_message(
    client_id: str = "client-2",
    content: str = "What changed next?",
) -> InternalUserMessage:
    return InternalUserMessage(
        client_id=client_id,
        content=content,
        message_data={
            "clientMessageId": client_id,
            "parts": [{"type": "text", "text": content}],
        },
    )


def citation() -> Citation:
    return Citation(
        source_id="S1",
        citation_index=0,
        chunk_id=UUID(int=1),
        document_id=UUID(int=2),
        chunk_index=4,
        excerpt="Higher advertising and cloud services revenue drove the increase.",
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
    )


def result(status: AnswerStatus = "supported") -> AssistantRunResult:
    if status == "supported":
        answer = GroundedAnswer(
            status="supported",
            answer="Services increased because of advertising and cloud revenue [S1].",
            citations=(citation(),),
        )
    elif status == "insufficient_evidence":
        answer = GroundedAnswer(
            status="insufficient_evidence",
            answer=(
                "The available SEC filing corpus does not contain enough evidence "
                "to answer that question."
            ),
        )
    else:
        answer = GroundedAnswer(status=status, answer="A short response.")
    return AssistantRunResult(
        answer=answer,
        usage=AssistantUsage(
            requests=3,
            tool_calls=2 if status == "supported" else 0,
            input_tokens=100,
            output_tokens=30,
            total_tokens=130,
            cache_read_tokens=20,
            cost_usd=Decimal("0.01"),
        ),
    )


def history_rows() -> list[dict[str, object]]:
    return [
        {
            "id": str(uuid4()),
            "position": 0,
            "role": "user",
            "content": "What changed first?",
            "message_data": {
                "clientMessageId": "client-1",
                "parts": [{"type": "text", "text": "What changed first?"}],
            },
            "created_at": NOW.isoformat(),
        },
        {
            "id": str(uuid4()),
            "position": 1,
            "role": "assistant",
            "content": "The first answer [S1].",
            "message_data": {
                "answerStatus": "supported",
                "parts": [{"type": "text", "text": "The first answer [S1]."}],
            },
            "created_at": NOW.isoformat(),
        },
    ]


def orchestrator(assistant: object) -> ChatTurnOrchestrator:
    return ChatTurnOrchestrator(
        settings=make_settings(),
        supabase=object(),
        openai_client=SimpleNamespace(responses=object(), embeddings=object()),
        assistant=assistant,
    )


def test_runs_with_saved_history_and_atomically_persists_validated_turn() -> None:
    assistant = SimpleNamespace(run=AsyncMock(return_value=result()))
    persist = AsyncMock(return_value=TurnPersistenceResult(assistant_created_at=NOW))
    rows = history_rows()
    service = orchestrator(assistant)

    async def run():
        with (
            patch(
                "app.chat.orchestrator.chats.load_thread",
                AsyncMock(return_value=({"id": str(THREAD_ID)}, rows, [])),
            ),
            patch("app.chat.orchestrator.chats.complete_chat_turn", persist),
        ):
            prepared = await service.prepare(
                thread_id=THREAD_ID,
                user_id=USER_ID,
                user_message=user_message(),
            )
            return await service.complete(prepared)

    completed = asyncio.run(run())

    assert completed.metadata.answer_status == "supported"
    assert [part.type for part in completed.parts] == [
        "text",
        "source-url",
        "data-citation",
    ]
    assert assistant.run.await_args.args[0] == "What changed next?"
    history = assistant.run.await_args.args[2]
    assert [message.content for message in history] == [
        "What changed first?",
        "The first answer [S1].",
    ]
    assert persist.await_args.args[2] == 2
    assert persist.await_args.args[8]["total_tokens"] == 130
    assert persist.await_args.args[9][0]["chunk_id"] == str(UUID(int=1))


def test_insufficient_evidence_turn_persists_without_citations() -> None:
    assistant = SimpleNamespace(
        run=AsyncMock(return_value=result("insufficient_evidence"))
    )
    persist = AsyncMock(return_value=TurnPersistenceResult(assistant_created_at=NOW))
    service = orchestrator(assistant)

    async def run():
        with (
            patch(
                "app.chat.orchestrator.chats.load_thread",
                AsyncMock(return_value=({"id": str(THREAD_ID)}, [], [])),
            ),
            patch("app.chat.orchestrator.chats.complete_chat_turn", persist),
        ):
            prepared = await service.prepare(
                thread_id=THREAD_ID,
                user_id=USER_ID,
                user_message=user_message(),
            )
            return await service.complete(prepared)

    completed = asyncio.run(run())

    assert completed.metadata.answer_status == "insufficient_evidence"
    assert [part.type for part in completed.parts] == ["text"]
    assert persist.await_args.args[9] == []


@pytest.mark.parametrize("status", ["conversational", "out_of_scope"])
def test_non_retrieval_turn_persists_without_citations(status: AnswerStatus) -> None:
    assistant = SimpleNamespace(run=AsyncMock(return_value=result(status)))
    persist = AsyncMock(return_value=TurnPersistenceResult(assistant_created_at=NOW))
    service = orchestrator(assistant)

    async def run():
        with (
            patch(
                "app.chat.orchestrator.chats.load_thread",
                AsyncMock(return_value=({"id": str(THREAD_ID)}, [], [])),
            ),
            patch("app.chat.orchestrator.chats.complete_chat_turn", persist),
        ):
            prepared = await service.prepare(
                thread_id=THREAD_ID,
                user_id=USER_ID,
                user_message=user_message(),
            )
            return await service.complete(prepared)

    completed = asyncio.run(run())

    assert completed.metadata.answer_status == status
    assert [part.type for part in completed.parts] == ["text"]
    assert persist.await_args.args[7]["answerStatus"] == status
    assert persist.await_args.args[9] == []


def test_replays_a_completed_client_message_without_running_the_agent() -> None:
    rows = history_rows()
    assistant = SimpleNamespace(run=AsyncMock())
    service = orchestrator(assistant)

    async def run():
        with patch(
            "app.chat.orchestrator.chats.load_thread",
            AsyncMock(return_value=({"id": str(THREAD_ID)}, rows, [])),
        ):
            prepared = await service.prepare(
                thread_id=THREAD_ID,
                user_id=USER_ID,
                user_message=user_message("client-1", "What changed first?"),
            )
            return await service.complete(prepared)

    completed = asyncio.run(run())

    assert completed.parts[0].text == "The first answer [S1]."
    assistant.run.assert_not_awaited()


def test_rejects_reusing_a_client_message_id_for_a_different_question() -> None:
    rows = history_rows()
    assistant = SimpleNamespace(run=AsyncMock())
    service = orchestrator(assistant)

    async def run():
        with patch(
            "app.chat.orchestrator.chats.load_thread",
            AsyncMock(return_value=({"id": str(THREAD_ID)}, rows, [])),
        ):
            return await service.prepare(
                thread_id=THREAD_ID,
                user_id=USER_ID,
                user_message=InternalUserMessage(
                    client_id="client-1",
                    content="A different question",
                    message_data={},
                ),
            )

    with pytest.raises(ChatPositionConflictError):
        asyncio.run(run())
    assistant.run.assert_not_awaited()


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("  What   changed?  ", "What changed?"),
        (
            "Compare the changes in cloud infrastructure spending across all years",
            "Compare the changes in cloud infrastructure spending…",
        ),
        ("x" * 80, "x" * 59 + "…"),
    ],
)
def test_derives_bounded_first_question_title(question: str, expected: str) -> None:
    assert derive_thread_title(question) == expected
