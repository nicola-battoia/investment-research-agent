"""Typed OpenAI keyword extraction for the lexical retrieval branch."""

import time
from typing import Protocol

from app.assistant.tracing import AssistantTrace
from app.config import settings
from app.retrieval.models import ExtractedKeywords

KEYWORD_EXTRACTION_INSTRUCTIONS = f"""
You extract lexical search concepts for an internal SEC filing retrieval system.
The corpus contains structure-aware chunks from 10-K and 10-Q filings.

Return between 1 and {settings.retrieval_keyword_max_groups} keyword groups. Each
group represents one distinct, evidence-bearing concept explicitly present in the
question and contains 1 to {settings.retrieval_keyword_max_terms_per_group} terms or
short phrases likely to appear in a filing.

Rules:
- Remove question framing, conversational filler, and generic request verbs.
- Preserve named companies, products, segments, financial metrics, accounting
  terms, operational constraints, risks, and cause-and-effect concepts that the
  user actually wrote.
- Prefer exact filing language such as "net sales", "operating income",
  "capacity constraints", or "revenue growth" over broad topical words.
- Add only an abbreviation expansion or a very close lexical form of an explicit
  concept, such as "AWS" and "Amazon Web Services". Never add possible answers,
  causes, drivers, products, metrics, entities, or synonyms not stated in the
  question. If the user asks what drove a change, do not guess the drivers.
- Keep phrases to {settings.retrieval_keyword_max_phrase_words} words or fewer. Do not
  emit sentences, punctuation-only values, Boolean operators, explanations, or search
  syntax.
- Do not answer the question. Return only the structured keyword groups.

Examples:
- "What drove the increase in Services net sales?" -> "Services", "net sales",
  "increase".
- "How much did AWS sales grow?" -> "AWS" / "Amazon Web Services", "sales",
  "growth".
- "Could foundry capacity constraints prevent meeting demand?" -> "foundry
  capacity", "capacity constraints", "meet demand".
""".strip()


class ParsedKeywordResponse(Protocol):
    output_parsed: ExtractedKeywords | None


class ResponsesResource(Protocol):
    async def parse(
        self,
        *,
        model: str,
        instructions: str,
        input: str,
        text_format: type[ExtractedKeywords],
        max_output_tokens: int,
        store: bool,
    ) -> ParsedKeywordResponse: ...


class OpenAIClient(Protocol):
    responses: ResponsesResource


class KeywordExtractor(Protocol):
    async def extract(self, query: str) -> ExtractedKeywords: ...


class OpenAIKeywordExtractor:
    """Extract bounded SEC-search terms with OpenAI Structured Outputs."""

    def __init__(
        self,
        client: OpenAIClient,
        *,
        model: str,
        trace: AssistantTrace | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("Keyword extraction model is required")
        self._responses = client.responses
        self._model = model
        self._trace = trace or AssistantTrace.disabled()

    async def extract(self, query: str) -> ExtractedKeywords:
        query = query.strip()
        if not query:
            raise ValueError("Keyword extraction query cannot be empty")
        started = time.perf_counter()
        self._trace.emit(
            "retrieval_keyword_model_request",
            "retrieval.keywords.request",
            model=self._model,
            instructions=KEYWORD_EXTRACTION_INSTRUCTIONS,
            input=query,
            max_output_tokens=settings.openai_keyword_max_output_tokens,
        )
        response = await self._responses.parse(
            model=self._model,
            instructions=KEYWORD_EXTRACTION_INSTRUCTIONS,
            input=query,
            text_format=ExtractedKeywords,
            max_output_tokens=settings.openai_keyword_max_output_tokens,
            store=settings.openai_store_responses,
        )
        if response.output_parsed is None:
            self._trace.emit(
                "retrieval_keyword_model_invalid_response",
                "retrieval.keywords.invalid_response",
                level="error",
                model=self._model,
                duration_ms=(time.perf_counter() - started) * 1000,
                provider_response_id=getattr(response, "id", None),
            )
            raise ValueError("OpenAI did not return structured retrieval keywords")
        self._trace.emit(
            "retrieval_keyword_model_response",
            "retrieval.keywords.response",
            model=self._model,
            duration_ms=(time.perf_counter() - started) * 1000,
            provider_response_id=getattr(response, "id", None),
            output=response.output_parsed,
            usage=getattr(response, "usage", None),
        )
        return response.output_parsed
