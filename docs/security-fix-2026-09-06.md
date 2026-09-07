# Chat integrity fix — 2026-09-06

Signed-in users can no longer forge, edit or delete individual saved messages or
citations. Only the backend can complete a turn, after validating the user,
thread ownership and assistant grounding. Users retain access to their own chat
history and can create, rename and delete whole chats.

This closes Q01 in the [QA findings](qa-findings-2026-09-05.md) and F02 in the
[repository audit](repository-audit.md). Research budget failures and other audit
findings remain separate work.

## What changed

- [The orchestrator](../backend/app/chat/orchestrator.py) now saves the validated
  result through its server-only Supabase client. It passes the user ID already
  verified by the authentication dependency, never an identity from request metadata.
- [Migration 0010](../backend/app/alembic/versions/20260906_0010_server_chat_completion.py)
  adds the `complete_chat_turn` signature with required `p_owner_id`. Only
  `service_role` can execute it. It remains `SECURITY INVOKER` and uses an empty
  search path. It rechecks ownership under a row lock, enforces the expected even
  position, and atomically saves messages, citations, usage and the thread update.
- [Migration 0011](../backend/app/alembic/versions/20260906_0011_lock_chat_writes.py)
  removes the old function signature and browser write grants and policies on
  `chat_messages` and `message_citations`. Both user and assistant messages become
  read-only history, preventing role changes and poisoning saved user questions.
- Whole-chat deletion still uses the user's JWT. Its foreign-key cascade removes
  the saved messages and citations. RLS still isolates users and protects the
  filing corpus. The private QA schema remains inaccessible to browser and service roles.

Citation identity, retrieval/read provenance, excerpt matching and answer validation
remain in the backend grounding layer before persistence. The database enforces
ownership, integrity constraints and atomicity; it does not independently assess
whether the prose is supported by its citations.

## Rollout

Target: Supabase project `mzhtuxodihxbzdmdbxgd` and the existing Railway production
backend at `https://10k-club-backend.up.railway.app`.

1. Rehearsed both migrations and the permission/atomicity tests in a transaction;
   all DDL and temporary data were rolled back afterward.
2. Deployed the backend with the additive migration through `20260906_0010`.
   Railway deployment `d3b43f0e-4bb2-4f1d-a7ee-09214b2eebd8` reached `SUCCESS`.
3. Passed 16 real API/chat checks and verified the previous backend was inactive.
4. Applied `uv run --locked alembic upgrade head` to Supabase. The recorded head
   advanced to `20260906_0011`, removing the old write path.
5. Passed the SQL, public API and real assistant checks under the locked permissions.
6. Packaged the full migration chain in the final backend image. Deployment
   `491cdef0-1b21-45f6-a8ba-bea936cc7275` reached `SUCCESS`. One earlier final-image
   upload failed with a network error before creating a deployment and was retried.

For an existing older installation, use this order: additive migration, updated
backend, smoke test, then permission removal. Do not revoke the old path while
an old backend still depends on it. New installations can apply the full chain.
Prefer a forward correction over downgrading: migration 0011's downgrade
intentionally restores the old insecure permissions for schema reversibility.

The release was uploaded from a clean temporary build context containing the
backend runtime files and migrations, without local credentials, datasets or QA
results. Repository changes remain available in the working tree for review.

## Verification

| Check | Result |
| --- | --- |
| Offline backend suite | 302 passed; 15 live tests deselected |
| Ruff | Passed for app, evaluation and tests |
| Database role/RLS probes | 37 passed, 0 failed; all fixtures rolled back |
| Atomic server-only completion contract | Passed; no partial saves on invalid citations, missing sources, duplicate IDs or position conflicts |
| Public Supabase API with actual user JWTs | 34 passed, 0 failed |
| Deployed assistant API after lockdown | 16 passed, 0 failed; real Azure generation and Supabase storage |
| Deployed frontend | Sign-in, cited reply, source panel, reload and deletion verified; browser tampering rejected |

Evidence:

- [Database permission results](../backend/evaluation/results/permissions-2026-09-06.json)
- [Public API permission results](../backend/evaluation/results/permissions-http-2026-09-06.json)
- [Chat smoke results before lockdown](../backend/evaluation/results/chat-integrity-before-lockdown-2026-09-06.json)
- [Chat smoke results after lockdown](../backend/evaluation/results/chat-integrity-2026-09-06.json)
- [Browser permission results](../backend/evaluation/results/permissions-browser-2026-09-06.json)

The real chat smoke checks cited SSE output against reloaded text/citations,
replays the same client message without adding rows, rejects reuse of that ID
with different text, completes a follow-up, and checks renaming/deletion. It also
rejects another user's reads and mutations, supplied assistant messages, and
supplied citation parts. SQL tests reject a mismatched or null verified owner
even when a service token is used, and reject completion after chat deletion.

The browser reproduction now returns:

- Direct assistant edit: HTTP **403**.
- Old `complete_chat_turn` request: HTTP **404**, because that signature is removed.
- Current function with `p_owner_id`, called with a normal user token: HTTP **403**.
- Readback: the original assistant record is unchanged.

## Repeat the checks

From `backend/`, with credentials for the intended environment:

```bash
uv run --locked pytest -q -m 'not integration'
uv run --locked python -m evaluation.qa.permissions \
  --output evaluation/results/permissions-new.json
uv run --locked python -m evaluation.qa.permissions_http \
  --output evaluation/results/permissions-http-new.json
uv run --locked pytest -q tests/database/test_live_complete_chat_turn.py
uv run --locked python -m evaluation.qa.chat_integrity \
  --base-url https://10k-club-backend.up.railway.app \
  --output evaluation/results/chat-integrity-new.json
```

The live commands use disposable QA accounts and rolled-back or deleted fixtures.
The chat command makes real model calls. Omitting `--base-url` tests local FastAPI
with the configured real services. The browser verification used a separate
disposable account; no existing user's chats were modified. All temporary QA
accounts/chats were removed, and the final database check found zero remaining.

This fix prevents future direct tampering. It does not identify or restore messages
that may have been modified before the lockdown, and does not establish that every
historical answer is correct. Existing chat contents were preserved.
