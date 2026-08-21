"""Opt-in end-to-end grounding checks against live OpenAI and Supabase."""

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from openai import AsyncOpenAI

from app.assistant import (
    AssistantDeps,
    AssistantModelSettings,
    create_document_assistant,
)
from app.assistant.policy import (
    INSUFFICIENT_EVIDENCE_STATEMENT,
    INVESTMENT_ADVICE_STATEMENT,
)
from app.database.supabase import create_user_supabase_client
from app.grounding import GroundingValidator
from app.retrieval.keywords import OpenAIKeywordExtractor
from app.retrieval.retriever import DocumentRetriever

pytestmark = pytest.mark.integration


async def live_services() -> tuple[object, AssistantDeps]:
    access_token = os.environ.get("SUPABASE_TEST_ACCESS_TOKEN")
    if not access_token:
        pytest.skip("SUPABASE_TEST_ACCESS_TOKEN is required for live assistant tests")

    from app.config import settings

    supabase = await create_user_supabase_client(settings, access_token)
    auth_response = await supabase.auth.get_user(access_token)
    openai_client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        max_retries=3,
    )
    retriever = DocumentRetriever(
        supabase,
        openai_client,
        OpenAIKeywordExtractor(
            openai_client,
            model=settings.openai_keyword_model,
        ),
        embedding_model=settings.openai_embedding_model,
        embedding_dimensions=settings.openai_embedding_dimensions,
    )
    deps = AssistantDeps(
        user_id=UUID(auth_response.user.id),
        thread_id=uuid4(),
        retriever=retriever,
        grounding_validator=GroundingValidator(),
        model_settings=AssistantModelSettings.from_app_settings(settings),
    )
    return create_document_assistant(settings), deps


def test_live_answerable_question_returns_current_turn_citations() -> None:
    async def run() -> None:
        assistant, deps = await live_services()
        result = await assistant.run(
            "According to Apple's 2024 10-K, what drove the increase in Services net sales?",
            deps,
        )

        assert result.answer.status == "supported"
        assert result.answer.citations
        assert all(citation.ticker == "AAPL" for citation in result.answer.citations)

    asyncio.run(run())


def test_live_unsupported_question_returns_clear_refusal() -> None:
    async def run() -> None:
        assistant, deps = await live_services()
        result = await assistant.run(
            "What color were the walls in Apple's executive offices in fiscal 2024?",
            deps,
        )

        assert result.answer.status == "insufficient_evidence"
        assert INSUFFICIENT_EVIDENCE_STATEMENT in result.answer.answer
        assert result.answer.citations == ()

    asyncio.run(run())


def test_live_mixed_advice_question_returns_cited_facts_then_refuses() -> None:
    async def run() -> None:
        assistant, deps = await live_services()
        result = await assistant.run(
            "According to Apple's 2024 10-K, what drove Services growth, and should I buy Apple shares because of it?",
            deps,
        )

        assert result.answer.status == "investment_advice_refused"
        assert result.answer.citations
        assert INVESTMENT_ADVICE_STATEMENT in result.answer.answer

    asyncio.run(run())
