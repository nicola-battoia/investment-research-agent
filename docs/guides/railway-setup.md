# Railway setup

This is the end-to-end execution guide for the Docker-based Railway deployment. It incorporates the commands and corrections from the first production deployment. See [`railway-deployment-plan.md`](./railway-deployment-plan.md) for the repository audit, design rationale, deployment record, and remaining production gates.

## Verified target

| Resource | Name | ID or URL |
| --- | --- | --- |
| Railway project | `10-K Club` | `42cace43-5886-4706-b9f2-f8312e798507` |
| Environment | `production` | `7b864536-d01b-47f2-bf19-c44582daf6cf` |
| Backend service | `backend` | `974a863b-2ee3-455e-a903-fec1c92343ca` |
| Frontend service | `frontend` | `a0149246-5f2c-4a2c-86f6-cb58279a5458` |
| Backend domain | — | `https://10k-club-backend.up.railway.app` |
| Frontend domain | — | `https://10k-club.up.railway.app` |
| GitHub source | — | `nicola-battoia/investment-research-agent` |
| Initial branch | — | `railway-deploy` |

These are the exact values for the existing deployment. If the project or services are ever recreated, substitute the new IDs and domains returned in phases 2, 3, and 5.

The repository becomes two services:

| Service | Root Directory | Image entry point |
| --- | --- | --- |
| `backend` | `/backend` | `backend/Dockerfile` → FastAPI/Uvicorn |
| `frontend` | `/frontend` | `frontend/Dockerfile` → Caddy static server |

Supabase remains the database and authentication provider. Do not provision Railway Postgres. Keep Railway custom Build and Start Commands empty so the Dockerfiles remain the source of truth.

Run the commands below from the repository root unless a step says otherwise. After the initial `railway link`, the commands use explicit project, environment, and service IDs wherever the CLI supports them so they cannot silently target another resource.

## 1. Clear the release checks

Run the backend checks:

```sh
cd backend
uv run --locked pytest -m 'not integration'
uv run --locked ruff check app tests
uv run --locked ruff format --check app tests
```

Run the frontend checks:

```sh
cd ../frontend
pnpm exec tsc --noEmit
pnpm lint
pnpm build
cd ..
```

The first release finished with 228 backend tests passing and all Ruff, TypeScript, ESLint, and Vite build checks passing.

Optionally validate both production images locally:

```sh
docker build -t investment-research-backend ./backend

docker build \
  --build-arg VITE_API_BASE_URL=https://api.example.com \
  --build-arg VITE_SUPABASE_URL=https://example.supabase.co \
  --build-arg VITE_SUPABASE_ANON_KEY=local-build-check \
  -t investment-research-frontend \
  ./frontend
```

The placeholder frontend values only validate the image build. Do not deploy that locally built image.

## 2. Authenticate, link, and confirm access

Check the Railway CLI and authenticate if necessary:

```sh
railway --version
railway login
```

Upgrade first if the CLI reports that the required subcommands are unavailable:

```sh
railway upgrade --yes
```

Link the local repository to the existing project and `production` environment:

```sh
railway link
railway status --json
```

Select workspace `Nicola Battoia's Projects`, project `10-K Club`, and environment `production`. The status output must show project ID `42cace43-5886-4706-b9f2-f8312e798507` and environment ID `7b864536-d01b-47f2-bf19-c44582daf6cf`.

Confirm that Railway's GitHub App can see `nicola-battoia/investment-research-agent`. Local Git and GitHub CLI access do not prove that the Railway GitHub App has access. If the repository is absent from Railway's repository selector, add it to the GitHub App's selected-repository access before continuing.

Inspect existing services before creating anything:

```sh
railway service list \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --json
```

For a new deployment this should return `[]`.

## 3. Create empty services

Create services without a repository or image source:

```sh
railway add --service backend --json
railway add --service frontend --json
```

If the interactive flow asks `Enter a variable <esc to skip>`, press `Esc`. Variables are configured deliberately in phase 6.

Read back the service IDs:

```sh
railway service list \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --json
```

The created IDs for this project are:

```text
backend  974a863b-2ee3-455e-a903-fec1c92343ca
frontend a0149246-5f2c-4a2c-86f6-cb58279a5458
```

Do not run `railway add` again after these services exist.

## 4. Configure service settings

Configure the backend:

```sh
railway environment edit \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service-config 974a863b-2ee3-455e-a903-fec1c92343ca source.rootDirectory /backend \
  --service-config 974a863b-2ee3-455e-a903-fec1c92343ca build.builder DOCKERFILE \
  --service-config 974a863b-2ee3-455e-a903-fec1c92343ca build.buildEnvironment V3 \
  --service-config 974a863b-2ee3-455e-a903-fec1c92343ca build.dockerfilePath /backend/Dockerfile \
  --service-config 974a863b-2ee3-455e-a903-fec1c92343ca build.watchPatterns '["/backend/**"]' \
  --service-config 974a863b-2ee3-455e-a903-fec1c92343ca deploy.preDeployCommand 'alembic upgrade head' \
  --service-config 974a863b-2ee3-455e-a903-fec1c92343ca deploy.healthcheckPath /health \
  --service-config 974a863b-2ee3-455e-a903-fec1c92343ca deploy.multiRegionConfig.europe-west4-drams3a.numReplicas 1 \
  --message 'Configure backend service' \
  --json
```

Configure the frontend:

```sh
railway environment edit \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service-config a0149246-5f2c-4a2c-86f6-cb58279a5458 source.rootDirectory /frontend \
  --service-config a0149246-5f2c-4a2c-86f6-cb58279a5458 build.builder DOCKERFILE \
  --service-config a0149246-5f2c-4a2c-86f6-cb58279a5458 build.buildEnvironment V3 \
  --service-config a0149246-5f2c-4a2c-86f6-cb58279a5458 build.dockerfilePath /frontend/Dockerfile \
  --service-config a0149246-5f2c-4a2c-86f6-cb58279a5458 build.watchPatterns '["/frontend/**"]' \
  --service-config a0149246-5f2c-4a2c-86f6-cb58279a5458 deploy.healthcheckPath /health \
  --service-config a0149246-5f2c-4a2c-86f6-cb58279a5458 deploy.multiRegionConfig.europe-west4-drams3a.numReplicas 1 \
  --message 'Configure frontend service' \
  --json
```

Do not set custom Build or Start Commands. The backend image `CMD` expands Railway's `PORT`; the frontend uses the Caddy image command.

Only in a brand-new environment, before any variables contain secrets, inspect the combined configuration:

```sh
railway environment config \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --json
```

Skip this command when working on the existing configured environment. Do not paste or share `railway environment config --json` or `railway variable list --json` after variables have been added: current CLI output can include raw secret values. Use `railway deployment list --json` later to inspect deployment metadata.

### Decide whether backend IPv6 is required

Inspect only the hostname and port of `DATABASE_URL` without printing the password.

- `db.<project-ref>.supabase.co:5432`: direct Supabase connection; enable Railway outbound IPv6.
- `*.pooler.supabase.com:5432`: Supavisor session pooler; leave outbound IPv6 disabled.
- Port `6543`: transaction pooler; do not use it for Alembic.

The deployed project uses the Supavisor session pooler on port `5432`, so IPv6 remains disabled. If switching to the direct host, run:

```sh
railway outbound-network ipv6 enable \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --json

railway environment edit \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --message 'Enable backend outbound IPv6' \
  --json
```

## 5. Generate and verify public domains

For each newly created service, create one domain before setting cross-service URLs or connecting GitHub. If `railway domain list` already shows an active domain, reuse it instead of generating another.

```sh
railway domain \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --json

railway domain \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service a0149246-5f2c-4a2c-86f6-cb58279a5458 \
  --json
```

Read them back:

```sh
railway domain list \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --json

railway domain list \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service a0149246-5f2c-4a2c-86f6-cb58279a5458 \
  --json
```

Use the active values returned by `domain list`:

```text
Backend:  https://10k-club-backend.up.railway.app
Frontend: https://10k-club.up.railway.app
```

Set these final HTTPS URLs explicitly in phase 6. During the first deployment, a `${{service.RAILWAY_PUBLIC_DOMAIN}}` reference resolved to an older generated domain after domain renaming. The explicit active URLs avoid building that stale value into the Vite bundle.

## 6. Set variables before connecting the source

Do not upload local `.env` files wholesale and do not set `PORT`.

### Backend non-secret values

Replace the Supabase public values if the project changes:

```sh
railway variable set \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  'SUPABASE_URL=https://<project-ref>.supabase.co' \
  'SUPABASE_ANON_KEY=<publishable-anon-key>' \
  OPENAI_EMBEDDING_MODEL=text-embedding-3-small \
  OPENAI_EMBEDDING_DIMENSIONS=1536 \
  OPENAI_KEYWORD_MODEL=gpt-5.4-nano \
  OPENAI_ASSISTANT_MODEL=gpt-5.6-terra \
  OPENAI_ASSISTANT_REASONING_EFFORT=medium \
  OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS=3000 \
  ALLOWED_ORIGINS=https://10k-club.up.railway.app \
  LOG_LEVEL=INFO \
  LOG_FORMAT=json \
  ASSISTANT_TRACE_MODE=summary \
  --json
```

`ALLOWED_ORIGINS` is the frontend origin, not the backend URL. It must exactly match the browser's origin, including `https://` and excluding paths and a trailing slash.

### Backend secrets

Set each secret through hidden shell input so it does not enter shell history. Do not paste secrets into documentation, chat, or visible CLI arguments.

```sh
read -rs 'RAILWAY_SECRET_VALUE?Paste SUPABASE_SERVICE_ROLE_KEY: '
printf '\n'
printf '%s' "$RAILWAY_SECRET_VALUE" | railway variable set \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --stdin SUPABASE_SERVICE_ROLE_KEY
unset RAILWAY_SECRET_VALUE
```

```sh
read -rs 'RAILWAY_SECRET_VALUE?Paste postgresql+psycopg DATABASE_URL: '
printf '\n'
printf '%s' "$RAILWAY_SECRET_VALUE" | railway variable set \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --stdin DATABASE_URL
unset RAILWAY_SECRET_VALUE
```

```sh
read -rs 'RAILWAY_SECRET_VALUE?Paste funded OpenAI API key: '
printf '\n'
printf '%s' "$RAILWAY_SECRET_VALUE" | railway variable set \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --stdin OPENAI_API_KEY
unset RAILWAY_SECRET_VALUE
```

`DATABASE_URL` must use `postgresql+psycopg://`, a direct or session-pooler host on port `5432`, and a percent-encoded password. The settings validator rejects plain `postgresql://`.

Before deployment, confirm that the OpenAI API organization or project owning the key has an active API balance and sufficient project limits at <https://platform.openai.com/settings/organization/billing/overview>. A ChatGPT or Codex subscription does not supply API credits. An exhausted balance produces `429 credit_balance_exhausted` even though Railway, CORS, authentication, and the stream endpoint are healthy.

### Frontend build-time values

```sh
railway variable set \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service a0149246-5f2c-4a2c-86f6-cb58279a5458 \
  VITE_API_BASE_URL=https://10k-club-backend.up.railway.app \
  'VITE_SUPABASE_URL=https://<project-ref>.supabase.co' \
  'VITE_SUPABASE_ANON_KEY=<publishable-anon-key>' \
  --json
```

`VITE_API_BASE_URL` is the backend domain. The three `VITE_*` values are public and are embedded into the generated JavaScript during `pnpm build`. A variable change therefore requires a frontend rebuild, not only a restart. Never place the service-role key or another secret in a `VITE_*` variable.

### Supabase Authentication URL Configuration

In Supabase Dashboard → Authentication → URL Configuration:

- Set Site URL to `https://10k-club.up.railway.app`.
- Add `https://10k-club.up.railway.app` as an allowed redirect URL.
- Keep the localhost redirect used by local Vite development, normally `http://localhost:5173`, if local development continues.

Password sign-in does not currently use redirects. These values matter for password recovery and any future magic-link or OAuth flow. The localhost entry is only selected when testing those flows from the local frontend.

## 7. Commit and push the release candidate

Connecting a source deploys the remote branch, not uncommitted local files. Review `git status` first. The broad `git add` below assumes every change under those paths belongs to the release; stage narrower paths if the worktree contains unrelated work.

```sh
git status --short --branch
git diff --check
git add backend frontend docs/guides/railway-setup.md docs/guides/railway-deployment-plan.md
git diff --cached --stat
git diff --cached --check
git commit -m 'Prepare services for Railway deployment'
git push origin railway-deploy
```

Verify that local and remote are synchronized:

```sh
git rev-list --left-right --count origin/railway-deploy...railway-deploy
```

Expected output:

```text
0	0
```

## 8. Connect GitHub sources last

Connect the backend:

```sh
railway service source connect \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --repo nicola-battoia/investment-research-agent \
  --branch railway-deploy \
  --json
```

Connect the frontend:

```sh
railway service source connect \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service a0149246-5f2c-4a2c-86f6-cb58279a5458 \
  --repo nicola-battoia/investment-research-agent \
  --branch railway-deploy \
  --json
```

These commands trigger the first builds. Do not use `railway up` for this GitHub-autodeploy workflow: it uploads local files instead of configuring the repository source. `railway run` executes locally with Railway variables and is not the production migration mechanism.

Confirm source attachment:

```sh
railway service list \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --json
```

Both services must show repository `nicola-battoia/investment-research-agent` and status progressing toward `SUCCESS`.

## 9. Verify the release

### Wait for terminal deployment status

```sh
railway deployment list \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --limit 3 \
  --json

railway deployment list \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service a0149246-5f2c-4a2c-86f6-cb58279a5458 \
  --limit 3 \
  --json
```

`QUEUED`, `BUILDING`, and `DEPLOYING` are intermediate states. Continue polling. Only `SUCCESS` is a successful release. Inspect logs for `FAILED` or `CRASHED`.

The deployment manifest returned here should show `builder: DOCKERFILE`, the correct Dockerfile path, Root Directory, Watch Paths, healthcheck, and backend Pre-Deploy Command.

### Verify public endpoints and SPA routing

```sh
curl --fail --silent --show-error --include \
  https://10k-club-backend.up.railway.app/health

curl --fail --silent --show-error --include \
  https://10k-club.up.railway.app/health

curl --fail --silent --show-error --include \
  https://10k-club.up.railway.app/sign-in
```

Expected results:

```text
Backend /health:  HTTP 200 and {"status":"ok"}
Frontend /health: HTTP 200 and ok
Frontend /sign-in: HTTP 200 and the SPA HTML, not 404
```

The backend intentionally has no `/` route; `GET /` and `/favicon.ico` returning 404 are not failures.

### Verify browser CORS

```sh
curl --include --request OPTIONS \
  https://10k-club-backend.up.railway.app/chat/threads \
  --header 'Origin: https://10k-club.up.railway.app' \
  --header 'Access-Control-Request-Method: POST' \
  --header 'Access-Control-Request-Headers: authorization,content-type'
```

Expected headers include:

```text
HTTP/2 200
access-control-allow-origin: https://10k-club.up.railway.app
access-control-allow-credentials: true
```

`http://10k-club.up.railway.app` is a different origin and must not be used. Railway serves the frontend over HTTPS.

### Verify the compiled frontend API URL

Capture the current fingerprinted JavaScript path and inspect only embedded Railway URLs:

```sh
RAILWAY_FRONTEND_ASSET="$(
  curl --fail --silent --show-error https://10k-club.up.railway.app/ \
    | rg -o '/assets/index-[^" ]+\.js' \
    | head -n 1
)"

curl --fail --silent --show-error \
  "https://10k-club.up.railway.app${RAILWAY_FRONTEND_ASSET}" \
  | rg -o 'https://[A-Za-z0-9.-]+\.up\.railway\.app' \
  | sort -u

unset RAILWAY_FRONTEND_ASSET
```

The output must include `https://10k-club-backend.up.railway.app` and must not include an obsolete backend domain. Because Vite embeds the value during the image build, a corrected variable is ineffective until a new frontend deployment reaches `SUCCESS`. Hard-refresh the browser after that deployment.

### Verify the browser flow

Open <https://10k-club.up.railway.app/sign-in> and verify:

1. The page reports `FastAPI connected`.
2. Supabase password sign-in succeeds.
3. Creating a chat succeeds.
4. A greeting produces a streamed assistant response.
5. A question about an ingested filing performs retrieval and returns supported citations.
6. Refreshing `/chat/<thread-id>` restores the SPA and persisted messages.
7. Signing out and signing back in preserves the user's chats.

An HTTP 200 from `/chat/stream` only confirms that the SSE stream opened. The stream can still contain a structured failure event, so the visible assistant answer is part of the release gate.

### Inspect bounded logs

```sh
railway logs \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --since 30m \
  --lines 300 \
  --json

railway logs \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --http \
  --status '>=400' \
  --since 30m \
  --lines 100 \
  --json
```

Always bound `railway logs` with `--lines`, `--since`, or `--until`; otherwise it streams indefinitely.

Alembic and Uvicorn write some informational startup lines to stderr, so Railway may label messages containing `INFO` as error severity. One Pre-Deploy container stopping before the runtime container starts is expected. Repeated runtime restarts are not.

Before promotion, logs must avoid secret values, full prompts, conversation history, retrieved passages, and serialized frame-local variables. The initial deployment exposed an observability defect where `exc_info=True` plus structured traceback rendering produced excessively large exception events. That code-level hardening is tracked separately and remains a production gate.

## 10. Correct common first-deployment failures

### `Disallowed CORS origin`

Confirm that the value is the exact HTTPS frontend origin, then let the automatic backend redeploy finish:

```sh
railway variable set \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  ALLOWED_ORIGINS=https://10k-club.up.railway.app \
  --json
```

Re-run the CORS preflight only after the newest backend deployment is `SUCCESS`.

### Frontend says it cannot reach the API

If CORS passes, inspect the compiled bundle. Correct the backend URL on the frontend service:

```sh
railway variable set \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service a0149246-5f2c-4a2c-86f6-cb58279a5458 \
  VITE_API_BASE_URL=https://10k-club-backend.up.railway.app \
  --json
```

This triggers the required frontend rebuild. Wait for `SUCCESS`, then hard-refresh or use a private browser window.

### Assistant says it is temporarily unavailable

Search for the safe error code:

```sh
railway logs \
  --project 42cace43-5886-4706-b9f2-f8312e798507 \
  --environment 7b864536-d01b-47f2-bf19-c44582daf6cf \
  --service 974a863b-2ee3-455e-a903-fec1c92343ca \
  --since 30m \
  --lines 50 \
  --filter credit_balance_exhausted \
  --json
```

`429 credit_balance_exhausted` means the OpenAI API project has no usable API balance. Adding API credits to the organization that owns the current key requires no Railway redeploy. If moving to a funded key, replace `OPENAI_API_KEY` through `--stdin`; the variable change triggers a backend redeploy.

## 11. Supabase ingestion and branch promotion

Ingestion remains a deliberate offline operation. Use the numbered workflow documented in [`../../backend/ingestion/README.md`](../../backend/ingestion/README.md); do not run ingestion inside either web service or as a deployment migration.

After all release gates pass:

1. Merge `railway-deploy` into `main` through review.
2. Change both production service source branches to `main`.
3. Retain `railway-deploy` only for a separate staging environment if it has a continuing purpose.
4. Verify the next frontend-only commit deploys only the frontend and the next backend-only commit deploys only the backend.

The repository currently has no GitHub Actions workflows. Keep Railway **Wait for CI** disabled until matching checks exist in GitHub Actions.
