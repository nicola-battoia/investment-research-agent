"""Inspect an actual search_filings call, cell by cell in the backend kernel.

Only the assistant's choice of query is manual. Its registered tool dispatcher,
retriever, user-scoped database access, limits, and result serialization are real.
The answer model is not called. Run # %% cells with Shift+Enter, not `python`.
"""

# ruff: noqa: F704, PLE1142 - IPython supports top-level await.

# %% Imports
from getpass import getpass

import nest_asyncio2
from IPython.display import JSON, display

from app.assistant.tools import FilingSearchFilters
from evaluation.inspect_search_tool import inspect_search_filings

nest_asyncio2.apply()


# %% Edit the query and filters
QUERY = "Which Apple product had the highest net sales in fiscal 2024?"

FILTERS = FilingSearchFilters(
    tickers=("AAPL",),
    filing_types=("10-K",),
    filing_years=(2024,),
)
# To intentionally search the entire corpus: FILTERS = FilingSearchFilters(corpus_wide=True)
# Query/filters here are tool arguments; no model rewrites them for you.

TOKEN_ENCODING = "o200k_base"  # Explicit local estimate, not a billing measurement.

# Other query ideas:
# "How could foundry capacity constraints prevent NVIDIA from meeting demand?"
# "How fast did Azure and other cloud services grow and what drove it?"

# %% Inspect the exact arguments supplied as a manual assistant tool call
tool_arguments = {"query": QUERY, "filters": FILTERS.model_dump(mode="json")}
display(JSON(tool_arguments, expanded=True))


# %% Authenticate as the same user as the app (JWT, not a service-role key)
# Credentials are never included in the inspection output.
ACCESS_TOKEN = getpass("Supabase access token: ")


# %% Execute ONE search_filings call through the real assistant tool dispatcher
# This cell calls live Azure embeddings/keywords and Supabase, but no answer model.
# Re-running starts fresh tool counters and S# IDs. All clients close automatically.
inspection = await inspect_search_filings(
    QUERY, FILTERS, ACCESS_TOKEN, token_encoding=TOKEN_ENCODING
)


# %% Metadata: query, tools offered/called, limits, result counts, and elapsed time
display(JSON(inspection.metadata, expanded=True))


# %% All tool definitions offered to the assistant (derived from its registration)
display(JSON(inspection.tool_definitions, expanded=False))


# %% Token estimates: arguments, result, schemas, and before/after assistant input
# Tool-result tokens become the assistant's NEXT INPUT, not its generated output.
# No assistant request was sent; these are explicitly labeled local estimates.
display(JSON(inspection.token_metadata, expanded=True))


# %% Actual provider-reported token usage for the internal embedding/keyword calls
# Embeddings have no generated-text output tokens; unavailable values remain null.
display(JSON(inspection.provider_usage, expanded=True))


# %% Exact compact tool-result text (or retry message) returned to the assistant
print(inspection.output_text)


# %% The same output in an expandable, structured view
result = inspection.result
if result is not None:
    display(JSON(result.model_dump(mode="json"), expanded=False))


# %% Ranked S# previews separately from additional bridge-context previews
if result is not None:
    display(JSON([item.model_dump(mode="json") for item in result.ranked_passages]))
    display(JSON([item.model_dump(mode="json") for item in result.context_passages]))


# %% Retrieval stages: keyword/embedding requests, candidates, RRF, hydration/context
# All of these came from the SAME search above; displaying them performs no I/O.
display(JSON(inspection.stages, expanded=False))


# %% Individual stages can also be inspected on separate lines
inspection.stages.get("retrieval.keywords.response")

# %% Semantic ranking (IDs + scores)
inspection.stages.get("retrieval.semantic.completed")

# %% Lexical ranking (IDs + scores)
inspection.stages.get("retrieval.lexical.completed")

# %% Fused ranking (IDs + scores + component ranks)
inspection.stages.get("retrieval.fusion.completed")

# %% Hydrated ranked evidence, bridge context, and retrieval timings
inspection.stages.get("retrieval.search.completed")


# %% Full local source metadata/text by S# (NOT all sent in the search result)
# Inspecting this does not invoke read_chunk or mark evidence as read.
display(
    JSON(
        {
            key: value.model_dump(mode="json")
            for key, value in inspection.evidence.items()
        }
    )
)


# %% Assistant input content preview: real instructions, tools, and output schema
# For this fresh-turn illustration, QUERY is also the user message; no history.
# These request-content previews are serialized locally and are NOT sent to Azure.
display(JSON(inspection.assistant_request_content, expanded=False))


# %% Next assistant input content, including function_call and function_call_output
display(JSON(inspection.assistant_followup_content, expanded=False))


# %% Forget the pasted token when finished (inspection data remains available)
del ACCESS_TOKEN
