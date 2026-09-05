# Evaluation and inspection

Use these tools to inspect retrieval or evaluate an answer. Commands run from
`backend/` with the configured Azure and Supabase credentials. The
[configuration reference](../../docs/configuration.md) explains the deployment
names and limits.

## Choose a tool

| Tool | What it exercises | Access and side effects |
| --- | --- | --- |
| [Search playground](../playground/inspect_retrieval.py) / [`inspect_search_filings`](inspect_search_tool.py) | One manually supplied `search_filings` call through the production tool dispatcher | User JWT; live embedding, keyword, and database calls; no answer generation or chat writes |
| [Assistant playground](../playground/inspect_assistant.py) | A complete assistant run with retrieval and grounding | User JWT; live model and database reads; no chat persistence |
| [Branch inspector](inspect_retrieval.py) | Semantic, lexical, and fused retrieval rankings | Admin database client; live retrieval calls; no answer model |
| [Retrieval runner](run_retrieval.py) | The cases in `retrieval_cases.json` against all three ranking methods | Admin database client; live retrieval calls; writes a local result file |
| [Deep research benchmark](benchmarks/filings_deep_research_v1.md) | Fifteen human-scored research tasks | A specification, with no automated runner wired to it |

Live model calls incur usage. Full inspection objects contain query and filing
content; treat saved notebook output accordingly.

## Inspect the production search tool

Open [`playground/inspect_retrieval.py`](../playground/inspect_retrieval.py) in an
IPython-compatible editor using the backend environment. Run its `# %%` cells
with Shift+Enter; this is not a normal Python CLI script.

1. Edit `QUERY` and `FILTERS`.
2. Use `FilingSearchFilters(corpus_wide=True)` when whole-corpus search is
   intentional. Otherwise supply a company, form, year, or other supported scope.
3. Paste a current Supabase **user access token** into the hidden prompt.
4. Run the execution cell once. Subsequent display cells inspect the same result
   without repeating network calls.
5. Delete the token variable with the final cell when finished.

The planner is simulated with a `FunctionModel` that emits exactly the supplied
tool call. Tool registration, argument validation, counters, timeout, user-scoped
retrieval, evidence registration, and result serialization are real. Each
execution starts a fresh turn and closes its owned clients. Invalid tool arguments
can produce a retry message; the graph stops before a model can act on that retry.

No assistant provider request is sent. The graph stops at the next model-request
boundary, before answer generation, grounding, or persistence. The query doubles
as the user message in this fresh-turn illustration; history is empty.

| Inspection field | Meaning |
| --- | --- |
| `arguments`, `metadata` | Supplied query/filters, execution status, tool counts, limits, result sizes, and duration |
| `tool_definitions` | Tools and schemas derived from the real assistant registration |
| `output_text` | Exact compact result text, or retry message, returned to the assistant |
| `result` | Structured search result, or `None` for a retry |
| `provider_usage` | Provider-reported usage from the internal embedding and keyword calls |
| `token_metadata` | Explicit local estimates for arguments, result, schemas, and assistant input |
| `stages`, `events` | Retrieval diagnostics from this execution, including branch rankings and fusion |
| `evidence` | Full locally registered passage metadata/text, indexed by `S#` |
| `assistant_request_content` | Locally serialized first assistant request content |
| `assistant_followup_content` | Locally serialized next request content, including the tool call and its output |

Search results expose ranked previews and any added context previews separately.
Opening `evidence` in the notebook does **not** invoke `read_chunk` or mark a
passage as read for grounding.

Tool-result tokens become the assistant's **next input**, not its generated
output. The default local encoding is `o200k_base`; its tokenizer data may need
a download on first use. These estimates differ from production's conservative
request-budget estimate and are not billing measurements. Simulated assistant
usage is deliberately omitted. Embeddings have no generated-text output usage;
unavailable usage remains null.

## Retrieval evaluation: labels need repair

The checked-in ten-case dataset uses accession-number/chunk-index references.
All fourteen expected references are absent from the current local
`sec_sections_v2` checkpoints. The accepted result dated 2026-08-19 predates
the parser/chunker replacement. It is historical evidence, not a passing score
for today's corpus. See [audit finding F01](../../docs/repository-audit.md#f01-retrieval-evaluation-labels-do-not-match-the-current-corpus).

Before using this runner as a release gate:

1. Remap expected passages to the current corpus and review their relevance.
2. Verify the uploaded database corpus matches those checkpoints.
3. Run the evaluation and review per-case rankings, not only the aggregate.

After those prerequisites, a run can be saved without overwriting history:

```bash
uv run --locked python -m evaluation.run_retrieval \
  --output /tmp/document-copilot-retrieval.json
```

The runner evaluates semantic, lexical, and hybrid rankings at ten results.
Acceptance requires a hybrid hit for every case, nonzero mean lexical hit rate,
and hybrid mean nDCG at least as high as both component methods. This tests
retrieval against the labels; it does not validate generated claims or arithmetic.
See [the dated tuning record](results/tuning-summary.md) for earlier experiments.

## Offline and live tests

The normal development suite is offline:

```bash
uv run --locked pytest -m "not integration"
```

For explicitly scheduled live testing, place a current
`SUPABASE_TEST_ACCESS_TOKEN` in a local ignored `.env.integration`, confirm the
target environment, then run:

```bash
uv run --locked --env-file .env.integration pytest -m integration
```

Always select the intended marker explicitly: plain `pytest` also selects these
integration tests. Some use admin credentials to create test users/threads
and write or delete test records; assistant/retrieval tests can use paid model
calls. They are not a read-only production smoke test.

The deep research benchmark additionally requires printed-page locators and
some ten-document answers. Current chunks have no populated page numbers and
the default turn has eight total tool calls. Its compatibility notes and the
[audit](../../docs/repository-audit.md) explain why it is not currently a
passing end-to-end release gate.
