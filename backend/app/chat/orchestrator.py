"""Own one authorized, grounded, and atomically persisted chat turn."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID, uuid4

from supabase import AsyncClient

from app.assistant.agent import DocumentAssistant
from app.assistant.deps import AssistantDeps, AssistantModelSettings
from app.assistant.tracing import AssistantTrace
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
from app.config import Settings, settings
from app.database import chats
from app.grounding import GroundingValidator
from app.retrieval.keywords import OpenAIKeywordExtractor
from app.retrieval.retriever import DocumentRetriever
from app.services import AzureOpenAIService


class AssistantRunner(Protocol):
    async def run(self, question, deps, history=(), **kwargs): ...


@dataclass(frozen=True)
class PreparedChatTurn:
    thread_id: UUID
    user_id: UUID
    user_message: InternalUserMessage
    expected_position: int
    history_rows: tuple[dict[str, object], ...]
    trace: AssistantTrace = field(
        default_factory=AssistantTrace.disabled,
        compare=False,
        repr=False,
    )
    cached_assistant: UIMessageResponse | None = None


class ChatTurnOrchestrator:
    """Coordinate current-turn services without retaining request state."""

    def __init__(
        self,
        *,
        settings: Settings,
        supabase: AsyncClient,
        admin_supabase: AsyncClient,
        azure_openai: AzureOpenAIService,
        assistant: DocumentAssistant,
        trace: AssistantTrace | None = None,
    ) -> None:
        self._settings = settings
        self._supabase = supabase
        self._admin_supabase = admin_supabase
        self._azure_openai = azure_openai
        self._assistant: AssistantRunner = assistant
        self._trace = trace or AssistantTrace.disabled()

    async def prepare(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        user_message: InternalUserMessage,
    ) -> PreparedChatTurn:
        prepare_started = time.perf_counter()
        self._trace.emit(
            "chat_thread_load_started",
            "turn.prepare.thread_load",
        )
        _thread, messages, citations = await chats.load_thread(
            self._supabase,
            self._admin_supabase,
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
        self._trace.emit(
            "chat_turn_prepared",
            "turn.prepared",
            stored_message_count=len(messages),
            stored_citation_count=len(citations),
            expected_position=expected_position,
            cached_replay=cached_assistant is not None,
            duration_ms=(time.perf_counter() - prepare_started) * 1000,
        )
        return PreparedChatTurn(
            thread_id=thread_id,
            user_id=user_id,
            user_message=user_message,
            expected_position=expected_position,
            history_rows=tuple(messages),
            trace=self._trace,
            cached_assistant=cached_assistant,
        )

    async def complete(self, turn: PreparedChatTurn) -> UIMessageResponse:
        if turn.cached_assistant is not None:
            turn.trace.emit(
                "chat_turn_cache_replayed",
                "turn.cache_replay",
                assistant_message_id=turn.cached_assistant.id,
                answer_status=turn.cached_assistant.metadata.answer_status,
            )
            turn.trace.emit(
                "chat_turn_completed",
                "turn.completed",
                operational=True,
                cached_replay=True,
                assistant_message_id=turn.cached_assistant.id,
                answer_status=turn.cached_assistant.metadata.answer_status,
                total_duration_ms=turn.trace.elapsed_ms,
            )
            return turn.cached_assistant

        retriever = DocumentRetriever(
            self._supabase,
            self._azure_openai.client,
            OpenAIKeywordExtractor(
                self._azure_openai.client,
                model=self._settings.azure_openai_keyword_deployment,
                trace=turn.trace,
            ),
            embedding_model=self._settings.azure_openai_embedding_deployment,
            embedding_dimensions=self._settings.openai_embedding_dimensions,
            semantic_weight=self._settings.retrieval_semantic_weight,
            lexical_weight=self._settings.retrieval_lexical_weight,
            rrf_k=self._settings.retrieval_rrf_k,
            trace=turn.trace,
        )
        deps = AssistantDeps(
            user_id=turn.user_id,
            thread_id=turn.thread_id,
            retriever=retriever,
            grounding_validator=GroundingValidator(),
            model_settings=AssistantModelSettings.from_app_settings(self._settings),
            trace=turn.trace,
        )
        history = stored_messages_to_history(list(turn.history_rows))
        turn.trace.emit(
            "chat_history_selected",
            "turn.history.selected",
            history=history,
            history_message_count=len(history),
        )
        result = await self._assistant.run(
            turn.user_message.content,
            deps,
            history,
        )

        user_message_id = uuid4()
        assistant_message_id = uuid4()
        citation_ids = tuple(uuid4() for _citation in result.answer.citations)
        parts = assistant_ui_parts(result.answer, citation_ids)
        assistant_data = assistant_message_data(result.answer.status, parts)
        model_usage = result.usage.model_dump(mode="json")
        stored_citations = [
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
        ]
        first_turn_title = derive_thread_title(turn.user_message.content)
        turn.trace.emit(
            "chat_turn_persistence_started",
            "turn.persistence.started",
            expected_position=turn.expected_position,
            user_message_id=str(user_message_id),
            assistant_message_id=str(assistant_message_id),
            answer_status=result.answer.status,
            citation_count=len(result.answer.citations),
            assistant_message_data=assistant_data,
            model_usage=model_usage,
            citations=stored_citations,
            first_turn_title=first_turn_title,
        )
        persistence_started = time.perf_counter()
        persistence = await chats.complete_chat_turn(
            self._admin_supabase,
            turn.thread_id,
            turn.expected_position,
            turn.user_message,
            user_message_id,
            assistant_message_id,
            result.answer.answer,
            assistant_data,
            model_usage,
            stored_citations,
            first_turn_title,
            user_id=turn.user_id,
        )
        turn.trace.emit(
            "chat_turn_persistence_completed",
            "turn.persistence.completed",
            assistant_message_id=str(assistant_message_id),
            assistant_created_at=persistence.assistant_created_at,
            duration_ms=(time.perf_counter() - persistence_started) * 1000,
        )
        turn.trace.emit(
            "chat_turn_completed",
            "turn.completed",
            operational=True,
            assistant_message_id=str(assistant_message_id),
            answer_status=result.answer.status,
            citation_count=len(result.answer.citations),
            requests=result.usage.requests,
            tool_calls=result.usage.tool_calls,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            cost_usd=(
                str(result.usage.cost_usd)
                if result.usage.cost_usd is not None
                else None
            ),
            total_duration_ms=turn.trace.elapsed_ms,
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
    if len(normalized) <= settings.chat_auto_title_max_characters:
        return normalized
    prefix = normalized[: settings.chat_auto_title_max_characters - 1]
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
