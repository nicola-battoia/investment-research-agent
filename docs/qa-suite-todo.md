# Assistant QA suite — implementation checklist

This is the working plan for the QA suite requested on 2026-09-05. Checkboxes
describe work actually completed, not intended behavior. The [permission fix](security-fix-2026-09-06.md) implements the first security
follow-up. Production limit changes remain separate work.
See the [measured findings](qa-findings-2026-09-05.md) and
[run instructions](../backend/evaluation/README.md). A checked test task means
implemented/executed, not that the desired security or quality assertion passed.
The [September 7 research plan](assistant-research-plan.md) adds measured limit
causes, a small capacity comparison, and the proposed answer/continuation design.

## Scope and design

- [x] Review existing tests and distinguish offline, real-service, and browser coverage.
- [x] Confirm the live corpus: 27 documents, 6,373 chunks, no populated page numbers.
- [x] Separate the ten-question atomic retrieval dataset from the fifteen-question
  deep-research benchmark. Only the former had obsolete numeric chunk references.
- [x] Create a private `qa` schema through SQLAlchemy models and Alembic.
- [x] Store immutable dataset versions, cases with gold answers/evidence, run
  configuration, and individual results. Preserve failed runs as well as successes.
- [x] Keep QA tables unavailable to browser roles; use the operator database connection.
- [x] Record corpus fingerprint, source revision, model/deployment, prompt hash,
  effective settings, timestamps, and evaluator version for reproducibility. New
  runs also hash application/harness code; early runs retain the revision and prompt hash.

## Layer 1 — permissions and integrity (first priority)

- [x] Exercise actual PostgreSQL roles/RLS with two temporary identities and rollback.
- [x] Deny anonymous access to chats and QA tables.
- [x] Verify both directions of user isolation for threads, messages, and citations.
- [x] Verify authenticated users can read the shared filing corpus but cannot edit it.
- [x] Try inserting, modifying, and deleting an assistant message in one's own chat.
- [x] Try forging a citation and calling `complete_chat_turn` directly.
- [x] Require rejected writes to leave the database unchanged; do not treat an empty
  response alone as proof of denial.
- [x] Report current integrity failures without changing grants or hiding failures
  with `xfail`. The desired policy is that only validated backend turns create or
  modify assistant answers/citations; legitimate thread deletion remains allowed.
- [x] Add a separate real-JWT/PostgREST/API test against the intended QA environment.

- [x] Move validated turn saves to a server-only RPC with a verified owner ID.
- [x] Remove the old RPC signature and direct browser message/citation writes.
- [x] Extend SQL and JWT tests to role changes, display parts, upserts, saved user
  messages, server owner mismatch, and whole-chat deletion/cascade.
- [x] Add a real-model API smoke command for cited replies, replay, follow-up,
  reload, forged input, isolation, renaming and deletion on a local or deployed API.

## Layer 2 — corpus and required evidence

- [x] Export and inspect current database chunks; compare identities/checksums with
  local source files before reusing local evidence.
- [x] Repair the fourteen references in the ten-case retrieval dataset.
- [x] Map all fifteen research questions to current filing evidence.
- [x] Store accession, chunk UUID/index, text checksum, section, and exact supporting
  excerpts. A bare chunk number is never a portable evidence identifier.
- [x] Group equivalent passages as alternatives: retrieving one valid alternative
  satisfies that requirement. Keep independent required facts in separate groups.
- [x] Verify gold facts, calculations, units, fiscal years, and caveats against the
  sources. Mark any remaining unreviewed criteria explicitly.
- [x] Update the Markdown benchmark with verified chunk references; explain that old
  printed-page locators were manual and the parser provides no page metadata.
- [x] Fail dataset preflight on missing/changed references before spending model calls.
- [x] Use a new dataset version when evidence, questions, or scoring rules change.

## Layer 3 — assistant answer quality

- [x] Run the fifteen benchmark questions with explicit company scope through the application's
  authenticated HTTP/SSE path with real retrieval and real generation.
- [x] Parse SSE events and verify final text/citations against the reloaded thread.
- [x] Store retrieved, explicitly read, and cited evidence separately.
- [x] Calculate evidence-group recall separately for retrieval, reading, and citation.
- [x] Report completion rate separately from quality among completed answers;
  failures stay in the run denominator. Latest compatible case results are selected
  independently of their score; initial scope defects remain in run history.
- [x] Exercise the production citation provenance/excerpt validator on completed turns.
- [ ] Add deterministic extraction/checking of answer calculations and units beyond
  the advisory grader, and independently review all gold calculations/caveats.
- [x] Add an optional rubric-based model assessment with reasons and critical-failure
  flags. Treat this as advisory; it is not an independent proof of correctness.
- [ ] Add small factual, multi-turn, ambiguous, unsupported, advice/refusal, language,
  and document-injection cases alongside the harder benchmark.
- [ ] Review false passes/failures with a person; avoid exact-string grading of prose.

## Layer 4 — limits, failures, and chat lifecycle (urgent)

- [x] Run a baseline using the effective current settings; do not raise limits first.
- [x] Capture partial progress on failure: searches, successful/attempted tools,
  model requests, actual/estimated tokens, deadline, retries, last stage, and error.
- [x] Record the user-visible failure separately from internal diagnostics.
- [x] Calculate a conservative minimum read/search-call requirement from evidence.
- [x] Exercise the key budget boundaries with a controlled model:
  tool calls, model requests, per-request input, cumulative input/output, tool
  timeout, turn deadline, search/surrounding caps, and grounding retries. Existing
  deadline/search/grounding tests are reused; new tests exercise real budget boundaries.
- [x] Distinguish local limits, provider 429s, invalid output, grounding rejection,
  database errors, and transport failures.
- [ ] Test duplicate submission, conflicting concurrent turns, failed save, retry,
  disconnect, Stop before/after commit, and history beyond the database row cap.
- [x] Compare a candidate profile in a separate process so import-time settings agree.
  The September 7 three-case comparison and serial retry are diagnostic only;
  broad questions still fail and provider contention affected one attempt.
- [x] Propose improvements based on observed bottlenecks: batch evidence reads,
  smaller retained context, staged research and reserved answer budget.
- [ ] Measure candidate-profile cost, latency and quality before selecting changes.
- [ ] Add provider output-truncation and keyword-generation failure cases.
- [ ] Re-run the same dataset/version/profile after each fix; keep the baseline.
- [ ] Implement and test protected synthesis before hard limits, including a
  grounding correction reserve and a shared budget across research phases.
- [ ] Fix company-alias resolution and source-handle confusion; test coverage-guided
  searches, bounded batch reads, repeated-result suppression and source packing.
- [ ] Add grounded partial/clarification/insufficient-evidence outcomes and meaningful
  progress events; partial answers must not count as complete benchmark passes.
- [ ] Persist secure research checkpoints and test continuation ownership, source
  changes, concurrent/repeated requests and limits across the whole research session.
- [ ] Calibrate mandatory caveat grading and review equivalent DR-11 evidence in a
  new dataset version; retain the original results and single-turn denominator.

## Layer 5 — browser experience

- [ ] Add a small browser suite for sign-in, ask, open citation, highlighted table,
  refresh, retry, Stop, sign-out, and second-user isolation.
- [ ] Document the explicit change from the current manual-only frontend policy
  when introducing the requested browser automation.
- [x] Keep API/SSE coverage labeled as API coverage until real browser checks run.

## Layer 6 — privacy and operation

- [ ] Test real in-memory telemetry spans during failures, not only mocked spans.
- [ ] With content capture disabled, assert test-secret/content markers are absent
  from span attributes, exception events, and application logs.
- [ ] Check embedding/keyword/assistant usage separately; never call token overlap
  or missing cost metadata an accuracy or total-spend measurement.
- [x] Keep golden answers and QA diagnostics inaccessible to normal users and out
  of the assistant's retrieval corpus.
- [x] Add bounded, explicit live-run commands and a readable Markdown/JSON report.
- [ ] Add CI stages for offline tests; run paid/service tests only with explicit
  credentials, a bounded case selection, and a known target environment.

## Acceptance and rollout

Security/integrity checks require zero unexpected successful operations. Dataset
validation requires all mapped evidence to exist and match its snapshot. Research
quality retains the benchmark's critical-failure rules; unsupported cases and
execution failures cannot disappear from the score. A run with skipped or
unreviewed checks must report them clearly.

The first implementation should expose defects. It must not change production
budgets, weaken the questions, rewrite expected answers to fit model output, or
grant extra browser permissions to make the suite pass.
