"""AI SDK-compatible streaming for validated, persisted chat turns."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from fastapi import Request
from openai import OpenAIError
from postgrest import APIError
from pydantic_ai.exceptions import (
    ModelAPIError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)

from app.chat.messages import (
    CitationPart,
    SourceUrlPart,
    TextPart,
    UIMessageResponse,
)
from app.chat.orchestrator import ChatTurnOrchestrator, PreparedChatTurn
from app.config import settings
from app.database.chats import ChatPositionConflictError, ChatThreadNotFoundError
from app.grounding import GroundingFailureError


@dataclass(frozen=True)
class StreamFailure:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class UsageLimitFailure:
    limit: str
    code: str
    message: str


USAGE_LIMIT_FAILURES = (
    UsageLimitFailure(
        "per_request_input_tokens_limit",
        "assistant_context_limit",
        "The conversation and source context are too large for this turn. "
        "Try a narrower question or start a new chat.",
    ),
    UsageLimitFailure(
        "input_tokens_limit",
        "assistant_input_tokens_limit",
        "The research assistant reached its cumulative input-token limit. "
        "Try a narrower question or start a new chat.",
    ),
    UsageLimitFailure(
        "output_tokens_limit",
        "assistant_output_tokens_limit",
        "The research assistant reached its response-token limit. "
        "Try a narrower question.",
    ),
    UsageLimitFailure(
        "total_tokens_limit",
        "assistant_total_tokens_limit",
        "The research assistant reached its total-token limit. "
        "Try a narrower question.",
    ),
    UsageLimitFailure(
        "tool_calls_limit",
        "assistant_tool_calls_limit",
        "The research assistant reached its tool-call limit. Try a narrower question.",
    ),
    UsageLimitFailure(
        "request_limit",
        "assistant_request_limit",
        "The research assistant reached its model-request limit. "
        "Try a narrower question.",
    ),
    UsageLimitFailure(
        "cost_limit",
        "assistant_cost_limit",
        "The research assistant reached its configured cost limit. "
        "Try a narrower question.",
    ),
)
UNKNOWN_USAGE_LIMIT_FAILURE = UsageLimitFailure(
    "unknown",
    "assistant_usage_limit",
    "The research assistant reached a configured usage limit. Try a narrower question.",
)
_SAFE_UPSTREAM_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


async def chat_turn_events(
    *,
    request: Request,
    orchestrator: ChatTurnOrchestrator,
    turn: PreparedChatTurn,
    timeout_seconds: int,
) -> AsyncIterator[str]:
    trace = turn.trace
    trace.emit(
        "chat_stream_started",
        "stream.started",
        timeout_seconds=timeout_seconds,
    )
    yield _status_event()
    task = asyncio.create_task(orchestrator.complete(turn))
    try:
        async with asyncio.timeout(timeout_seconds):
            completed = None
            while completed is None:
                done, _pending = await asyncio.wait(
                    {task},
                    timeout=settings.chat_stream_heartbeat_seconds,
                )
                if task in done:
                    completed = task.result()
                    break
                if await request.is_disconnected():
                    await _cancel(task)
                    trace.emit(
                        "chat_stream_disconnected",
                        "stream.disconnected",
                        level="warning",
                        operational=True,
                        failed_after_stage=trace.last_stage,
                    )
                    return
                yield _status_event()
        if completed is None:
            return
    except TimeoutError:
        await _cancel(task)
        failed_after_stage = trace.last_stage
        trace.emit(
            "chat_turn_timed_out",
            "stream.timeout",
            level="warning",
            operational=True,
            error_code="turn_timeout",
            retryable=True,
            failed_after_stage=failed_after_stage,
            timeout_seconds=timeout_seconds,
        )
        async for event in _failure_events(
            StreamFailure(
                code="turn_timeout",
                message="The research turn took too long. Please try again.",
                retryable=True,
            )
        ):
            yield event
        return
    except asyncio.CancelledError:
        await _cancel(task)
        trace.emit(
            "chat_stream_cancelled",
            "stream.cancelled",
            level="warning",
            operational=True,
            failed_after_stage=trace.last_stage,
        )
        raise
    except Exception as error:  # noqa: BLE001 - HTTP stream boundary maps all failures.
        failure = _mapped_failure(error)
        failed_after_stage = trace.last_stage
        trace.emit(
            "chat_turn_failed",
            "stream.failed",
            level="error",
            operational=True,
            exc_info=True,
            error_class=type(error).__name__,
            error_code=failure.code,
            error_message=str(error),
            retryable=failure.retryable,
            failed_after_stage=failed_after_stage,
            **_error_log_context(error),
        )
        async for event in _failure_events(failure):
            yield event
        return

    if await request.is_disconnected():
        trace.emit(
            "chat_stream_disconnected",
            "stream.disconnected",
            level="warning",
            operational=True,
            failed_after_stage=trace.last_stage,
            persisted=True,
        )
        return
    async for event in _completed_turn_events(completed):
        yield event
    trace.emit(
        "chat_stream_completed",
        "stream.completed",
        assistant_message_id=completed.id,
        answer_status=completed.metadata.answer_status,
        total_duration_ms=trace.elapsed_ms,
    )


async def _completed_turn_events(message: UIMessageResponse) -> AsyncIterator[str]:
    metadata = message.metadata.model_dump(mode="json", by_alias=True)
    yield _event(
        {
            "type": "start",
            "messageId": message.id,
            "messageMetadata": metadata,
        }
    )
    for index, part in enumerate(message.parts):
        if isinstance(part, TextPart):
            text_id = f"{message.id}-text-{index}"
            yield _event({"type": "text-start", "id": text_id})
            for offset in range(
                0,
                len(part.text),
                settings.chat_stream_text_delta_characters,
            ):
                yield _event(
                    {
                        "type": "text-delta",
                        "id": text_id,
                        "delta": part.text[
                            offset : offset + settings.chat_stream_text_delta_characters
                        ],
                    }
                )
                await asyncio.sleep(0)
            yield _event({"type": "text-end", "id": text_id})
        elif isinstance(part, SourceUrlPart | CitationPart):
            yield _event(part.model_dump(mode="json", by_alias=True))
    yield _event(
        {
            "type": "finish",
            "finishReason": "stop",
            "messageMetadata": metadata,
        }
    )
    yield "data: [DONE]\n\n"


async def _failure_events(failure: StreamFailure) -> AsyncIterator[str]:
    yield _event(
        {
            "type": "data-turn-error",
            "data": {
                "code": failure.code,
                "message": failure.message,
                "retryable": failure.retryable,
            },
            "transient": True,
        }
    )
    yield _event({"type": "error", "errorText": failure.message})
    yield "data: [DONE]\n\n"


def _status_event() -> str:
    return _event(
        {
            "type": "data-turn-status",
            "data": {
                "state": "researching",
                "message": "Preparing response…",
            },
            "transient": True,
        }
    )


def _mapped_failure(error: Exception) -> StreamFailure:
    if isinstance(error, ChatPositionConflictError):
        return StreamFailure(
            "turn_conflict",
            "Another message completed in this chat. Refresh and try again.",
            True,
        )
    if isinstance(error, ChatThreadNotFoundError):
        return StreamFailure(
            "thread_missing",
            "This chat no longer exists.",
            False,
        )
    if isinstance(error, GroundingFailureError):
        return StreamFailure(
            "grounding_failed",
            "The answer could not be verified against its filing sources.",
            True,
        )
    if isinstance(error, APIError):
        return StreamFailure(
            "database_unavailable",
            "The chat database is temporarily unavailable.",
            True,
        )
    if isinstance(error, UsageLimitExceeded):
        usage_failure = _usage_limit_failure(error)
        return StreamFailure(
            usage_failure.code,
            usage_failure.message,
            True,
        )
    if isinstance(
        error,
        (OpenAIError, ModelAPIError, UnexpectedModelBehavior),
    ):
        return StreamFailure(
            "assistant_unavailable",
            "The research assistant is temporarily unavailable.",
            True,
        )
    return StreamFailure(
        "turn_failed",
        "The research turn could not be completed.",
        True,
    )


def _usage_limit_failure(error: UsageLimitExceeded) -> UsageLimitFailure:
    message = str(error)
    return next(
        (failure for failure in USAGE_LIMIT_FAILURES if failure.limit in message),
        UNKNOWN_USAGE_LIMIT_FAILURE,
    )


def _error_log_context(error: Exception) -> dict[str, str | int]:
    context: dict[str, str | int] = {}
    if isinstance(error, UsageLimitExceeded):
        context["usage_limit"] = _usage_limit_failure(error).limit
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and 100 <= status_code <= 599:
        context["upstream_status_code"] = status_code
    upstream_code = _upstream_error_code(error)
    if upstream_code is not None:
        context["upstream_error_code"] = upstream_code
    return context


def _upstream_error_code(error: Exception) -> str | None:
    candidates: list[object] = [getattr(error, "code", None)]
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        candidates.append(body.get("code"))
        nested = body.get("error")
        if isinstance(nested, Mapping):
            candidates.append(nested.get("code"))
    for candidate in candidates:
        if isinstance(candidate, str) and _SAFE_UPSTREAM_CODE.fullmatch(candidate):
            return candidate
    return None


async def _cancel(task: asyncio.Task[object]) -> None:
    if task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _event(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
