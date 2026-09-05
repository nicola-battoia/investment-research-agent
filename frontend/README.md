# Document Copilot frontend

A Vite + React + TypeScript SPA for private SEC-filing research. It uses Supabase
email/password auth, React Router, AI SDK chat state, Tailwind CSS and shadcn/ui.
The backend owns retrieval, generation, citation validation and persistence.

## Set up and run

Use Node.js 22+ and pnpm 11.18.0. From this directory:

```bash
pnpm install --frozen-lockfile
cp -n .env.example .env
# Set the Supabase public URL/key and backend URL.
pnpm dev
```

Open [localhost:5173](http://localhost:5173). Start FastAPI separately using the
[backend guide](../docs/guides/backend-setup.md). Its `ALLOWED_ORIGINS` must
include the exact origin printed by Vite, including the port.

The pilot has no sign-up or password-reset screen. An administrator must create
the account and disable public signup in Supabase. Hiding signup in this UI does
not enforce that hosted setting. See [Supabase setup](../docs/guides/supabase-setup.md).

## Configuration

[src/lib/env.ts](src/lib/env.ts) validates these public values:

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | FastAPI origin; locally `http://localhost:8000` |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Browser-safe Supabase public key |

Vite embeds these values at build time. Production changes require a rebuild.
Never use backend secrets in frontend environment variables.

## User flows

| Route | Behavior |
| --- | --- |
| `/sign-in` | Email/password sign-in and API process-health indicator |
| `/` | Protected workspace; selects the most recently updated thread or offers a new chat |
| `/chat/:threadId` | Protected saved conversation |
| Other paths | Redirect to `/` |

The sidebar creates, renames and deletes threads and signs out. The composer
supports Enter to send, Shift+Enter for a newline, a 10,000-character limit and
Stop while a response is running.

The app displays status heartbeats while the backend works. Final answer text
arrives only after grounding and persistence, followed by citations. Selecting a
numbered source opens its excerpt, filing metadata, SEC link and full text/table
passage. Wide screens use a sidebar; smaller screens use a sheet.

Errors distinguish session expiry, ownership, missing threads, validation, network
failures and typed research failures. A failed stream can be reconciled with the
stored thread, and Retry retains the client message ID. Stop restores the draft;
the audit records an outstanding edge case when a turn commits just before Stop.

## Code map

| Location | Responsibility |
| --- | --- |
| `src/App.tsx` | Routes |
| `src/lib/auth.tsx`, `supabase.ts`, `access-token.ts` | Session and authentication |
| `src/lib/api.ts`, `http.ts` | Typed product calls, bearer headers and 10-second JSON-request timeout |
| `src/lib/chat-transport.ts` | Authenticated SSE transport; sends one newest user message |
| `src/pages/` | Sign-in and thread loading/navigation |
| `src/components/chat/` | Conversation, composer, thread sidebar and citation display |
| `src/components/ui/` | shadcn primitives |
| `src/index.css` | Theme, fonts and Tailwind imports |

Ordinary API calls use the product methods exported by `api.ts`.
Streaming uses `createChatTransport`; it does not use the JSON request wrapper's
10-second timeout.

## Verify changes

```bash
pnpm lint
pnpm build
```

The build runs `tsc -b` across the referenced TypeScript projects, then Vite.
For type checking alone, use `pnpm exec tsc -b`. A bare `tsc --noEmit` at this
solution-level tsconfig does not check its referenced source projects.

Per [AGENTS.md](AGENTS.md), do not add a frontend test runner. Check the following
in a browser when relevant; this list is a checklist, not a claim that the latest
release has passed it:

| Check | Expected result |
| --- | --- |
| Existing account sign-in/sign-out | Protected routes require a session; chats return after sign-in |
| Expired session | Useful sign-in action, no hidden success |
| Two different accounts | Each sees only its own threads/messages/citations |
| Greeting and filing question | Conversational response, then a cited filing answer |
| Unsupported/advice question | Appropriate refusal without invented evidence |
| Text/table citation | Correct excerpt, highlighted passage/cells, working SEC link |
| Refresh a saved thread URL | SPA loads and saved messages/citations return |
| Network failure and Retry | Clear error, reconciliation, no duplicated completed turn |
| Stop near completion | Check server persistence as well as the restored draft |
| Narrow screen and keyboard | Usable navigation, source sheet, focus and composer |

## Production

[Dockerfile](Dockerfile) builds the SPA with the three public `VITE_*` arguments.
[Caddyfile](Caddyfile) serves `dist/`, exposes `/health`, provides SPA route
fallback, compresses responses and caches fingerprinted assets.

See the [Railway runbook](../docs/guides/railway-setup.md) for release steps.
The [audit](../docs/repository-audit.md) records the current bundle warning,
unused starter assets and remaining authenticated browser checks.
