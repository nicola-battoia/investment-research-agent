"""Bounded, request-local diagnostics for one assistant turn."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, SecretStr
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import RunContext, ToolDefinition

from app.config import settings

if TYPE_CHECKING:
    from app.assistant.deps import AssistantDeps
    from app.config import Settings

TraceMode = Literal["off", "summary", "full"]

_REDACTED = "[REDACTED]"
_OMITTED = "[OMITTED]"
_SENSITIVE_KEY_PARTS = (
    "access_token",
    "api_key",
    "authorization",
    "database_url",
    "password",
    "refresh_token",
    "secret",
    "service_role",
)
_OMITTED_KEY_PARTS = (
    "encrypted_content",
    "provider_details",
    "reasoning_content",
    "signature",
)
_SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)


@dataclasses.dataclass
class AssistantTrace:
    """Emit ordered diagnostics without sharing mutable state across turns."""

    trace_id: str
    thread_id: str
    user_id: str
    client_message_id: str
    mode: TraceMode
    max_content_characters: int
    _started: float = dataclasses.field(default_factory=time.perf_counter, repr=False)
    _sequence: int = dataclasses.field(default=0, init=False, repr=False)
    _model_request_index: int = dataclasses.field(default=0, init=False, repr=False)
    _active_model_request: int | None = dataclasses.field(
        default=None, init=False, repr=False
    )
    _model_started: dict[int, float] = dataclasses.field(
        default_factory=dict, init=False, repr=False
    )
    _tool_indexes: dict[str, int] = dataclasses.field(
        default_factory=dict, init=False, repr=False
    )
    _tool_started: dict[str, float] = dataclasses.field(
        default_factory=dict, init=False, repr=False
    )
    _last_stage: str = dataclasses.field(default="turn.created", init=False)

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        thread_id: UUID,
        user_id: UUID,
        client_message_id: str,
    ) -> AssistantTrace:
        return cls(
            trace_id=str(uuid4()),
            thread_id=str(thread_id),
            user_id=str(user_id),
            client_message_id=client_message_id,
            mode=settings.assistant_trace_mode,
            max_content_characters=settings.assistant_trace_max_content_characters,
        )

    @classmethod
    def disabled(cls) -> AssistantTrace:
        return cls(
            trace_id="disabled",
            thread_id="disabled",
            user_id="disabled",
            client_message_id="disabled",
            mode="off",
            max_content_characters=settings.assistant_trace_summary_characters,
        )

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def last_stage(self) -> str:
        return self._last_stage

    @property
    def elapsed_ms(self) -> float:
        return _elapsed_ms(self._started)

    def emit(
        self,
        event: str,
        stage: str,
        *,
        level: Literal["debug", "info", "warning", "error"] = "info",
        exc_info: bool = False,
        **fields: object,
    ) -> None:
        if not self.enabled:
            return
        self._sequence += 1
        self._last_stage = stage
        logger = structlog.get_logger("assistant_trace")
        log = getattr(logger, level)
        log(
            event,
            trace_id=self.trace_id,
            sequence=self._sequence,
            stage=stage,
            elapsed_ms=round(self.elapsed_ms, 3),
            thread_id=self.thread_id,
            user_id=self.user_id,
            client_message_id=self.client_message_id,
            last_stage=self._last_stage,
            exc_info=exc_info,
            **self.serialize(fields),
        )

    def serialize(self, value: object) -> Any:
        return _serialize(
            value,
            mode=self.mode,
            max_content_characters=self.max_content_characters,
        )

    def begin_model_request(self) -> int:
        self._model_request_index += 1
        index = self._model_request_index
        self._active_model_request = index
        self._model_started[index] = time.perf_counter()
        return index

    def current_model_request(self) -> int | None:
        if self._active_model_request is not None:
            return self._active_model_request
        return self._model_request_index or None

    def finish_model_request(self, index: int | None = None) -> float | None:
        active = index or self._active_model_request
        if active is None:
            return None
        started = self._model_started.pop(active, None)
        if self._active_model_request == active:
            self._active_model_request = None
        return _elapsed_ms(started) if started is not None else None

    def begin_tool_call(self, tool_call_id: str) -> int:
        index = self._tool_indexes.get(tool_call_id)
        if index is None:
            index = len(self._tool_indexes) + 1
            self._tool_indexes[tool_call_id] = index
        self._tool_started[tool_call_id] = time.perf_counter()
        return index

    def tool_index(self, tool_call_id: str) -> int | None:
        return self._tool_indexes.get(tool_call_id)

    def finish_tool_call(self, tool_call_id: str) -> float | None:
        started = self._tool_started.pop(tool_call_id, None)
        return _elapsed_ms(started) if started is not None else None


def serialize_model_messages(messages: list[ModelMessage]) -> object:
    """Convert semantic model messages while omitting private reasoning payloads."""
    dumped = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    return _remove_thinking_content(dumped)


def serialize_model_response(response: ModelResponse) -> dict[str, object]:
    dumped = ModelMessagesTypeAdapter.dump_python([response], mode="json")[0]
    cleaned = _remove_thinking_content(dumped)
    assert isinstance(cleaned, dict)
    return cleaned


def serialize_request_context(
    request_context: ModelRequestContext,
) -> dict[str, object]:
    parameters = request_context.model_request_parameters
    return {
        "model": request_context.model_id or request_context.model.model_id,
        "streaming": request_context.streaming,
        "model_settings": dict(request_context.model_settings or {}),
        "messages": serialize_model_messages(request_context.messages),
        "function_tools": [
            _serialize_tool_definition(item) for item in parameters.function_tools
        ],
        "output_tools": [
            _serialize_tool_definition(item) for item in parameters.output_tools
        ],
        "output_mode": parameters.output_mode,
        "output_object": (
            dataclasses.asdict(parameters.output_object)
            if parameters.output_object is not None
            else None
        ),
        "allow_text_output": parameters.allow_text_output,
        "thinking": parameters.thinking,
    }


def embedding_summary(vector: Sequence[float]) -> dict[str, object]:
    """Describe an embedding without exposing the vector itself."""
    encoded = json.dumps(list(vector), separators=(",", ":")).encode()
    return {
        "dimensions": len(vector),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "l2_norm": round(math.sqrt(sum(value * value for value in vector)), 6),
    }


def grounding_reason(status: str) -> str:
    return {
        "conversational": "non_retrieval_without_search",
        "out_of_scope": "non_retrieval_without_search",
        "supported": "supported_with_resolved_citations",
        "insufficient_evidence": "insufficient_after_search",
        "investment_advice_refused": "advice_refusal_validated",
    }[status]


def create_assistant_trace_hooks() -> Hooks[AssistantDeps]:
    """Build passive PydanticAI hooks backed by request-local trace state."""
    hooks: Hooks[AssistantDeps] = Hooks(id="document_copilot_trace")

    @hooks.on.before_model_request
    async def before_model_request(
        ctx: RunContext[AssistantDeps],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        trace = ctx.deps.trace
        if not trace.enabled:
            return request_context
        request_index = trace.begin_model_request()
        trace.emit(
            "assistant_model_request",
            "assistant.model.request",
            model_request_index=request_index,
            run_step=ctx.run_step,
            input=serialize_request_context(request_context),
        )
        return request_context

    @hooks.on.after_model_request
    async def after_model_request(
        ctx: RunContext[AssistantDeps],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        trace = ctx.deps.trace
        if not trace.enabled:
            return response
        request_index = trace.current_model_request()
        duration_ms = trace.finish_model_request(request_index)
        trace.emit(
            "assistant_model_response",
            "assistant.model.response",
            model_request_index=request_index,
            run_step=ctx.run_step,
            duration_ms=duration_ms,
            model=request_context.model_id or request_context.model.model_id,
            provider_response_id=response.provider_response_id,
            finish_reason=response.finish_reason,
            output=serialize_model_response(response),
        )
        return response

    @hooks.on.model_request_error
    async def model_request_error(
        ctx: RunContext[AssistantDeps],
        *,
        request_context: ModelRequestContext,
        error: Exception,
    ) -> ModelResponse:
        trace = ctx.deps.trace
        if not trace.enabled:
            raise error
        request_index = trace.current_model_request()
        trace.emit(
            "assistant_model_request_failed",
            "assistant.model.error",
            level="error",
            model_request_index=request_index,
            run_step=ctx.run_step,
            duration_ms=trace.finish_model_request(request_index),
            model=request_context.model_id or request_context.model.model_id,
            error_class=type(error).__name__,
            error_message=str(error),
        )
        raise error

    @hooks.on.tool_validate_error
    async def tool_validate_error(
        ctx: RunContext[AssistantDeps],
        *,
        call,
        tool_def,
        args,
        error,
    ):
        if not ctx.deps.trace.enabled:
            raise error
        ctx.deps.trace.emit(
            "assistant_tool_validation_failed",
            "assistant.tool.validation_failed",
            level="warning",
            model_request_index=ctx.deps.trace.current_model_request(),
            tool_name=call.tool_name,
            tool_call_id=call.tool_call_id,
            arguments=args,
            error_class=type(error).__name__,
            error_message=str(error),
        )
        raise error

    @hooks.on.tool_execute
    async def tool_execute(
        ctx: RunContext[AssistantDeps],
        *,
        call,
        tool_def,
        args,
        handler,
    ):
        trace = ctx.deps.trace
        if not trace.enabled:
            return await handler(args)
        tool_index = trace.begin_tool_call(call.tool_call_id)
        trace.emit(
            "assistant_tool_started",
            "assistant.tool.started",
            tool_index=tool_index,
            tool_name=tool_def.name,
            tool_call_id=call.tool_call_id,
            arguments=args,
        )
        try:
            result = await handler(args)
        except Exception as error:
            trace.emit(
                "assistant_tool_failed",
                "assistant.tool.failed",
                level="warning",
                tool_index=tool_index,
                tool_name=tool_def.name,
                tool_call_id=call.tool_call_id,
                duration_ms=trace.finish_tool_call(call.tool_call_id),
                error_class=type(error).__name__,
                error_message=str(error),
            )
            raise
        trace.emit(
            "assistant_tool_completed",
            "assistant.tool.completed",
            tool_index=tool_index,
            tool_name=tool_def.name,
            tool_call_id=call.tool_call_id,
            duration_ms=trace.finish_tool_call(call.tool_call_id),
            result=result,
        )
        return result

    @hooks.on.output_validate_error
    async def output_validate_error(
        ctx: RunContext[AssistantDeps],
        *,
        output_context,
        output,
        error,
    ):
        if not ctx.deps.trace.enabled:
            raise error
        ctx.deps.trace.emit(
            "assistant_output_validation_failed",
            "assistant.output.validation_failed",
            level="warning",
            retry=ctx.retry,
            max_retries=ctx.max_retries,
            output=output,
            error_class=type(error).__name__,
            error_message=str(error),
        )
        raise error

    return hooks


def _serialize_tool_definition(tool: ToolDefinition) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters_json_schema": tool.parameters_json_schema,
        "strict": tool.strict,
        "sequential": tool.sequential,
        "kind": tool.kind,
        "return_schema": tool.return_schema,
    }


def _serialize(value: object, *, mode: TraceMode, max_content_characters: int) -> Any:
    if isinstance(value, SecretStr):
        return _REDACTED
    if isinstance(value, BaseModel):
        return _serialize(
            value.model_dump(mode="json"),
            mode=mode,
            max_content_characters=max_content_characters,
        )
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _serialize(
            dataclasses.asdict(value),
            mode=mode,
            max_content_characters=max_content_characters,
        )
    if isinstance(value, Mapping):
        result = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized_key = key.casefold()
            if any(part in normalized_key for part in _OMITTED_KEY_PARTS):
                result[key] = _OMITTED
            elif any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
                result[key] = _REDACTED
            else:
                result[key] = _serialize(
                    item,
                    mode=mode,
                    max_content_characters=max_content_characters,
                )
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [
            _serialize(
                item,
                mode=mode,
                max_content_characters=max_content_characters,
            )
            for item in value
        ]
    if isinstance(value, str):
        return _bounded_text(
            _redact_text(value),
            mode=mode,
            max_content_characters=max_content_characters,
        )
    if isinstance(value, UUID | date | datetime | Decimal | Enum):
        return str(value)
    if isinstance(value, bytes | bytearray):
        return {
            "bytes": len(value),
            "sha256": hashlib.sha256(bytes(value)).hexdigest(),
        }
    if value is None or isinstance(value, bool | int | float):
        return value
    return _bounded_text(
        _redact_text(repr(value)),
        mode=mode,
        max_content_characters=max_content_characters,
    )


def _bounded_text(
    value: str,
    *,
    mode: TraceMode,
    max_content_characters: int,
) -> str | dict[str, object]:
    limit = (
        max_content_characters
        if mode == "full"
        else min(settings.assistant_trace_summary_characters, max_content_characters)
    )
    if len(value) <= limit:
        return value
    return {
        "preview": value[:limit],
        "characters": len(value),
        "omitted_characters": len(value) - limit,
        "sha256": hashlib.sha256(value.encode()).hexdigest(),
        "truncated": True,
    }


def _redact_text(value: str) -> str:
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(_REDACTED, value)
    return value


def _remove_thinking_content(value: object) -> object:
    if isinstance(value, list):
        return [_remove_thinking_content(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("part_kind") == "thinking":
        return {"part_kind": "thinking", "content": _OMITTED}
    return {key: _remove_thinking_content(item) for key, item in value.items()}


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
