import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.retrieval.keywords import (
    KEYWORD_EXTRACTION_INSTRUCTIONS,
    OpenAIKeywordExtractor,
)
from app.retrieval.models import ExtractedKeywords, KeywordGroup


def test_extracted_keywords_normalize_and_deduplicate_search_terms() -> None:
    keywords = ExtractedKeywords(
        groups=(
            KeywordGroup(terms=("  Net   sales ", "Revenue", "revenue")),
            KeywordGroup(terms=("Services", "net sales")),
        )
    )

    assert keywords.groups[0].terms == ("Net sales", "Revenue")
    assert keywords.search_text == "Net sales Revenue Services"


def test_openai_extractor_uses_typed_project_prompt() -> None:
    keywords = ExtractedKeywords(
        groups=(
            KeywordGroup(terms=("Services", "net sales")),
            KeywordGroup(terms=("revenue growth",)),
        )
    )
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=keywords))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    extractor = OpenAIKeywordExtractor(client, model="gpt-5.4-nano")

    result = asyncio.run(
        extractor.extract("  What drove the increase in Services net sales?  ")
    )

    assert result == keywords
    parse.assert_awaited_once_with(
        model="gpt-5.4-nano",
        instructions=KEYWORD_EXTRACTION_INSTRUCTIONS,
        input="What drove the increase in Services net sales?",
        text_format=ExtractedKeywords,
        max_output_tokens=2000,
        store=False,
    )


def test_openai_extractor_rejects_missing_structured_output() -> None:
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=None))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    extractor = OpenAIKeywordExtractor(client, model="gpt-5.4-nano")

    with pytest.raises(ValueError, match="structured retrieval keywords"):
        asyncio.run(extractor.extract("revenue growth"))
