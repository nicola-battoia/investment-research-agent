# Configuration reference

The backend reads configuration in [app/config.py](../backend/app/config.py); the
frontend reads browser configuration in [src/lib/env.ts](../frontend/src/lib/env.ts).
The backend resolves `.env` relative to `backend/`, regardless of the working
directory. Process environment values override that file. Required missing values
fail validation when settings are imported.

Copy the service's `.env.example` for development and fill in placeholders. Keep
real credentials out of documentation, version control and browser bundles.

## Required backend values

| Variables | Meaning |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Project URL and public key for user-scoped HTTP access |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only credential for privileged ownership checks and ingestion |
| `DATABASE_URL` | Psycopg URL for migrations and direct operator queries; required even though ordinary chat queries use HTTP |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` | Azure resource endpoint ending in `/openai/v1/` and its secret key |
| `AZURE_OPENAI_ASSISTANT_DEPLOYMENT` | Azure deployment alias used for answer-generation requests |
| `AZURE_OPENAI_KEYWORD_DEPLOYMENT` | Azure deployment alias used for typed keyword extraction |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Azure deployment alias used for query and corpus embeddings |
| `OPENAI_ASSISTANT_MODEL`, `OPENAI_ASSISTANT_REASONING_EFFORT` | Underlying model identity/profile and request reasoning effort |
| `OPENAI_KEYWORD_MODEL` | Underlying keyword-model identity |
| `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS` | Embedding identity for tokenization/checkpoints and vector width |
| `APP_ENVIRONMENT` | `development`, `test` or `production` |
| `ALLOWED_ORIGINS` | Comma-separated browser origins, including scheme and port |

Deployment aliases and model identities serve different purposes. The OpenAI client
sends the `AZURE_OPENAI_*_DEPLOYMENT` values as `model`; the `OPENAI_*_MODEL` fields
describe the model behind those aliases. This app uses Azure credentials, not a
separate `OPENAI_API_KEY`.

`DATABASE_URL` must start with `postgresql+psycopg://`. Use a direct connection or
the Supavisor **session** pooler on port 5432, not the transaction pooler on 6543.
Percent-encode reserved password characters. See [Supabase setup](guides/supabase-setup.md).

The checked-in schema and semantic RPCs use **1,536 dimensions**. Changing the
environment variable alone does not migrate the database or re-embed existing
chunks. Model/dimension changes need a deliberate corpus migration.

## Assistant limits: defaults versus example profile

These are the values in the working tree reviewed on 2026-09-05. The lower limits
in `.env.example` and the Railway runbook are explicit settings from the earlier
reliability rollout; they override the newer Python defaults when used.

| Setting | Python default when omitted | `.env.example` / documented Railway profile |
| --- | ---: | ---: |
| `OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS` | 2,500 | 3,000 |
| `ASSISTANT_MAX_TOTAL_INPUT_TOKENS` | 75,000 | 60,000 |
| `ASSISTANT_MAX_REQUEST_INPUT_TOKENS` | 50,000 | 32,000 |
| `ASSISTANT_MAX_TOTAL_OUTPUT_TOKENS` | 10,000 | 6,000 |
| `ASSISTANT_MAX_MODEL_REQUESTS` | 10 | 10 |
| `ASSISTANT_MAX_TOOL_CALLS` | 8 | 8 |
| `ASSISTANT_MAX_SEARCH_CALLS` | 5 | 5 |
| `ASSISTANT_MAX_SURROUNDING_CALLS` | 2 | 2 |
| `ASSISTANT_SEARCH_RESULT_LIMIT` | 10 | 10 |
| `ASSISTANT_EVIDENCE_PREVIEW_CHARACTERS` | 400 | 400 |
| `CHAT_TURN_TIMEOUT_SECONDS` | 180 | 180 |

Other defaults include five history pairs / 20,000 history characters, 150 unique
evidence passages, 20 citations, 120 seconds per tool, one tool retry and one output
retry. Tools run sequentially. The eight-call total includes `read_chunk`; per-tool
limits are ceilings, not separate allowances.

The Azure model adapter estimates input tokens locally from serialized request
characters. Completed assistant requests contribute provider-reported usage.
These bounds are per assistant run, not a shared quota limiter; keyword and embedding
calls have separate provider usage. Concurrent users, retries and Azure's reservation
rules can still cause throttling. Budget unification is an open
[audit finding](repository-audit.md#f04-token-budgets-differ-between-defaults-and-operator-profiles).

## Retrieval and HTTP defaults

| Setting group | Defaults |
| --- | --- |
| Retrieval candidates/results | 50 per branch / 10 fused results; hard ceilings 100 / 20 |
| Weighted RRF | Semantic 20, lexical 1, smoothing constant 60 |
| Keyword extraction | Up to 6 concept groups, 3 terms/group, 800 output tokens |
| Supabase HTTP deadlines | Connect/pool 5 seconds; read/write 15 seconds |
| Azure SDK retries | 3 retries |
| SSE | Status heartbeat every 15 seconds; final answer deltas of 160 characters |

`filing_years` filters use the **report-date year**, not the filing-date year.
Filing-date range filters are separate. See the settings module for all validated
limits and relationships; the table is a navigation aid, not a second schema.

## Logs and Azure traces

| Channel | Development example | Production profile |
| --- | --- | --- |
| `LOG_FORMAT` | `console` | `json` (required) |
| `ASSISTANT_TRACE_MODE` | `full` | `summary` or `off`; `full` is rejected |
| `LOG_MAX_EVENT_BYTES` | 4,096 | 4,096 default, configurable 1,024–65,536 |
| `AZURE_MONITOR_TRACING_ENABLED` | `false` | Opt-in; default `false` |
| `AZURE_MONITOR_CAPTURE_CONTENT` | `false` | Independent opt-in; default `false` |
| `AZURE_MONITOR_TRACE_SAMPLE_RATE` | 1 | Fraction from 0 to 1 when tracing is enabled |

`APPLICATION_INSIGHTS_CONNECTION_STRING` is required when Azure tracing is enabled.
Content capture requires tracing. The production profile **does allow Azure content
capture** even though it forbids full application logs; the two channels have separate
controls. The application's log allowlist and size bound do not apply to Azure spans.

Azure tracing wraps the assistant run, assistant model requests, keyword requests
and retrieval embeddings. It disables automatic framework/HTTP instrumentation,
Azure log export, metrics, live metrics and local exporter retry storage. Exporter
configuration is process-wide; restart the process to change it. The current embedding
usage mapping has a known gap, and exception events can contain content even with
capture disabled; both are recorded in the audit. See the
[Azure guide](guides/azure-foundry-setup.md) for operational queries.

## Frontend values

| Variable | Development value |
| --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` |
| `VITE_SUPABASE_URL` | The same Supabase project URL as the backend |
| `VITE_SUPABASE_ANON_KEY` | The project's browser-safe public key |

All three are required and embedded by Vite at build time. Changing production
values requires a new frontend build. Never place a service-role key, database URL,
Azure key or Application Insights connection string under `VITE_*`.
