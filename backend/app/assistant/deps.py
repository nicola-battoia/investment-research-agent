"""Explicit dependencies and mutable request state for one assistant run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic_ai.models.openai import OpenAIResponsesModelSettings

from app.assistant.evidence import TurnEvidence
from app.assistant.outputs import GroundedAnswer
from app.assistant.tracing import AssistantTrace
from app.retrieval.retriever import DocumentRetriever

if TYPE_CHECKING:
    from app.config import Settings
    from app.grounding.validator import GroundingValidator

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class AssistantModelSettings:
    """Model identity and bounded request settings supplied with every run."""

    model_name: str
    reasoning_effort: ReasoningEffort
    max_output_tokens: int
    parallel_tool_calls: bool = False
    store_responses: bool = False
    text_verbosity: Literal["low", "medium", "high"] = "low"

    @classmethod
    def from_app_settings(cls, settings: Settings) -> AssistantModelSettings:
        return cls(
            model_name=settings.openai_assistant_model,
            reasoning_effort=settings.openai_assistant_reasoning_effort,
            max_output_tokens=settings.openai_assistant_max_output_tokens,
            parallel_tool_calls=settings.assistant_parallel_tool_calls,
            store_responses=settings.openai_store_responses,
            text_verbosity=settings.assistant_text_verbosity,
        )

    def to_pydantic_ai(self) -> OpenAIResponsesModelSettings:
        return OpenAIResponsesModelSettings(
            max_tokens=self.max_output_tokens,
            parallel_tool_calls=self.parallel_tool_calls,
            openai_reasoning_effort=self.reasoning_effort,
            openai_store=self.store_responses,
            openai_text_verbosity=self.text_verbosity,
        )


@dataclass
class ToolCounters:
    search_calls: int = 0
    surrounding_calls: int = 0


@dataclass
class AssistantDeps:
    """Request-scoped services and evidence; never reuse between turns."""

    user_id: UUID
    thread_id: UUID
    retriever: DocumentRetriever
    grounding_validator: GroundingValidator
    model_settings: AssistantModelSettings
    trace: AssistantTrace = field(default_factory=AssistantTrace.disabled)
    evidence: TurnEvidence = field(default_factory=TurnEvidence)
    counters: ToolCounters = field(default_factory=ToolCounters)
    validated_answer: GroundedAnswer | None = None
    last_grounding_error: str | None = None

    def require_fresh_run(self) -> None:
        if (
            not self.evidence.is_empty
            or self.counters.search_calls
            or self.counters.surrounding_calls
            or self.validated_answer is not None
            or self.last_grounding_error is not None
        ):
            raise ValueError("AssistantDeps cannot be reused across assistant turns")
