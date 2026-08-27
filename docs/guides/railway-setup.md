# Railway deployment

This repo deploys to Railway as two services from one project:

- `document-copilot-backend` from `backend/` — FastAPI + Uvicorn.
- `document-copilot-frontend` from `frontend/` — Vite React build served by Caddy.

Supabase stays hosted at Supabase. Do not add Railway Postgres for this app.

## Before Railway

Have these ready:

- A GitHub repo with this project pushed, or the local repo plus the Railway CLI.
- A Supabase project from [Supabase setup](supabase-setup.md).
- An OpenAI API key.
- Production source documents loaded in Supabase, or be ready to run ingestion after deploy.

Use the direct Supabase Postgres URL for `DATABASE_URL`, not the transaction pooler URL.

## Option A: Railway UI

Use this path if you want to click through Railway yourself.

1. In Railway, click **New Project** → **Deploy from GitHub repo** and select this repo.
2. Name the backend service `document-copilot-backend`.
3. Open backend **Settings**:
   - **Root Directory:** `/backend`
   - **Healthcheck Path:** `/health`
   - Leave build and start commands blank. Railway uses `backend/Dockerfile`.
4. Add backend **Variables**:

```text
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your-anon-public-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-secret-key
DATABASE_URL=postgresql://postgres:your-password@db.your-project-ref.supabase.co:5432/postgres
OPENAI_API_KEY=sk-your-openai-api-key
ALLOWED_ORIGINS=http://localhost:5173
```

1. In backend **Settings** → **Deploy**, set the pre-deploy command:

```bash
uv run alembic upgrade head
```

1. Deploy the backend, then open **Networking** and generate a public domain.
1. Visit `https://your-backend.up.railway.app/health`. You should see `{"status":"ok"}`.
1. In the same project, click **New** → **GitHub Repo** and select this repo again.
1. Name the frontend service `document-copilot-frontend`.
1. Open frontend **Settings**:
   - **Root Directory:** `/frontend`
   - **Healthcheck Path:** `/health`
   - Leave build and start commands blank. Railway uses `frontend/Dockerfile`.
1. Add frontend **Variables** before deploying:

```text
VITE_API_BASE_URL=https://your-backend.up.railway.app
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-public-key
```

1. Deploy the frontend, then open **Networking** and generate a public domain.
1. Update the backend variable:

```text
ALLOWED_ORIGINS=https://your-frontend.up.railway.app
```

1. Redeploy the backend.

## Option B: MCP + CLI

Use this path if you want an agent in Cursor to drive the deploy like we did. The Railway MCP server is best for project creation, status, logs, and deployment diagnosis. The Railway CLI is still the most direct way to create services, set variables, upload monorepo subdirectories, generate domains, and run migrations.

1. Install and authenticate the CLI:

```bash
railway login
railway setup agent -y
```

1. Ask the agent to confirm Railway access with the MCP `whoami` or `list-projects` tool.
1. Ask the agent to create a private project with MCP:

```text
Create a private Railway project named document-copilot.
```

1. Link your local repo to the project:

```bash
railway link --project <project-id> --environment production
```

1. Create the two empty services:

```bash
railway add --service document-copilot-backend --json
railway add --service document-copilot-frontend --json
```

1. Set backend variables. Use `--stdin` for secret values so they are not printed in shell history:

```bash
railway variable set \
  SUPABASE_URL=https://your-project-ref.supabase.co \
  SUPABASE_ANON_KEY=your-anon-public-key \
  DATABASE_URL=postgresql://postgres:your-password@db.your-project-ref.supabase.co:5432/postgres \
  ALLOWED_ORIGINS=http://localhost:5173 \
  --service document-copilot-backend \
  --skip-deploys

printf "%s" "$SUPABASE_SERVICE_ROLE_KEY" | railway variable set SUPABASE_SERVICE_ROLE_KEY \
  --stdin \
  --service document-copilot-backend \
  --skip-deploys

printf "%s" "$OPENAI_API_KEY" | railway variable set OPENAI_API_KEY \
  --stdin \
  --service document-copilot-backend \
  --skip-deploys
```

1. Deploy the backend from the `backend/` folder and generate a domain:

```bash
railway up ./backend --path-as-root --service document-copilot-backend --detach
railway domain --service document-copilot-backend --json
```

1. Run migrations against production:

```bash
railway run --service document-copilot-backend -- sh -c "cd backend && uv run alembic upgrade head"
```

1. Set frontend variables before deploying. `VITE_*` values are baked into the frontend build:

```bash
railway variable set \
  VITE_API_BASE_URL=https://your-backend.up.railway.app \
  VITE_SUPABASE_URL=https://your-project-ref.supabase.co \
  VITE_SUPABASE_ANON_KEY=your-anon-public-key \
  --service document-copilot-frontend \
  --skip-deploys
```

1. Deploy the frontend from the `frontend/` folder and generate a domain:

```bash
railway up ./frontend --path-as-root --service document-copilot-frontend --detach
railway domain --service document-copilot-frontend --json
```

1. Update backend CORS and redeploy:

```bash
railway variable set ALLOWED_ORIGINS=https://your-frontend.up.railway.app \
  --service document-copilot-backend

railway redeploy --service document-copilot-backend --yes
```

1. Use MCP `get-status`, `get-logs`, or `railway-agent` to verify both services are `SUCCESS` and diagnose any failures.

## Supabase auth URLs

In Supabase, open **Authentication** → **URL Configuration**:

- **Site URL:** `https://your-frontend.up.railway.app`
- **Redirect URLs:** add `https://your-frontend.up.railway.app/*`

Keep `http://localhost:5173/*` too if you still run local development.

## Load or refresh corpus data

Document ingestion is a manual backend job against Supabase. From your local machine, with production env values in `backend/.env`:

```bash
cd backend
uv sync --extra ingest
uv run python -m ingest.load_source_documents
uv run python -m ingest.chunk_and_embed --all
```

Skip this if production Supabase already has source documents and chunks.

## Lessons from the first deploy

- Do not set `PORT` yourself. Railway provides it automatically, and both containers bind to that value.
- Keep ingestion-only dependencies out of the API image. `docling` lives behind `uv sync --extra ingest` because it pulls large ML/CUDA dependencies that can make image publishing slow or fail.
- Set frontend `VITE_*` variables before `railway up` or before a UI deploy. Redeploy the frontend after changing them.
- Keep the frontend `/health` route ahead of the SPA fallback in `frontend/Caddyfile`; otherwise Railway may receive `index.html` instead of a simple health response.
- If a Docker build succeeds but Railway fails while publishing the image, check image size and dependency bloat before retrying repeatedly.

## Final check

1. Open the frontend Railway URL.
2. Sign up or sign in with email.
3. Send a chat question.
4. Check these endpoints:

```text
https://your-backend.up.railway.app/health
https://your-frontend.up.railway.app/health
```

The backend should return `{"status":"ok"}` and the frontend should return `ok`.