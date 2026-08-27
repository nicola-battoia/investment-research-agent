# Railway setup

This is the concise execution guide for the Docker-based Railway deployment. See [`railway-deployment-plan.md`](./railway-deployment-plan.md) for the repository audit, rationale, variable inventory, and operational details.

## Architecture

Deploy the GitHub repository as two services in one Railway project:

| Service | Root Directory | Image entry point |
| --- | --- | --- |
| `backend` | `/backend` | `backend/Dockerfile` → FastAPI/Uvicorn |
| `frontend` | `/frontend` | `frontend/Dockerfile` → Caddy static server |

Supabase remains the hosted database and authentication provider. Do not add Railway Postgres.

Railway builds a service's `Dockerfile` automatically when it is at the service Root Directory. Leave Railway's custom Build and Start Commands empty so the Dockerfiles remain the source of truth.

## Before connecting GitHub

1. Confirm Railway's GitHub App can access `nicola-battoia/investment-research-agent`.
2. Create empty `backend` and `frontend` services in the existing Railway project.
3. Configure both services before attaching the source:

| Setting | `backend` | `frontend` |
| --- | --- | --- |
| Root Directory | `/backend` | `/frontend` |
| Watch Paths | `/backend/**` | `/frontend/**` |
| Builder | Dockerfile (automatic detection) | Dockerfile (automatic detection) |
| Custom Build Command | empty | empty |
| Custom Start Command | empty | empty |
| Pre-Deploy Command | `alembic upgrade head` | empty |
| Healthcheck Path | `/health` | `/health` |

4. Enable outbound IPv6 on `backend` if `DATABASE_URL` uses Supabase's direct database hostname.
5. Generate a public Railway domain for each empty service.

Creating domains before the source connection lets both services use their final cross-service URLs on the first deployment.

## Variables

Do not upload local `.env` files wholesale and do not set `PORT`; Railway supplies it.

### Shared browser-safe values

These values may be Railway shared variables:

```text
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your-anon-public-key
```

### Backend

```text
SUPABASE_URL=${{shared.SUPABASE_URL}}
SUPABASE_ANON_KEY=${{shared.SUPABASE_ANON_KEY}}
SUPABASE_SERVICE_ROLE_KEY=<secret>
DATABASE_URL=postgresql+psycopg://...
OPENAI_API_KEY=<secret>
OPENAI_EMBEDDING_MODEL=<model>
OPENAI_EMBEDDING_DIMENSIONS=<integer>
OPENAI_KEYWORD_MODEL=<model>
OPENAI_ASSISTANT_MODEL=<model>
OPENAI_ASSISTANT_REASONING_EFFORT=<effort>
OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS=<integer>
ALLOWED_ORIGINS=https://${{frontend.RAILWAY_PUBLIC_DOMAIN}}
LOG_LEVEL=INFO
LOG_FORMAT=json
ASSISTANT_TRACE_MODE=summary
```

`DATABASE_URL` must use Psycopg 3's `postgresql+psycopg://` scheme. Use the Supabase direct or session-pooler connection on port `5432`, not the transaction pooler on port `6543`. Percent-encode reserved characters in the password.

Set `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, and `OPENAI_API_KEY` through Railway's UI or CLI standard input so they are not recorded in shell history.

### Frontend

```text
VITE_API_BASE_URL=https://${{backend.RAILWAY_PUBLIC_DOMAIN}}
VITE_SUPABASE_URL=${{shared.SUPABASE_URL}}
VITE_SUPABASE_ANON_KEY=${{shared.SUPABASE_ANON_KEY}}
```

The frontend Dockerfile declares these values as Docker build arguments because Vite embeds them in the browser bundle at build time. Never expose the service-role key or another secret through a `VITE_*` variable.

## Connect the GitHub source

Connect both services to:

```text
Repository: nicola-battoia/investment-research-agent
Branch: railway-deploy
```

Connecting the source triggers the first builds. Future pushes to `railway-deploy` trigger the matching service based on its Watch Paths.

With the current Railway CLI, the source connections are:

```sh
railway service source connect \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment production \
  --service backend \
  --repo nicola-battoia/investment-research-agent \
  --branch railway-deploy

railway service source connect \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment production \
  --service frontend \
  --repo nicola-battoia/investment-research-agent \
  --branch railway-deploy
```

`railway link` only selects a default Railway target for local CLI commands. `railway up` uploads local source instead of configuring GitHub autodeployment, and `railway run` executes locally with Railway variables. Neither is needed for this deployment path.

## Verify

Wait until both deployments reach `SUCCESS`, then verify:

```text
https://<backend-domain>/health  -> {"status":"ok"}
https://<frontend-domain>/health -> ok
```

Also verify browser CORS, Supabase password sign-in, a refreshed client-side route, and a complete streamed chat response.

## Local image checks

Build the images from their service roots:

```sh
docker build -t investment-research-backend ./backend

docker build \
  --build-arg VITE_API_BASE_URL=https://api.example.com \
  --build-arg VITE_SUPABASE_URL=https://example.supabase.co \
  --build-arg VITE_SUPABASE_ANON_KEY=local-build-check \
  -t investment-research-frontend \
  ./frontend
```

The placeholder frontend values are only for validating the image build; do not deploy that locally built image.

## Supabase auth and ingestion

In Supabase Authentication URL Configuration, add the Railway frontend domain as the Site URL and an allowed redirect URL. Keep the localhost redirect if local development continues.

Ingestion remains a deliberate offline operation. Use the numbered workflow documented in [`../../backend/ingestion/README.md`](../../backend/ingestion/README.md); do not run ingestion inside either web service or as a deployment migration.
