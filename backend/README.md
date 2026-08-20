# Document Copilot backend

FastAPI owns authentication, retrieval, AI orchestration, grounding, and database access.

## Set up

From this folder:

```bash
uv sync
```

Create `.env` from `.env.example` and fill in every value. `app/config.py` validates the file when the application starts.

## Run

```bash
uv run uvicorn app.main:app --reload
```

- Health check: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

## Check changes

```bash
uv run pytest
uv run ruff check app tests
uv run ruff format --check app tests
```

Preview pending migration SQL without changing the database:

```bash
uv run alembic upgrade head --sql
```

## Ingest converted SEC filings

From `backend/`, validate the manifest and Markdown corpus without changing Supabase:

```bash
uv run python -m ingestion.ingest_documents --dry-run
```

Upsert the documents into `source_documents` using the configured service-role key:

```bash
uv run python -m ingestion.ingest_documents
```

Rows are matched by SEC accession number, so the command is safe to rerun.

## Chunk, embed, and ingest filing passages

The chunking pipeline loads the native Docling JSON files and uses Docling's
`HierarchicalChunker`. Each table stays in one chunk. Tables use a compact row
serialization for embedding, while source offsets are located against the
non-compact normalized Markdown.

Validate one filing's hierarchy, table integrity, source offsets, and token limits:

```bash
uv run python -m ingestion.chunk_documents \
  --accession-number 0000320193-24-000123
```

Validate the complete local corpus without calling OpenAI or Supabase:

```bash
uv run python -m ingestion.ingest_chunks --dry-run
```

Run a deliberately bounded paid embedding test without database writes:

```bash
uv run python -m ingestion.create_embeddings \
  --accession-number 0000320193-24-000123 \
  --limit-chunks 3
```

After `source_documents` has been ingested, embed and upsert the complete corpus:

```bash
uv run python -m ingestion.ingest_chunks
```

To embed and upsert one complete filing instead, add
`--accession-number <accession>`. Chunk rows are matched by document ID and chunk
index, so reruns update stable rows and remove only a stale trailing range.

## Hybrid retrieval

Apply the latest Alembic migration before retrieval. It adds separate, bounded
Supabase RPC functions for pgvector similarity and Postgres full-text search;
Python combines their rankings with Reciprocal Rank Fusion.

```mermaid
flowchart LR
    Q["Query and explicit filters"] --> E["Embed query once"]
    Q --> K["OpenAI keyword extraction<br/>typed SEC concepts"]
    E --> S["pgvector semantic RPC<br/>up to 50 chunk IDs"]
    K --> L["Postgres English FTS RPC<br/>up to 50 chunk IDs"]
    Q -. "same filing filters" .-> S
    Q -. "same filing filters" .-> L
    S --> R["Weighted RRF in Python<br/>weight / (60 + rank)"]
    L --> R
    R --> T["Keep the top 10 IDs"]
    T --> H["Hydrate passage text<br/>and document metadata"]
    H --> B{"Useful one-chunk<br/>section bridge?"}
    B -- "Yes" --> C["Fetch bridge as separate context"]
    B -- "No" --> O["RetrievalResult"]
    C --> O
```

The retriever starts two complete pipelines concurrently. The semantic pipeline
embeds the original question once and immediately runs pgvector search. The lexical
pipeline asks a configured OpenAI model for bounded, typed groups of SEC-relevant
terms, then searches with their normalized, deduplicated text. Both database calls
use identical company, ticker, filing-type, fiscal-year, and filing-date filters.
A failure in either pipeline fails the request instead of silently changing
retrieval behavior.

The extraction prompt removes conversational framing and preserves evidence-bearing
filing concepts such as named segments, financial metrics, risks, causes, and exact
phrases. PostgreSQL's `english` text-search dictionary then performs stemming and
stop-word removal against the indexed `search_vector`; no separate NLP runtime
dependency is needed. Extracted groups and the final lexical query are recorded in
evaluation output for inspection. `OPENAI_KEYWORD_MODEL` configures the extraction
model; the evaluated default is `gpt-5.4-nano`.

RRF combines ranks rather than incomparable vector and text-search scores. It
deduplicates IDs and uses deterministic tie-breaking. The corpus-tuned weights are
20 for semantic and 1 for lexical, with `k=60`. Only the final ten chunks are
hydrated. A missing middle chunk is added only when it bridges two retained chunks
from the same document and section, and it remains separate from ranked evidence
so it cannot affect RRF or evaluation metrics.

### Inspect retrieval interactively

Open `playground/inspect_retrieval.py` in the editor with the backend IPython
kernel selected. Edit `QUERY` and `FILTERS`, then run each `# %%` cell with
Shift+Enter. There are no command-line arguments and no terminal workflow.

The small playground calls `evaluation.inspect_retrieval`, which runs the real
OpenAI/Supabase pipeline and logs the extracted keywords, FTS query, semantic and
lexical timings, branch candidates, RRF ranks, stable passage keys, and text
snippets. The last cell displays the final chunks in `result.hybrid_passages`;
`result.semantic_passages` and `result.lexical_passages` remain available when you
want to compare the two source rankings.

### Run the retrieval evaluation

The checked-in evaluation set contains atomic evidence lookups derived from the
client brief. Run it against the ingested corpus without invoking the answer model:

```bash
uv run python -m evaluation.run_retrieval \
  --output evaluation/results/retrieval-baseline.json
```

The command records semantic-only, lexical-only, and hybrid NDCG@10, hit rate,
evidence-group recall, latency, and the exact retrieval configuration. It exits
nonzero unless every hybrid case has a relevant top-10 passage and hybrid mean
NDCG@10 meets or exceeds both individual retrievers.

The live sample-corpus tuning run selected semantic/lexical RRF weights of 20:1.
This is the smallest recorded ratio that passed the frozen acceptance set; the
retriever and evaluation command use it by default. See
`evaluation/results/tuning-summary.md` for the recorded comparison.

The fast test suite never calls Supabase or OpenAI:

```bash
uv run pytest -m "not integration"
```

To run the authenticated live retrieval test deliberately, provide a current test
user token and select the integration marker:

```bash
SUPABASE_TEST_ACCESS_TOKEN=<token> uv run pytest -m integration
```

## Use in Python or Jupyter

Use the backend virtual environment, then import shared settings through:

```python
from app.config import settings
```

Never read environment variables directly in other backend modules.
