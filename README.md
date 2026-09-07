# Document Copilot

An internal SEC-filing research assistant for the fictional investment research
firm **10-K Club**. Analysts sign in, ask questions, inspect cited passages and
tables, and return to their saved conversations.

The application is implemented. FastAPI validates citations and stores a complete
turn before sending the answer to the browser. The current local corpus has 27
filings: 25 company 10-Ks for fiscal 2021–2025 and two BSP offering documents.
Pilot scope and release verification still have open decisions; see the
[project status](docs/todos.md) and [repository audit](docs/repository-audit.md).

## Start here

- [Documentation index](docs/README.md): setup, operation, implementation, and historical records.
- [Architecture](docs/architecture.md): service boundaries and current behavior.
- [Client brief](docs/client-brief.md): product goals and intended rollout.
- [Agent instructions](AGENTS.md): repository conventions for coding agents.

## Stack

| Layer | Implementation |
| --- | --- |
| Backend | Python 3.12+, FastAPI, PydanticAI |
| Frontend | Vite, React, TypeScript, AI SDK UI, Tailwind CSS, shadcn/ui |
| Identity and data | Supabase Auth and Postgres |
| Schema | SQLAlchemy models and Alembic migrations |
| Retrieval | pgvector, Postgres full-text search, weighted rank fusion in Python |
| Models | OpenAI models through Azure AI Foundry's OpenAI-compatible v1 endpoint |
| Hosting | Separate Railway services: Uvicorn API and Caddy-served SPA |

## Run locally

Install Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/),
plus Node.js 22+ and pnpm **11.18.0** (the version in
[frontend/package.json](frontend/package.json)). The backend Docker image uses
Python 3.13. You need a configured [Supabase project](docs/guides/supabase-setup.md),
[Azure Foundry deployments](docs/guides/azure-foundry-setup.md), and an administrator-created
Supabase email/password account.

In one terminal, from the repository root:

```bash
cd backend
uv sync --locked
cp -n .env.example .env
# Fill in the required credentials and deployment names in .env.
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --reload
```

The migration command changes the database selected by `DATABASE_URL`. Use a
development project for local work. Open the [API health endpoint](http://localhost:8000/health)
or [interactive API documentation](http://localhost:8000/docs).

In a second terminal, from the repository root:

```bash
cd frontend
pnpm install --frozen-lockfile
cp -n .env.example .env
# Fill in the Supabase public URL/key; the default API URL is localhost:8000.
pnpm dev
```

Open [the app](http://localhost:5173). Sign-in requires an existing account;
there is no sign-up or password-reset screen. A filing question also requires an
ingested corpus. `/health` confirms the API is running, not that Azure or Supabase
is reachable. See [backend setup](docs/guides/backend-setup.md),
[frontend setup](docs/guides/frontend-setup.md), and the
[configuration reference](docs/configuration.md) for details.

## Check changes

From `backend/`, with a valid local configuration:

```bash
uv run --locked pytest -m "not integration"
uv run --locked ruff check app tests ingestion evaluation playground
uv run --locked ruff format --check app tests ingestion evaluation playground
```

From `frontend/`:

```bash
pnpm lint
pnpm build
```

`pnpm build` runs TypeScript project checks (`tsc -b`) and a production Vite build.
Frontend flows are verified manually; the repository does not use a frontend test
runner. Live backend tests, model calls, and evaluation runs are opt-in. See the
[evaluation guide](backend/evaluation/README.md) and the audit for the latest local
check results and known failures. The [QA checklist](docs/qa-suite-todo.md) tracks
the suite layers; [QA findings](docs/qa-findings-2026-09-05.md) records the live
permission and research-budget failures.

## Prepare the corpus

Read [data/README.md](data/README.md) before downloading: the downloader has a
placeholder SEC contact and **clears existing downloads by default**. Its year
selection moves with the calendar, so preserve a corpus snapshot when reproducing
an evaluation.

The [ingestion guide](backend/ingestion/README.md) covers parsing, chunk checkpoints,
paid Azure embeddings, Supabase upload, verification, and deliberate resets.
Ingestion runs separately from the web services.

## Repository map

```text
investment-research-agent/
├── AGENTS.md
├── README.md
├── backend/
│   ├── app/           # API, agent, retrieval, grounding, schema and migrations
│   ├── ingestion/     # Active pipeline, operator scripts and historical archive
│   ├── evaluation/    # Diagnostics, retrieval evaluator and answer benchmark
│   ├── playground/    # IPython cell-based live inspection
│   └── tests/         # Offline tests and opt-in integration tests
├── frontend/          # React SPA and Caddy production image
├── data/              # Downloader; corpus and checkpoints are gitignored
└── docs/              # Current guides, status, architecture and audit
```

Local `azure-image-backups/` and `azure-storage-backups/` belong to a separate
invoice-review application. Their recovery notes and ignored payloads are outside
Document Copilot's runtime; their disposition is recorded in the audit.
