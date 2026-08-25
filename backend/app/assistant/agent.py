"""Injectable PydanticAI document agent and controlled run boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from openai import AsyncOpenAI
from pydantic_ai import Agent, ModelRetry, NativeOutput, RunContext, UsageLimits
from pydantic_ai.agent import EventStreamHandler
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

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
from app.grounding.validator import (
    GroundingFailureError,
    GroundingValidationError,
)

if TYPE_CHECKING:
    from app.config import Settings

MAX_MODEL_REQUESTS = 12
MAX_TOOL_CALLS = 12
MAX_TOTAL_OUTPUT_TOKENS = 6_000
MAX_REQUEST_INPUT_TOKENS = 64_000
MAX_QUESTION_CHARACTERS = 10_000


class DocumentAssistant:
    """Run a stateless agent with fresh dependencies for every user turn."""

    def __init__(self, model: Model) -> None:
        self._agent = Agent(
            model,
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
            retries={"tools": 1, "output": 1},
            tool_timeout=60,
        )

        @self._agent.output_validator
        async def validate_grounding(
            ctx: RunContext[AssistantDeps],
            output: DraftGroundedAnswer,
        ) -> DraftGroundedAnswer:
            try:
                ctx.deps.validated_answer = ctx.deps.grounding_validator.validate(
                    output,
                    evidence=ctx.deps.evidence.passages,
                    read_source_ids=ctx.deps.evidence.read_source_ids,
                    search_calls=ctx.deps.counters.search_calls,
                )
            except GroundingValidationError as error:
                ctx.deps.last_grounding_error = str(error)
                if ctx.retry < ctx.max_retries:
                    raise ModelRetry(
                        "The answer failed grounding validation. Correct it without "
                        f"inventing evidence: {error}"
                    ) from error
                raise GroundingFailureError(
                    f"Grounding validation failed after correction: {error}"
                ) from error
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
        if len(question) > MAX_QUESTION_CHARACTERS:
            raise ValueError(
                f"Assistant question cannot exceed {MAX_QUESTION_CHARACTERS} characters"
            )
        deps.require_fresh_run()
        result = await self._agent.run(
            question,
            deps=deps,
            message_history=build_message_history(history),
            model_settings=deps.model_settings.to_pydantic_ai(),
            usage_limits=UsageLimits(
                request_limit=MAX_MODEL_REQUESTS,
                tool_calls_limit=MAX_TOOL_CALLS,
                output_tokens_limit=MAX_TOTAL_OUTPUT_TOKENS,
                per_request_input_tokens_limit=MAX_REQUEST_INPUT_TOKENS,
            ),
            event_stream_handler=event_stream_handler,
        )
        if deps.validated_answer is None:
            raise GroundingFailureError(
                "The assistant completed without a validated grounded answer"
            )
        return AssistantRunResult(
            answer=deps.validated_answer,
            usage=AssistantUsage.from_run_usage(result.usage),
        )


def create_document_assistant(
    settings: Settings,
    openai_client: AsyncOpenAI | None = None,
) -> DocumentAssistant:
    """Create the reusable model boundary without request-scoped retrieval state."""
    if openai_client is None:
        openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            max_retries=3,
        )
    model = OpenAIResponsesModel(
        settings.openai_assistant_model,
        provider=OpenAIProvider(openai_client=openai_client),
    )
    return DocumentAssistant(model)
