"""Injectable PydanticAI document agent and controlled run boundary."""

from __future__ import annotations

import time
from collections.abc import Sequence

from pydantic_ai import Agent, ModelRetry, NativeOutput, RunContext, UsageLimits
from pydantic_ai.agent import EventStreamHandler
from pydantic_ai.models import Model

from app.assistant.deps import AssistantDeps
from app.assistant.history import build_message_history
from app.assistant.outputs import (
    AssistantRunResult,
    AssistantUsage,
    DraftGroundedAnswer,
    HistoryMessage,
)
from app.assistant.policy import (
    ASSISTANT_INSTRUCTIONS,
    current_spain_time_instruction,
)
from app.assistant.tools import (
    read_chunk,
    read_surrounding_chunks,
    search_filings,
)
from app.assistant.tracing import create_assistant_trace_hooks, grounding_reason
from app.config import Settings, settings
from app.grounding.validator import (
    GroundingFailureError,
    GroundingValidationError,
)
from app.services import AzureOpenAIService
from app.telemetry import assistant_turn_span, instrument_assistant_model


class DocumentAssistant:
    """Run a stateless agent with fresh dependencies for every user turn."""

    def __init__(
        self,
        model: Model,
        app_settings: Settings = settings,
        *,
        count_tokens_before_request: bool = True,
    ) -> None:
        self._settings = app_settings
        self._count_tokens_before_request = count_tokens_before_request
        self._agent = Agent(
            instrument_assistant_model(model, app_settings),
            name="document_copilot",
            deps_type=AssistantDeps,
            output_type=NativeOutput(
                DraftGroundedAnswer,
                name="grounded_document_answer",
                description=(
                    "A validated SEC-filing answer, evidence or advice refusal, "
                    "conversational onboarding reply, or out-of-scope redirect."
                ),
                strict=True,
            ),
            instructions=[ASSISTANT_INSTRUCTIONS, current_spain_time_instruction],
            tools=[search_filings, read_chunk, read_surrounding_chunks],
            capabilities=[create_assistant_trace_hooks()],
            retries={
                "tools": app_settings.assistant_tool_retries,
                "output": app_settings.assistant_output_retries,
            },
            tool_timeout=app_settings.assistant_tool_timeout_seconds,
        )

        @self._agent.output_validator
        async def validate_grounding(
            ctx: RunContext[AssistantDeps],
            output: DraftGroundedAnswer,
        ) -> DraftGroundedAnswer:
            ctx.deps.trace.emit(
                "assistant_grounding_proposed",
                "assistant.grounding.proposed",
                selected_status=output.status,
                draft=output,
                search_calls=ctx.deps.counters.search_calls,
                surrounding_calls=ctx.deps.counters.surrounding_calls,
                evidence_count=len(ctx.deps.evidence.passages),
                read_source_count=len(ctx.deps.evidence.read_source_ids),
                evidence_source_ids=tuple(ctx.deps.evidence.passages),
                read_source_ids=tuple(sorted(ctx.deps.evidence.read_source_ids)),
            )
            try:
                ctx.deps.validated_answer = ctx.deps.grounding_validator.validate(
                    output,
                    evidence=ctx.deps.evidence.passages,
                    read_source_ids=ctx.deps.evidence.read_source_ids,
                    search_calls=ctx.deps.counters.search_calls,
                )
            except GroundingValidationError as error:
                ctx.deps.last_grounding_error = str(error)
                retry_available = ctx.retry < ctx.max_retries
                ctx.deps.trace.emit(
                    "assistant_grounding_rejected",
                    "assistant.grounding.rejected",
                    level="warning",
                    selected_status=output.status,
                    reason=str(error),
                    error_class=type(error).__name__,
                    retry=ctx.retry,
                    max_retries=ctx.max_retries,
                    retry_available=retry_available,
                )
                if retry_available:
                    raise ModelRetry(
                        "The answer failed grounding validation. Correct every listed "
                        f"problem in one response without inventing evidence: {error}"
                    ) from error
                raise GroundingFailureError(
                    f"Grounding validation failed after correction: {error}"
                ) from error
            ctx.deps.trace.emit(
                "assistant_grounding_accepted",
                "assistant.grounding.accepted",
                selected_status=output.status,
                reason=grounding_reason(output.status),
                grounding_reason=grounding_reason(output.status),
                citation_count=len(ctx.deps.validated_answer.citations),
                search_calls=ctx.deps.counters.search_calls,
                read_source_count=len(ctx.deps.evidence.read_source_ids),
                read_source_ids=tuple(sorted(ctx.deps.evidence.read_source_ids)),
            )
            return output

    async def run(
        self,
        question: str,
        deps: AssistantDeps,
        history: Sequence[HistoryMessage] = (),
        *,
        event_stream_handler: EventStreamHandler[AssistantDeps] | None = None,
    ) -> AssistantRunResult:
        """Return only a validated answer/refusal and normalized model usage."""
        question = question.strip()
        if not question:
            raise ValueError("Assistant question cannot be empty")
        if len(question) > self._settings.assistant_max_message_characters:
            raise ValueError(
                "Assistant question cannot exceed "
                f"{self._settings.assistant_max_message_characters} characters"
            )
        deps.require_fresh_run()
        run_started = time.perf_counter()
        deps.trace.emit(
            "assistant_run_started",
            "assistant.run.started",
            question=question,
            history=history,
            model=deps.model_settings.model_name,
            model_settings=deps.model_settings,
        )
        with assistant_turn_span(deps.trace.trace_id, deps.model_settings.model_name):
            result = await self._agent.run(
                question,
                deps=deps,
                message_history=build_message_history(history),
                model_settings=deps.model_settings.to_pydantic_ai(),
                usage_limits=UsageLimits(
                    request_limit=self._settings.assistant_max_model_requests,
                    tool_calls_limit=self._settings.assistant_max_tool_calls,
                    input_tokens_limit=self._settings.assistant_max_total_input_tokens,
                    output_tokens_limit=self._settings.assistant_max_total_output_tokens,
                    per_request_input_tokens_limit=(
                        self._settings.assistant_max_request_input_tokens
                    ),
                    count_tokens_before_request=self._count_tokens_before_request,
                ),
                event_stream_handler=event_stream_handler,
            )
        if deps.validated_answer is None:
            raise GroundingFailureError(
                "The assistant completed without a validated grounded answer"
            )
        normalized = AssistantRunResult(
            answer=deps.validated_answer,
            usage=AssistantUsage.from_run_usage(result.usage),
        )
        deps.trace.emit(
            "assistant_run_completed",
            "assistant.run.completed",
            answer=normalized.answer,
            usage=normalized.usage,
            search_calls=deps.counters.search_calls,
            surrounding_calls=deps.counters.surrounding_calls,
            evidence_count=len(deps.evidence.passages),
            answer_status=normalized.answer.status,
            requests=normalized.usage.requests,
            tool_calls=normalized.usage.tool_calls,
            input_tokens=normalized.usage.input_tokens,
            output_tokens=normalized.usage.output_tokens,
            total_tokens=normalized.usage.total_tokens,
            cost_usd=(
                str(normalized.usage.cost_usd)
                if normalized.usage.cost_usd is not None
                else None
            ),
            duration_ms=(time.perf_counter() - run_started) * 1000,
        )
        return normalized


def create_document_assistant(
    app_settings: Settings,
    azure_openai: AzureOpenAIService,
) -> DocumentAssistant:
    """Create the reusable model boundary without request-scoped retrieval state."""
    model = azure_openai.create_responses_model(
        app_settings.azure_openai_assistant_deployment,
        app_settings.openai_assistant_model,
    )
    return DocumentAssistant(model, app_settings)
