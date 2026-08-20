"""Typed OpenAI keyword extraction for the lexical retrieval branch."""

from typing import Protocol

from app.retrieval.models import ExtractedKeywords

KEYWORD_EXTRACTION_INSTRUCTIONS = """
You extract lexical search concepts for an internal SEC filing retrieval system.
The corpus contains structure-aware chunks from 10-K and 10-Q filings.

Return between 1 and 6 keyword groups. Each group represents one distinct,
evidence-bearing concept explicitly present in the question and contains 1 to 3
terms or short phrases likely to appear in a filing.

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
- Keep phrases to four words or fewer. Do not emit sentences, punctuation-only
  values, Boolean operators, explanations, or search syntax.
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

    def __init__(self, client: OpenAIClient, *, model: str) -> None:
        if not model.strip():
            raise ValueError("Keyword extraction model is required")
        self._responses = client.responses
        self._model = model

    async def extract(self, query: str) -> ExtractedKeywords:
        query = query.strip()
        if not query:
            raise ValueError("Keyword extraction query cannot be empty")
        response = await self._responses.parse(
            model=self._model,
            instructions=KEYWORD_EXTRACTION_INSTRUCTIONS,
            input=query,
            text_format=ExtractedKeywords,
            max_output_tokens=2000,
            store=False,
        )
        if response.output_parsed is None:
            raise ValueError("OpenAI did not return structured retrieval keywords")
        return response.output_parsed
