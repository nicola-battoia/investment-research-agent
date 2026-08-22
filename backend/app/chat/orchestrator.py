"""Own one authorized, grounded, and atomically persisted chat turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

import structlog
from openai import AsyncOpenAI
from supabase import AsyncClient

from app.assistant import AssistantDeps, AssistantModelSettings, DocumentAssistant
from app.chat.messages import (
    InternalUserMessage,
    MessageMetadata,
    TextPart,
    UIMessageResponse,
    assistant_message_data,
    assistant_ui_parts,
    stored_messages_to_history,
    stored_messages_to_ui,
)
from app.config import Settings
from app.database import chats
from app.grounding import GroundingValidator
from app.retrieval.keywords import OpenAIKeywordExtractor
from app.retrieval.retriever import DocumentRetriever

logger = structlog.get_logger()
MAX_THREAD_TITLE_CHARACTERS = 60


class AssistantRunner(Protocol):
    async def run(self, question, deps, history=(), **kwargs): ...


@dataclass(frozen=True)
class PreparedChatTurn:
    thread_id: UUID
    user_id: UUID
    user_message: InternalUserMessage
    expected_position: int
    history_rows: tuple[dict[str, object], ...]
    cached_assistant: UIMessageResponse | None = None


class ChatTurnOrchestrator:
    """Coordinate current-turn services without retaining request state."""

    def __init__(
        self,
        *,
        settings: Settings,
        supabase: AsyncClient,
        openai_client: AsyncOpenAI,
        assistant: DocumentAssistant,
    ) -> None:
        self._settings = settings
        self._supabase = supabase
        self._openai_client = openai_client
        self._assistant: AssistantRunner = assistant

    async def prepare(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        user_message: InternalUserMessage,
    ) -> PreparedChatTurn:
        _thread, messages, citations = await chats.load_thread(
            self._supabase,
            self._settings,
            thread_id,
            user_id,
        )
        _validate_positions(messages)
        ui_messages = stored_messages_to_ui(messages, citations)
        cached_assistant = _find_cached_assistant(
            ui_messages,
            user_message.client_id,
            user_message.content,
        )
        expected_position = len(messages)
        return PreparedChatTurn(
            thread_id=thread_id,
            user_id=user_id,
            user_message=user_message,
            expected_position=expected_position,
            history_rows=tuple(messages),
            cached_assistant=cached_assistant,
        )

    async def complete(self, turn: PreparedChatTurn) -> UIMessageResponse:
        if turn.cached_assistant is not None:
            return turn.cached_assistant

        retriever = DocumentRetriever(
            self._supabase,
            self._openai_client,
            OpenAIKeywordExtractor(
                self._openai_client,
                model=self._settings.openai_keyword_model,
            ),
            embedding_model=self._settings.openai_embedding_model,
            embedding_dimensions=self._settings.openai_embedding_dimensions,
        )
        deps = AssistantDeps(
            user_id=turn.user_id,
            thread_id=turn.thread_id,
            retriever=retriever,
            grounding_validator=GroundingValidator(),
            model_settings=AssistantModelSettings.from_app_settings(self._settings),
        )
        result = await self._assistant.run(
            turn.user_message.content,
            deps,
            stored_messages_to_history(list(turn.history_rows)),
        )

        user_message_id = uuid4()
        assistant_message_id = uuid4()
        citation_ids = tuple(uuid4() for _citation in result.answer.citations)
        parts = assistant_ui_parts(result.answer, citation_ids)
        persistence = await chats.complete_chat_turn(
            self._supabase,
            turn.thread_id,
            turn.expected_position,
            turn.user_message,
            user_message_id,
            assistant_message_id,
            result.answer.answer,
            assistant_message_data(result.answer.status, parts),
            result.usage.model_dump(mode="json"),
            [
                {
                    "id": str(citation_id),
                    "chunk_id": str(citation.chunk_id),
                    "citation_index": citation.citation_index,
                    "excerpt": citation.excerpt,
                }
                for citation, citation_id in zip(
                    result.answer.citations,
                    citation_ids,
                    strict=True,
                )
            ],
            derive_thread_title(turn.user_message.content),
        )
        logger.info(
            "chat_turn_completed",
            user_id=str(turn.user_id),
            thread_id=str(turn.thread_id),
            answer_status=result.answer.status,
            citation_count=len(result.answer.citations),
            requests=result.usage.requests,
            tool_calls=result.usage.tool_calls,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            cost_usd=(str(result.usage.cost_usd) if result.usage.cost_usd else None),
        )
        return UIMessageResponse(
            id=str(assistant_message_id),
            role="assistant",
            parts=parts,
            metadata=MessageMetadata(
                created_at=persistence.assistant_created_at,
                answer_status=result.answer.status,
            ),
        )


def derive_thread_title(question: str) -> str:
    normalized = " ".join(question.split())
    if len(normalized) <= MAX_THREAD_TITLE_CHARACTERS:
        return normalized
    prefix = normalized[: MAX_THREAD_TITLE_CHARACTERS - 1]
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return prefix.rstrip(".,;:!?") + "…"


def _validate_positions(messages: list[dict[str, object]]) -> None:
    for expected, message in enumerate(messages):
        if int(message["position"]) != expected:
            raise ValueError("Stored chat messages have non-contiguous positions")


def _find_cached_assistant(
    messages: list[UIMessageResponse],
    client_message_id: str,
    user_content: str,
) -> UIMessageResponse | None:
    for index, message in enumerate(messages):
        if message.role != "user" or message.id != client_message_id:
            continue
        stored_content = "\n".join(
            part.text for part in message.parts if isinstance(part, TextPart)
        )
        if stored_content != user_content:
            raise chats.ChatPositionConflictError(
                "The client message ID was already used for another question"
            )
        if index + 1 >= len(messages) or messages[index + 1].role != "assistant":
            raise ValueError(
                "A persisted client message is missing its assistant reply"
            )
        return messages[index + 1]
    return None
