"""Inspect one manually supplied call through the production assistant tool path.

Only the planner is simulated. Retrieval uses the real tool dispatcher and services;
the graph stops before the next assistant request or any answer/chat persistence.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, fields
from typing import Literal, cast
from uuid import UUID, uuid4

import httpx
import tiktoken
from openai import Omit
from pydantic_ai import Agent, UsageLimits
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModelSettings

from app.assistant.agent import DocumentAssistant
from app.assistant.deps import AssistantDeps, AssistantModelSettings
from app.assistant.outputs import SearchToolResult
from app.assistant.tools import FilingSearchFilters
from app.assistant.tracing import AssistantTrace
from app.config import settings
from app.database.supabase import create_user_supabase_client
from app.grounding import GroundingValidator
from app.retrieval.keywords import OpenAIKeywordExtractor
from app.retrieval.models import SourcePassage
from app.retrieval.retriever import DocumentRetriever
from app.services import AzureOpenAIService
from app.services.azure_responses_model import AzureResponsesModel


@dataclass
class SearchInspectionTrace(AssistantTrace):
    """Keep sanitized retrieval events in memory, never in shared log handlers."""

    events: list[dict[str, object]] = field(default_factory=list)

    def emit(
        self,
        event: str,
        stage: str,
        *,
        level: Literal["debug", "info", "warning", "error"] = "info",
        operational: bool = False,
        exc_info: bool = False,
        **values: object,
    ) -> None:
        # FunctionModel invents token usage: never retain its model-request events.
        if stage.startswith(("retrieval.", "assistant.tool.")):
            self.events.append(
                {
                    "event": event,
                    "stage": stage,
                    "elapsed_ms": round(self.elapsed_ms, 3),
                    **self.serialize(values),
                }
            )


def create_inspection_trace() -> SearchInspectionTrace:
    trace = SearchInspectionTrace.disabled()
    trace.mode = "full"
    return trace


@dataclass(frozen=True)
class SearchToolInspection:
    arguments: dict[str, object]
    metadata: dict[str, object]
    token_metadata: dict[str, object]
    tool_definitions: list[dict[str, object]]
    assistant_request_content: dict[str, object]
    assistant_followup_content: dict[str, object]
    result: SearchToolResult | None
    output_text: str
    provider_usage: list[dict[str, object]]
    stages: dict[str, dict[str, object]]
    events: tuple[dict[str, object], ...]
    evidence: dict[str, SourcePassage]


async def inspect_search_filings(
    query: str,
    filters: FilingSearchFilters,
    access_token: str,
    *,
    token_encoding: str = "o200k_base",
) -> SearchToolInspection:
    """Run one live user-scoped search and close all owned clients on exit."""
    access_token = access_token.strip()
    if not access_token:
        raise ValueError("An authenticated Supabase access token is required")
    # Resolve/download tokenizer data before spending requests on live retrieval.
    await asyncio.to_thread(tiktoken.get_encoding, token_encoding)
    timeout = httpx.Timeout(
        connect=settings.supabase_http_connect_timeout_seconds,
        read=settings.supabase_http_read_timeout_seconds,
        write=settings.supabase_http_write_timeout_seconds,
        pool=settings.supabase_http_pool_timeout_seconds,
    )
    async with (
        httpx.AsyncClient(timeout=timeout) as http_client,
        AzureOpenAIService(settings) as azure_openai,
    ):
        supabase = await create_user_supabase_client(
            settings, access_token, http_client=http_client
        )
        auth = await supabase.auth.get_user(access_token)
        trace = create_inspection_trace()
        retriever = DocumentRetriever(
            supabase,
            azure_openai.client,
            OpenAIKeywordExtractor(
                azure_openai.client,
                model=settings.azure_openai_keyword_deployment,
                trace=trace,
            ),
            embedding_model=settings.azure_openai_embedding_deployment,
            embedding_dimensions=settings.openai_embedding_dimensions,
            trace=trace,
        )
        deps = AssistantDeps(
            user_id=UUID(auth.user.id),
            thread_id=uuid4(),
            retriever=retriever,
            grounding_validator=GroundingValidator(),
            model_settings=AssistantModelSettings.from_app_settings(settings),
            trace=trace,
        )
        model = azure_openai.create_responses_model(
            settings.azure_openai_assistant_deployment,
            settings.openai_assistant_model,
        )
        return await run_search_inspection(
            query, filters, deps, model, trace, token_encoding=token_encoding
        )


async def run_search_inspection(
    query: str,
    filters: FilingSearchFilters,
    deps: AssistantDeps,
    model: AzureResponsesModel,
    trace: SearchInspectionTrace,
    *,
    token_encoding: str = "o200k_base",
) -> SearchToolInspection:
    """Inject only the planner response; execute the registered tool exactly once.

    The model adapter is used for serialization/estimates only, never generation.
    Tests can inject retrieval service boundaries without replacing the tool itself.
    """
    deps.require_fresh_run()
    arguments = {"query": query, "filters": filters.model_dump(mode="json")}
    captured_messages: list[ModelMessage] = []
    captured_info: AgentInfo | None = None

    def manual_call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal captured_info
        captured_messages.extend(messages)
        captured_info = info
        return ModelResponse(
            parts=[ToolCallPart("search_filings", arguments, "inspect-search-1")],
            finish_reason="tool_call",
        )

    assistant = DocumentAssistant(
        FunctionModel(manual_call, profile=model.profile),
        # Telemetry must not export simulated model calls as real Azure usage.
        settings.model_copy(update={"azure_monitor_tracing_enabled": False}),
        count_tokens_before_request=False,
    )
    started = time.perf_counter()
    # The wrapper exposes only complete answers. Its registered Agent is required
    # here to stop at the tool boundary, before a second model request/grounding.
    async with assistant._agent.iter(
        query,
        deps=deps,
        model_settings=deps.model_settings.to_pydantic_ai(),
        usage_limits=UsageLimits(
            request_limit=settings.assistant_max_model_requests,
            tool_calls_limit=settings.assistant_max_tool_calls,
            count_tokens_before_request=False,
        ),
    ) as run:
        node = await run.next(run.next_node)
        assert Agent.is_model_request_node(node)
        node = await run.next(node)
        assert Agent.is_call_tools_node(node)
        node = await run.next(node)
        assert Agent.is_model_request_node(node)
        part = next(
            part
            for part in node.request.parts
            if isinstance(part, ToolReturnPart | RetryPromptPart)
        )
        # Pending tool results are not in all_messages until the next request runs.
        followup_messages = [*run.all_messages(), node.request]
        executed_tool_calls = run.usage.tool_calls
    duration_ms = (time.perf_counter() - started) * 1000
    assert captured_info is not None
    result = part.content if isinstance(part, ToolReturnPart) else None
    assert result is None or isinstance(result, SearchToolResult)
    output_text = (
        part.model_response_str()
        if isinstance(part, ToolReturnPart)
        else part.model_response()
    )
    before = await _request_content(model, captured_messages, captured_info)
    after = await _request_content(model, followup_messages, captured_info)
    tool_definitions = before.get("tools", [])
    stages = {event["stage"]: event for event in trace.events}
    return SearchToolInspection(
        arguments=arguments,
        metadata={
            "tool_name": "search_filings",
            "tool_call_id": part.tool_call_id,
            "status": "success" if result is not None else "retry_required",
            "query": query,
            "normalized_query": result.query if result is not None else None,
            "filters": arguments["filters"],
            "available_tool_count": len(tool_definitions),
            "available_tool_names": [tool["name"] for tool in tool_definitions],
            "submitted_tool_calls": 1,
            "successful_tool_calls": executed_tool_calls,
            "search_calls": deps.counters.search_calls,
            "assistant_model_requests_sent": 0,
            "assistant_provider_usage": None,
            "database_access": "authenticated_user",
            "result_limit": settings.assistant_search_result_limit,
            "candidate_limit_per_branch": settings.assistant_search_candidate_limit,
            "tool_timeout_seconds": settings.assistant_tool_timeout_seconds,
            "max_search_calls_per_turn": settings.assistant_max_search_calls,
            "ranked_passage_count": len(result.ranked_passages) if result else 0,
            "context_passage_count": len(result.context_passages) if result else 0,
            "registered_evidence_count": len(deps.evidence.passages),
            "duration_ms": round(duration_ms, 3),
            "scope": "One manual tool call in a fresh turn; no history or answer.",
        },
        token_metadata=await _token_metadata(
            model,
            captured_info,
            captured_messages,
            followup_messages,
            before,
            after,
            query,
            arguments,
            output_text,
            token_encoding,
        ),
        tool_definitions=tool_definitions,
        assistant_request_content=before,
        assistant_followup_content=after,
        result=result,
        output_text=output_text,
        provider_usage=_provider_usage(stages),
        stages=stages,
        events=tuple(trace.events),
        evidence=deps.evidence.passages,
    )


async def _request_content(
    model: AzureResponsesModel,
    messages: list[ModelMessage],
    info: AgentInfo,
) -> dict[str, object]:
    prepared_settings, parameters = model.prepare_request(
        info.model_settings, info.model_request_parameters
    )
    # Use the same SDK serializer as AzureResponsesModel.count_tokens. These are
    # content-bearing request fields, not a claim that an HTTP request was sent.
    request = await model._build_responses_request_params(
        messages,
        cast(OpenAIResponsesModelSettings, prepared_settings or {}),
        parameters,
        model.profile,
    )
    return {
        item.name: value
        for item in fields(request)
        if not isinstance((value := getattr(request, item.name)), Omit)
    }


async def _token_metadata(
    model,
    info,
    messages,
    followup,
    before,
    after,
    query,
    arguments,
    output_text,
    token_encoding,
) -> dict[str, object]:
    encoding = tiktoken.get_encoding(token_encoding)

    def count(value: object) -> int:
        text = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        )
        return len(encoding.encode(text, disallowed_special=()))

    before_budget = await model.count_tokens(
        messages, info.model_settings, info.model_request_parameters
    )
    after_budget = await model.count_tokens(
        followup, info.model_settings, info.model_request_parameters
    )
    return {
        "encoding": token_encoding,
        "measurement": "Local text estimates, not provider-reported assistant usage.",
        "query_text_tokens_estimate": count(query),
        "tool_arguments_tokens_estimate": count(arguments),
        "tool_result_tokens_estimate": count(output_text),
        "tool_definitions_tokens_estimate": count(before.get("tools", [])),
        "assistant_request_content_tokens_estimate": count(before),
        "assistant_followup_content_tokens_estimate": count(after),
        "production_preflight_input_tokens_estimate": before_budget.input_tokens,
        "production_followup_input_tokens_estimate": after_budget.input_tokens,
        "note": (
            "The tool result becomes INPUT to the next assistant request, not "
            "assistant output-token usage. Request previews use QUERY as the user "
            "message, real instructions/tools/output schema, and a manual tool call; "
            "no history or model reasoning. No assistant request is sent. Preflight "
            "counts use the production character heuristic, not tiktoken."
        ),
    }


def _provider_usage(stages: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for role in ("embedding", "keywords"):
        response = stages.get(f"retrieval.{role}.response")
        if response is None:
            continue
        usage = response.get("usage")
        counters = usage if isinstance(usage, dict) else {}
        rows.append(
            {
                "role": role,
                "model": response.get("model"),
                "duration_ms": response.get("duration_ms"),
                "measurement": "provider_reported" if counters else "unavailable",
                "input_tokens": counters.get(
                    "prompt_tokens" if role == "embedding" else "input_tokens"
                ),
                "output_tokens": counters.get("output_tokens"),
                "total_tokens": counters.get("total_tokens"),
                "raw_usage": usage,
            }
        )
    return rows
