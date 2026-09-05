# Document Copilot backend

FastAPI owns request authorization, hybrid retrieval, the PydanticAI assistant,
citation validation and chat persistence. Models and embeddings run through Azure
AI Foundry; Supabase provides authentication and Postgres.

## Set up and run

From this directory:

```bash
uv sync --locked
cp -n .env.example .env
# Fill in required values before importing app.config or starting the server.
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --reload
```

Migrations affect the database in `DATABASE_URL`; use the intended development
project. See [backend setup](../docs/guides/backend-setup.md) and
[configuration](../docs/configuration.md). Health is at
[localhost:8000/health](http://localhost:8000/health), and the OpenAPI UI is at
[localhost:8000/docs](http://localhost:8000/docs). Health does not probe external services.

## Check changes

```bash
uv run --locked pytest -m "not integration"
uv run --locked ruff check app tests ingestion evaluation playground
uv run --locked ruff format --check app tests ingestion evaluation playground
```

This selects the offline suite. Plain `pytest` also selects integration tests,
some of which use configured live services. No frontend test runner is used.

Inspect the local migration graph or generate SQL without touching a database:

```bash
uv run --locked alembic heads
uv run --locked alembic upgrade head --sql
```

Offline SQL generation renders the full base-to-head chain. To preview only a known
revision range, use `alembic upgrade <known-revision>:head --sql`; offline mode
does not discover the live database's revision.

## API

All chat routes require a Supabase bearer token. JSON responses use camelCase.

| Method and path | Result |
| --- | --- |
| `GET /health` | Public process health |
| `GET /chat/threads` | Current user's threads |
| `POST /chat/threads` | Create a thread; optional title |
| `GET /chat/threads/{thread_id}` | Owned thread and saved UI messages |
| `PATCH /chat/threads/{thread_id}` | Rename an owned thread |
| `DELETE /chat/threads/{thread_id}` | Delete an owned thread and its messages/citations |
| `POST /chat/stream` | Complete one grounded turn and send an AI SDK-compatible SSE response |

The stream accepts `{ "id": "<thread UUID>", "message": <one user UIMessage> }`.
It sends status heartbeats while working, then final text and citations **after**
validation and atomic persistence. HTTP 200 means the stream opened; inspect its
typed failure events and `stream.completed` to determine the outcome.

The [chat-turn workflow](CHAT_TURN_WORKFLOW.md) explains ownership, history,
idempotency, tool execution, citations, cancellation and errors.

## Implementation map

| Directory/file | Purpose |
| --- | --- |
| `app/api/`, `app/auth/` | HTTP input and Supabase token verification |
| `app/chat/` | Orchestration, UI-message conversion and SSE |
| `app/assistant/` | Policy, agent, evidence registry, tools and local tracing |
| `app/retrieval/` | Semantic/lexical RPCs, rank fusion and passage hydration |
| `app/grounding/` | Citation validation and text/table highlighting |
| `app/database/`, `app/alembic/` | Data access, models and migrations |
| `app/services/` | Shared Azure OpenAI client and token-estimation adapter |
| `app/telemetry.py` | Optional Azure Monitor spans |
| `ingestion/` | Local corpus preparation and explicit upload |
| `evaluation/`, `playground/` | Inspection harnesses and evaluation material |
| `tests/` | Offline and explicitly marked live tests |

## Logs and Azure tracing

Each accepted stream request creates a `trace_id`. Local development uses the
content-rich `console` / `full` profile in `.env.example`. Production requires
JSON logs and rejects full assistant traces; use `summary` or `off`.

The main event sequence is:

```text
chat_turn_received
assistant_model_request → assistant_model_response
assistant_tool_started → retrieval_* → assistant_tool_completed
assistant_grounding_proposed → assistant_grounding_accepted|rejected
chat_turn_persistence_started → chat_turn_persistence_completed
chat_turn_completed → chat_stream_completed
```

Summary logging includes approved scalar metadata such as stages, durations,
model/tool names, counts, token usage and safe error classes. Production application
events default to a 4 KiB ceiling. It excludes prompts, history, passages, tool
payloads, application IDs other than `trace_id`, and exception messages/tracebacks.
Full local traces redact known secret/private fields, but still contain user and
filing content and should remain private.

Azure Monitor is a separate opt-in channel:

```dotenv
AZURE_MONITOR_TRACING_ENABLED=true
AZURE_MONITOR_CAPTURE_CONTENT=false
AZURE_MONITOR_TRACE_SAMPLE_RATE=1
# APPLICATION_INSIGHTS_CONNECTION_STRING=<secret from the chosen Azure resource>
```

The assistant-run span carries `app.trace_id` and contains assistant, keyword and
query-embedding calls. The exporter disables automatic HTTP/framework instrumentation,
log export, metrics, live metrics and local retry storage. Content capture can be
enabled independently of the production log profile. The application log allowlist
does not sanitize Azure spans; the [audit](../docs/repository-audit.md) records
exception-content and embedding-usage gaps in the current implementation.

See [configuration](../docs/configuration.md) for all controls and
[Azure operations](../docs/guides/azure-foundry-setup.md) for queries and dated
resource observations.

## Ingestion and evaluation

- [Ingestion guide](ingestion/README.md): download → parse → chunk checkpoints →
  paid embedding checkpoints → Supabase upload → verification.
- [Evaluation guide](evaluation/README.md): real search-tool inspection, full
  assistant inspection, branch comparison, live test selection and benchmarks.

The current local checkpoints contain 27 documents and 6,373 chunks. The old
retrieval benchmark's expected indexes are invalid for that layout. Preserve the
historical baseline and remap expectations before using it as a release gate.

The [repository audit](../docs/repository-audit.md) separates documentation
corrections from code, data and operational decisions still awaiting action.
