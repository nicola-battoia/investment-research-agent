"""Opt-in retrieval integration coverage for the configured live services."""

import asyncio
import os
from datetime import date

import pytest
from openai import AsyncOpenAI

from app.database.supabase import create_user_supabase_client
from app.retrieval.keywords import OpenAIKeywordExtractor
from app.retrieval.models import RetrievalFilters
from app.retrieval.retriever import DocumentRetriever

pytestmark = pytest.mark.integration


def test_authenticated_hybrid_retrieval_respects_all_filters() -> None:
    access_token = os.environ.get("SUPABASE_TEST_ACCESS_TOKEN")
    if not access_token:
        pytest.skip("SUPABASE_TEST_ACCESS_TOKEN is required for live retrieval")

    from app.config import settings

    async def run() -> None:
        supabase = await create_user_supabase_client(settings, access_token)
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
        result = await retriever.search(
            "What drove the increase in Services net sales?",
            RetrievalFilters(
                companies=("Apple Inc.",),
                tickers=("NOT-A-TICKER",),
                filing_types=("10-K",),
                filing_years=(2024,),
                filed_on_or_after=date(2024, 1, 1),
                filed_on_or_before=date(2024, 12, 31),
            ),
        )

        assert result.passages
        assert all(passage.ticker == "AAPL" for passage in result.passages)
        assert all(passage.filing_type == "10-K" for passage in result.passages)
        assert all(passage.report_date.year == 2024 for passage in result.passages)

    asyncio.run(run())
