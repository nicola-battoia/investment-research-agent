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
| [Assistant QA runner](qa/run.py) | Fifteen research questions through authenticated API/SSE, grounding and reload | Temporary accounts/chats, real model calls, private `qa` records and local reports |
| [Budget trace analysis](qa/analyze_budgets.py) | Per-request usage, search repeats, reads and stopping causes in saved QA traces | Local report files only; no service calls or database writes |
| [Permission probes](qa/permissions.py) / [public API probes](qa/permissions_http.py) | Actual roles/RLS and user JWT writes | Rollback-only SQL fixtures or disposable HTTP accounts; failures exit nonzero |

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

## Retrieval evaluation

The ten-case dataset was remapped to the current corpus on 2026-09-05. Each of
its fourteen labels now records accession/index, chunk UUID and text hash. The
runner validates the corpus fingerprint and all labels before calling models.
The August 19 result remains historical; use the
[new result](results/retrieval-2026-09-05.json) for the current labels.

```bash
uv run --locked python -m evaluation.run_retrieval \
  --output evaluation/results/retrieval-new.json
```

The runner evaluates semantic, lexical and hybrid rankings at ten results.
Acceptance requires a hybrid hit for every case, nonzero mean lexical hit rate,
and hybrid mean nDCG at least as high as both component methods. The September 5
run passed: hybrid evidence-group recall/hit rate 100%, nDCG 0.7462; semantic
nDCG 0.7401 and lexical nDCG 0.5994. These ten questions do not establish general
retrieval performance or answer correctness.

## Assistant QA: dataset, permissions and complete turns

The [working checklist](../../docs/qa-suite-todo.md) separates implemented layers
from pending browser, behavior and privacy coverage. The
[findings](../../docs/qa-findings-2026-09-05.md) explain current failures and proposed
fixes. The [case report](results/qa-baseline-2026-09-05.md) retains all fifteen cases.
The [September 7 budget investigation](results/research-budget-analysis-2026-09-07.md)
compares three questions under two profiles and explains why larger limits alone
are insufficient. Its [implementation plan](../../docs/assistant-research-plan.md)
proposes protected synthesis, compact evidence and secure continuation.

The [Markdown benchmark](benchmarks/filings_deep_research_v1.md) and its
[JSON companion](benchmarks/filings_deep_research_v1.json) contain the same questions
and gold answers; an offline test checks they agree. Required fact groups contain
one or more equivalent evidence passages. Retrieval, reading and citation each
receive a separate group-recall score. None is called answer accuracy.

`qa.datasets` stores version/checksum/corpus metadata; `qa.cases` stores questions,
gold answers, evidence and rubrics; `qa.runs` stores configuration and status;
`qa.results` stores each answer/failure, evidence, diagnostics and evaluation.
Dataset/case rows reject updates/deletes. The seeder refuses changed content under
an existing version. Publish a new version after editing questions, evidence or
rubrics. Golds are neither exposed through the browser API nor searchable filings.
The operator connection in `DATABASE_URL` owns QA writes.

Run from `backend/` against the intended configured Supabase project. These
commands create QA rows or temporary accounts, and assistant/retrieval/judge calls
use the configured Azure deployments. The QA runners do not change grants or
budgets. Alembic changes the schema; follow the staged
[security rollout](../../docs/security-fix-2026-09-06.md) when upgrading an older backend.

```bash
# After the reviewed migrations/rollout, validate and seed all 15 cases.
uv run --locked alembic upgrade head
uv run --locked python -m evaluation.qa.seed

# No assistant calls. A policy violation is a real nonzero result.
uv run --locked python -m evaluation.qa.permissions \
  --output evaluation/results/permissions-new.json
uv run --locked python -m evaluation.qa.permissions_http \
  --output evaluation/results/permissions-http-new.json

# Real replies, permissions, reload, replay, follow-up and chat lifecycle.
# Omit --base-url to exercise local FastAPI against the configured real services.
uv run --locked python -m evaluation.qa.chat_integrity \
  --base-url https://10k-club-backend.up.railway.app \
  --output evaluation/results/chat-integrity-new.json

# Bounded pilot; omit --cases to run all fifteen sequentially.
uv run --locked python -m evaluation.qa.run --cases DR-13 --judge \
  --output evaluation/results/qa-new.json
uv run --locked python -m evaluation.qa.report \
  --input evaluation/results/qa-new.json --output evaluation/results/qa-new.md
```

The runner creates a fresh confirmed test account for each question without
sending email, executes the real FastAPI route with its JWT, checks streamed
text/citations against a reloaded chat, then deletes the test chat/account. It
uses the same model/tool/validation/persistence code as the frontend's API. It
does **not** test browser rendering, Stop, CORS across a deployed network, or the
current Railway runtime configuration. Run each experimental environment profile
in a new process: several settings are bound at import time.

HTTP 200 is not a successful turn by itself: an SSE error counts as failure.
Failures and partial evidence are saved. A completed clarification or minimal
refusal is distinct from a rubric-passing research answer. `--judge` adds a
structured assessment using the configured assistant deployment (additional
model usage); critical failures override its score. Grades and usage are kept
separate from the deterministic evidence metrics. Human calibration remains
required. API format: [official structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

Full `qa-*.json` exports are ignored by Git and retained locally/in the private
schema. Commit reviewed Markdown and small permission/retrieval summaries. The
harness drops prompts, full source table metadata and duplicate answer payloads
from its trace; evidence identities, selected diagnostics and final answers remain.
It does not enable shared Azure content tracing. Do not enable content telemetry
merely to run QA.

After independently reviewing equivalent evidence, rescore recorded turns without
new assistant calls. Later inputs replace earlier cases regardless of score. The
command rejects changed questions/gold answers, missing cases or mixed settings:

```bash
uv run --locked python -m evaluation.qa.rescore \
  --input evaluation/results/qa-baseline-2026-09-05.json \
          evaluation/results/qa-explicit-scope-2026-09-05.json \
  --output evaluation/results/qa-reviewed-baseline-2026-09-05.json
```

Execution failures or failed/incomplete requested grading produce a nonzero exit
status after the run is recorded. An interrupted run records its status and
unrecorded-case count; hard process termination can leave a run marked running.
Original cases and results remain available when evidence is rescored.

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

The new QA integration tests require an additional explicit opt-in:

```bash
uv run --locked pytest tests/qa -m integration --qa-live
```

The desired permission assertions currently fail. Do not hide them with `xfail`
or interpret the green offline suite as proof that database permissions are safe.
