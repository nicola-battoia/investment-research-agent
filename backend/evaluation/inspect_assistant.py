"""Interactive diagnostics for one live grounded-assistant turn."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    RetryPromptPart,
    ToolReturnPart,
)

from app.assistant.agent import DocumentAssistant, create_document_assistant
from app.assistant.deps import AssistantDeps, AssistantModelSettings
from app.assistant.outputs import (
    AssistantRunResult,
    HistoryMessage,
    ReadablePassage,
    SearchToolResult,
)
from app.config import settings
from app.database.supabase import create_user_supabase_client
from app.grounding import GroundingValidator
from app.retrieval.keywords import OpenAIKeywordExtractor
from app.retrieval.models import SourcePassage
from app.retrieval.retriever import DocumentRetriever
from app.services import AzureOpenAIService

logger = logging.getLogger("assistant-inspector")


@dataclass(frozen=True)
class InspectedEvidence:
    """One current-turn source and how the assistant used it."""

    source_id: str
    passage: SourcePassage
    was_read: bool
    was_cited: bool


@dataclass(frozen=True)
class AssistantInspection:
    """Validated result plus the complete current-turn evidence trace."""

    result: AssistantRunResult
    evidence: tuple[InspectedEvidence, ...]
    search_calls: int
    surrounding_calls: int


def configure_logging() -> None:
    """Show compact assistant diagnostics in an interactive window."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(logging.INFO)


async def build_live_assistant(
    access_token: str,
) -> tuple[DocumentAssistant, AssistantDeps, AzureOpenAIService]:
    """Build the production assistant with an authenticated user-scoped retriever."""
    access_token = access_token.strip()
    if not access_token:
        raise ValueError("A Supabase access token is required")

    supabase = await create_user_supabase_client(settings, access_token)
    auth_response = await supabase.auth.get_user(access_token)
    azure_openai = AzureOpenAIService(settings)
    openai_client = azure_openai.client
    retriever = DocumentRetriever(
        supabase,
        openai_client,
        OpenAIKeywordExtractor(
            openai_client,
            model=settings.azure_openai_keyword_deployment,
        ),
        embedding_model=settings.azure_openai_embedding_deployment,
        embedding_dimensions=settings.openai_embedding_dimensions,
    )
    deps = AssistantDeps(
        user_id=UUID(auth_response.user.id),
        thread_id=uuid4(),
        retriever=retriever,
        grounding_validator=GroundingValidator(),
        model_settings=AssistantModelSettings.from_app_settings(settings),
    )
    logger.info(
        "Models: assistant=%s (%s reasoning), embedding=%s, keywords=%s",
        settings.openai_assistant_model,
        settings.openai_assistant_reasoning_effort,
        settings.openai_embedding_model,
        settings.openai_keyword_model,
    )
    return create_document_assistant(settings, azure_openai), deps, azure_openai


async def inspect_assistant(
    question: str,
    access_token: str,
    history: Sequence[HistoryMessage] = (),
    *,
    snippet_chars: int = 320,
) -> AssistantInspection:
    """Run the live assistant and log its tool, evidence, citation, and usage trace."""
    assistant, deps, azure_openai = await build_live_assistant(access_token)
    try:
        return await run_assistant_inspection(
            question,
            assistant,
            deps,
            history,
            snippet_chars=snippet_chars,
        )
    finally:
        await azure_openai.close()


async def run_assistant_inspection(
    question: str,
    assistant: DocumentAssistant,
    deps: AssistantDeps,
    history: Sequence[HistoryMessage] = (),
    *,
    snippet_chars: int = 320,
) -> AssistantInspection:
    """Run an injected assistant with the same diagnostics used by the playground."""
    if snippet_chars < 80:
        raise ValueError("Snippet length must be at least 80 characters")
    configure_logging()
    logger.info("\nQUESTION\n%s", question.strip())

    async def log_events(
        _ctx: RunContext[AssistantDeps],
        events: AsyncIterable[AgentStreamEvent],
    ) -> None:
        async for event in events:
            if isinstance(event, FunctionToolCallEvent):
                logger.info(
                    "\nTOOL CALL  %s\n%s",
                    event.part.tool_name,
                    event.part.args_as_dict(),
                )
            elif isinstance(event, FunctionToolResultEvent):
                _log_tool_result(event)

    result = await assistant.run(
        question,
        deps,
        history,
        event_stream_handler=log_events,
    )
    cited_ids = {citation.source_id for citation in result.answer.citations}
    evidence = tuple(
        InspectedEvidence(
            source_id=source_id,
            passage=passage,
            was_read=source_id in deps.evidence.read_source_ids,
            was_cited=source_id in cited_ids,
        )
        for source_id, passage in deps.evidence.passages.items()
    )
    _log_evidence(evidence, snippet_chars)
    _log_answer(result)
    logger.info(
        "\nUSAGE\nrequests=%d  tool_calls=%d  input_tokens=%d  "
        "output_tokens=%d  total_tokens=%d",
        result.usage.requests,
        result.usage.tool_calls,
        result.usage.input_tokens,
        result.usage.output_tokens,
        result.usage.total_tokens,
    )
    return AssistantInspection(
        result=result,
        evidence=evidence,
        search_calls=deps.counters.search_calls,
        surrounding_calls=deps.counters.surrounding_calls,
    )


def _log_tool_result(event: FunctionToolResultEvent) -> None:
    part = event.part
    if isinstance(part, RetryPromptPart):
        logger.info("TOOL RETRY  %s", part.content)
        return
    if not isinstance(part, ToolReturnPart):
        return

    content = part.content
    if isinstance(content, SearchToolResult):
        logger.info(
            "TOOL RESULT search_filings  lexical=%r  ranked=%d  context=%d",
            content.lexical_query,
            len(content.ranked_passages),
            len(content.context_passages),
        )
    elif isinstance(content, ReadablePassage):
        logger.info(
            "TOOL RESULT read_chunk  %s  %d characters",
            content.source_id,
            len(content.text),
        )
    elif isinstance(content, tuple) and all(
        isinstance(item, ReadablePassage) for item in content
    ):
        logger.info(
            "TOOL RESULT read_surrounding_chunks  %s",
            [item.source_id for item in content],
        )
    else:
        logger.info("TOOL RESULT %s", part.tool_name)


def _log_evidence(
    evidence: tuple[InspectedEvidence, ...],
    snippet_chars: int,
) -> None:
    logger.info("\nCURRENT-TURN EVIDENCE (%d passages)", len(evidence))
    for item in evidence:
        passage = item.passage
        location = passage.section_title or "unknown section"
        if passage.page_number is not None:
            location = f"{location}, page {passage.page_number}"
        logger.info(
            "%s  %s:%d  %s  %s  read=%s cited=%s",
            item.source_id,
            passage.accession_number,
            passage.chunk_index,
            passage.ticker,
            location,
            item.was_read,
            item.was_cited,
        )
        text = " ".join(passage.text.split())
        ellipsis = "…" if len(text) > snippet_chars else ""
        logger.info("   %s%s", text[:snippet_chars], ellipsis)


def _log_answer(result: AssistantRunResult) -> None:
    logger.info(
        "\nVALIDATED ANSWER (%s)\n%s", result.answer.status, result.answer.answer
    )
    if result.answer.citations:
        logger.info("\nCITATIONS")
        for citation in result.answer.citations:
            logger.info(
                "%s  %s:%d\n   %s",
                citation.source_id,
                citation.accession_number,
                citation.chunk_index,
                citation.excerpt,
            )
