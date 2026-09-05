# Supabase setup

Supabase hosts Postgres and email/password authentication. The browser signs in
with a public key; backend request paths use that user's JWT for database access.
Admin ingestion and some integration tests use a server-only service-role key.

Use an existing project when one is already configured. For a new environment,
create a project in the [Supabase dashboard](https://supabase.com/dashboard),
save its database password, and collect the values below. Dashboard labels can
change; the project's Connect/API settings expose the credentials.

## Configure the two services

| Project value | Backend variable | Frontend variable |
| --- | --- | --- |
| Project URL | `SUPABASE_URL` | `VITE_SUPABASE_URL` |
| Public anon key | `SUPABASE_ANON_KEY` | `VITE_SUPABASE_ANON_KEY` |
| Service-role key | `SUPABASE_SERVICE_ROLE_KEY` | Never put in the frontend |
| Direct or session Postgres URL | `DATABASE_URL` | Never put in the frontend |

The current application expects these names. See the
[configuration reference](../configuration.md) and each service's `.env.example`.
Keep secrets in ignored local env files or the hosting service's secret store.

Use a SQLAlchemy URL with the `postgresql+psycopg://` scheme for migrations.
Use the direct endpoint or the session pooler, normally port `5432`; do not use
the transaction pooler on `6543`. URL-encode special characters in credentials.
The direct endpoint may require IPv6 from the host running migrations; the
[Railway guide](railway-setup.md#decide-whether-backend-ipv6-is-required) explains
that deployment choice.

Application queries use the Supabase API clients. The database URL is principally
for Alembic/schema operations, not the browser or the normal chat request path.

## Private-pilot authentication

The implemented screen supports email **and password** sign-in, with no
self-service registration or password-reset screen.

For the intended manually provisioned pilot:

1. Enable the Email provider.
2. Disable **Allow new users to sign up** in the project's Auth configuration.
3. Create approved users administratively and arrange their credentials through
   the team's normal process.
4. Test sign-in and sign-out with an approved account, then verify a second
   account cannot access the first account's threads.

Hiding registration in the UI does not disable Supabase's registration API. The
backend accepts users authenticated by the configured Supabase project; it does
not implement a company-domain or email allowlist. The auth trigger creates a
public user record for new Auth users. Verify the hosted settings for each
environment rather than treating repository documentation as proof they are set.

Supabase documents the signup controls in its
[general Auth configuration](https://supabase.com/docs/guides/auth/general-configuration).
Set Site URL and permitted redirect URLs to the intended frontend domains if
using invitation, confirmation, or recovery links. Direct password sign-in itself
does not introduce a redirect flow, and recovery UI still needs a product decision.

## Apply the schema

Alembic owns schema changes. Do not recreate application tables manually in the
dashboard. From a configured `backend/`:

```bash
uv sync --locked --dev
uv run --locked alembic heads
uv run --locked alembic upgrade head --sql > /tmp/document-copilot-schema.sql
```

Offline SQL renders the migration chain from its assumed starting revision; it
does not inspect the connected database or identify only pending changes. Review
the intended migration range before applying:

```bash
uv run --locked alembic current
uv run --locked alembic upgrade head
```

Current repository head: `20260823_0008`. Migrations cover tables, indexes,
vector/full-text retrieval, RLS/grants, user synchronization, atomic chat-turn
completion, and chunk source offsets.

RLS separates users' chats, but authenticated users also retain direct write
permissions on their own messages/citations. The
[audit](../repository-audit.md#f02-assistant-message-provenance-is-not-enforced-at-the-database-boundary)
records the distinction between ownership isolation and trusted assistant output.

## Load and verify the corpus

Use the [checkpointed ingestion guide](../../backend/ingestion/README.md) from a
local operator environment. Parsing, embedding, and bulk upload are separate from
application startup and Railway deployment.

For live integration tests, use the [evaluation guide](../../backend/evaluation/README.md#offline-and-live-tests).
Some tests create and remove database records; choose their target deliberately.
