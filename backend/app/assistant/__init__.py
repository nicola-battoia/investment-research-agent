"""Grounded SEC-filing assistant."""

from app.assistant.agent import DocumentAssistant, create_document_assistant
from app.assistant.deps import AssistantDeps, AssistantModelSettings
from app.assistant.outputs import (
    AssistantRunResult,
    Citation,
    GroundedAnswer,
    HistoryMessage,
)

__all__ = [
    "AssistantDeps",
    "AssistantModelSettings",
    "AssistantRunResult",
    "Citation",
    "DocumentAssistant",
    "GroundedAnswer",
    "HistoryMessage",
    "create_document_assistant",
]
