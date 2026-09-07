# Project status and open decisions

Reviewed against the local working tree on **2026-09-05**. This replaces the
original build-phase checklist, which mixed completed implementation with
unverified operational tasks. The [repository audit](repository-audit.md)
contains evidence, severity, and proposed decisions; no application fixes were
made as part of that documentation review. The authorized security follow-up
was implemented and deployed on **2026-09-06**.

## Implemented in the repository

- FastAPI API, validated configuration, structured logs, health endpoint, and
  request dependencies.
- Supabase email/password sign-in, protected frontend routes, bearer-token
  verification, and user-scoped database access.
- Alembic schema through `20260906_0011`, RLS, ordered chat persistence,
  idempotent turn completion, and stored citations.
- SEC HTML parsing, local chunk/embedding checkpoints, upload and verification
  tools, and hybrid retrieval.
- A bounded PydanticAI assistant with three retrieval tools, structured outcomes,
  excerpt validation, refusal behavior, and buffered SSE delivery.
- React chat UI, thread management, answer status and citation display, and
  Docker/Caddy configuration for two Railway services.
- Offline backend tests, opt-in live tests, retrieval inspection/evaluation
  utilities, and a versioned fifteen-case assistant QA suite with private database history.

The changes reviewed by the initial audit add optional Azure Monitor tracing, a production
search-tool inspector, related configuration/dependencies, and tests. Those
features exist locally; their deployment has not been established by this audit.

## Recorded operation versus current verification

The [deployment history](guides/railway-deployment-plan.md) records a first
release and an August 28–29 Foundry reliability rollout. The local corpus contains
27 filings and 6,373 chunks. Neither those records nor local tests establish the
current contents of Supabase or configuration of Railway/Azure.

The September 5 audit passed 278 offline backend tests, backend lint, frontend
lint, and the production frontend build. One existing Python format mismatch and
a frontend bundle-size warning remain. Live authenticated flows and cloud
configuration were not rechecked.

The subsequent [QA investigation](qa-findings-2026-09-05.md) verified the live corpus,
created private QA tables, exercised real authenticated requests and reproduced
permission/budget failures. It passed 299 offline tests. Browser/cloud deployment
configuration were outside that investigation. The [September 6 security
follow-up](security-fix-2026-09-06.md) subsequently deployed server-only saves,
passed 302 offline tests, 37 SQL checks, 34 public API checks and 16 real assistant
API checks, and verified sign-in, citations, reload and tampering rejection in
the deployed browser. Other audit findings remain open.

## Decisions to make before the next release

- [x] Repair the stale retrieval labels and rerun the ten-case retrieval gate.
- [ ] Resolve the budget and explained-abstention failures in the research benchmark.
- [x] Enforce server-only assistant/message/citation persistence; see the
  [security fix and live verification](security-fix-2026-09-06.md).
- [ ] Decide how exception content should be handled in exported traces before
  enabling production tracing.
- [ ] Choose one intended token-budget profile and align defaults, example env,
  and operator configuration.
- [ ] Define embedding-model identity/version checks and the verification needed
  before accepting an upload as complete.
- [ ] Review history pagination and Stop/retry persistence behavior.
- [ ] Confirm the supported corpus: the five-company annual-report pilot versus
  the downloader's additional issuer/forms and rolling-year behavior.
- [ ] Decide whether private-pilot access remains manually provisioned or needs
  an application-enforced allowlist.
- [ ] Review grounding/product wording, the prompt's calculation instruction, and
  the maintenance candidates in the audit.

## Operational checks still requiring evidence

- [x] Confirm the live migration head and database corpus in the QA investigation.
- [ ] Confirm current deployed commits, service variables and embedding deployment identity.
- [x] Verify tested ownership isolation with two real user accounts.
- [ ] Verify Supabase public sign-up settings and approved-user provisioning.
- [ ] Run the [frontend manual checklist](../frontend/README.md#verify-changes)
  against the intended environment, including citation, refresh, retry, and
  cancellation behavior.
- [ ] Recheck Railway Watch Paths and the intended production source branch;
  prior release notes leave branch promotion and isolated rebuild checks open.
- [x] Run corrected retrieval and a fifteen-case API/SSE research baseline.
- [ ] Resolve failures and obtain human/browser acceptance before claiming release quality.
- [ ] Review observed latency, provider quota, cost, and trace content with the
  actual production profile.

## Pilot outcomes

- [ ] Give the five analysts a short usage guide with corpus and citation limits.
- [ ] Collect failed questions, misleading answers/citations, usability issues,
  response times, and time saved.
- [ ] Compare results with the client brief's target of three hours saved per
  analyst per week.
- [ ] Decide on broader S&P 500 coverage only after pilot quality, capacity, and
  operating-cost evidence is available.

The [client brief](client-brief.md) remains the business requirement; these items
do not silently change its scope.
