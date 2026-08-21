"""Run each # %% cell with Shift+Enter in the backend IPython kernel."""

# ruff: noqa: F704, PLE1142, B018 - IPython supports top-level await and display.

# %% Imports
import nest_asyncio2

from app.retrieval.models import RetrievalFilters
from evaluation.inspect_retrieval import inspect_retrieval

nest_asyncio2.apply()


# %% Edit the query and filters
QUERY = "What was the most grossing product in 2024?"

FILTERS = RetrievalFilters(
    tickers=("AAPL",),
    filing_types=("10-K",),
    filing_years=(2024,),
)

# Other query ideas:
# "How could foundry capacity constraints prevent NVIDIA from meeting demand?"
# "How fast did Azure and other cloud services grow and what drove it?"

# %% Run the complete hybrid-retrieval workflow
result = await inspect_retrieval(QUERY, FILTERS, show=5)

# %% Inspect the final ranked chunks
result.hybrid_passages
