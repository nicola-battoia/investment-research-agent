# Repository audit — 2026-09-05

Follow-up: the [September 5 QA investigation](qa-findings-2026-09-05.md) repairs the
retrieval labels and records live permission/budget evidence. This audit retains
its original findings and verification scope. The
[September 6 security fix](security-fix-2026-09-06.md) addresses F02.

At the time of this audit, documentation was updated while application fixes,
migrations, configuration changes and deletions were deferred. Later authorized
work is linked above and beside the relevant findings. The most consequential findings concern evaluation validity, assistant
message provenance, trace content, and corpus/version verification.

## Scope

Reviewed the repository structure, all tracked documentation and local recovery
notes, application and ingestion paths, tests, migrations, dependency manifests and
locks, deployment files, and the initial uncommitted changes. The starting revision
was `7799483`; there were 222 tracked files. Findings describe that revision plus
the local changes, not only committed code.

The local corpus review covered all 27 filings through parser dry-run validation,
source metadata/checksums, chunk and embedding checkpoint validation, and evaluation
reference matching. It did not independently reread and fact-check every financial
assertion in the original SEC filings or the benchmark's gold answers. Private
invoice-review payloads were checked for integrity, not reviewed as application data.

No database mutation, live model call, deployment, resource restoration, or
authenticated production-browser test was performed. Historical cloud observations
are labeled as such. Application source, lockfiles, env examples, datasets, and
backup payloads were preserved.

## Initial uncommitted work

| Area | Change reviewed |
| --- | --- |
| Azure tracing | New `app/telemetry.py`; optional exporter configuration, assistant instrumentation/parent span, and direct keyword/embedding spans |
| Runtime configuration and logs | New Azure Monitor settings/validation, startup wiring, and bounded logging fields |
| Search inspection | New `evaluation/inspect_search_tool.py`; the playground now executes one real user-scoped tool call with only the planner simulated |
| Tests | New tracing and inspection tests; existing assistant/configuration assertions updated |
| Dependencies | Azure Monitor package plus explicit OpenTelemetry API/SDK dependencies; lock adds 24 packages and changes nine existing OTel-related versions |
| Recovery material | Untracked image/storage backup directories for the separate invoice-review app |
| Documentation | Existing backend/Azure-guide edits were incorporated; detailed inspector guidance now lives in the evaluation README |

The lock moves the OTel API/SDK/exporter family from 1.44 to 1.43 and related
instrumentation packages from 0.65b0 to 0.64b0 to accommodate the new dependency
set. This is a real runtime dependency change, even though the feature is optional.
The offline suite passes; that does not verify Azure exporter delivery or establish
a package vulnerability assessment.

## Finding index

Priority indicates what to decide or verify first, not permission to change it.

| ID | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| F01 | High | Retrieval labels no longer match the corpus | Confirmed against every local checkpoint |
| F02 | High for provenance | Users could write assistant records directly | [Fixed and verified September 6](security-fix-2026-09-06.md) |
| F03 | High before trace export | Exceptions can enter traces with content capture off | Reproduced offline |
| F04 | Medium | Python defaults and operator token profiles differ | Confirmed configuration comparison |
| F05 | High for benchmark acceptance | Page/source requirements exceed current capabilities | Confirmed corpus and tool limits |
| F06 | High for corpus migration | Upload skip/verification does not prove model identity | Confirmed code path |
| F07 | Medium | Downloader destroys the previous snapshot before success | Confirmed default/control flow |
| F08 | Medium | Pilot scope/access requirements are only partly implemented | Code/brief mismatch; hosted Auth setting unverified |
| F09 | Medium | Grounding/product wording exceeds deterministic checks | Confirmed validation boundary |
| F10 | Medium | Unpaginated reads can truncate history and break next positions | Static analysis; threshold depends on hosted row cap |
| F11 | Medium | Stop can disagree with an already committed turn | Static race analysis; browser reproduction pending |
| F12 | Medium | Usage reporting omits some workload details | Embedding-span gap reproduced offline |
| F13 | Medium | Prompt asks for unsupported calculation/clarification behavior | Confirmed prompt/tool/output mismatch |
| F14 | Medium | Default embedding batches exceed the recorded quota profile | Offline batch calculation; current quota unverified |
| F15 | Low–medium | Injected settings do not control all runtime limits | Confirmed configuration ownership split |

## F01 Retrieval evaluation labels do not match the current corpus

**Evidence.** [`retrieval_cases.json`](../backend/evaluation/retrieval_cases.json)
has ten cases with fourteen expected passage references. All fourteen chunk
indexes exceed the current chunk count for their filing:

| Filing / accession | Expected indexes | Current count / valid indexes |
| --- | --- | --- |
| AAPL FY2024 / `0000320193-24-000123` | 340, 332 | 140 / 0–139 |
| AMZN FY2024 / `0001018724-25-000004` | 371, 406 | 174 / 0–173 |
| NVDA FY2024 / `0001045810-24-000029` | 528, 535, 286, 289 | 202 / 0–201 |
| MSFT FY2024 / `0000950170-24-087843` | 599, 524, 397 | 187 / 0–186 |
| GOOGL FY2024 / `0001652044-25-000014` | 581, 575, 594 | 206 / 0–205 |

The [accepted baseline](../backend/evaluation/results/retrieval-baseline.json)
was generated on 2026-08-19, before the SEC parser/chunker replacement.

**Impact.** A database containing the current checkpoints cannot satisfy these
labels. The old `accepted: true` does not establish current retrieval quality.

**Decision.** Remap evidence and relevance judgments, bind the dataset to a corpus
version, then run a new evaluation. Preserve the earlier results as history.

## F02 Assistant-message provenance is not enforced at the database boundary

**Follow-up:** addressed by the [September 6 permission fix](security-fix-2026-09-06.md).
The original evidence below is retained as the pre-fix record.


**Evidence.** [Migration 0002](../backend/app/alembic/versions/20260817_0002_restrict_authenticated_grants.py)
grants authenticated users SELECT/INSERT/UPDATE/DELETE on their chat tables.
[Migration 0007](../backend/app/alembic/versions/20260821_0007_complete_chat_turn.py)
also exposes `complete_chat_turn` to `authenticated`. It checks ownership and
positions, then stores supplied assistant content, metadata, usage, and citations.
It does not run the Python grounding validator.

**Impact.** A signed-in user can call Supabase directly to fabricate or alter
assistant records in their own threads, bypassing the API's validation. This is
an ownership-scoped provenance issue; these findings do **not** demonstrate access
to another user's chats.

**Decision.** Decide whether saved assistant messages must be trustworthy system
outputs or may be user-editable records. If provenance is required, define an
enforced server write boundary and corresponding grants/RPC authorization.

## F03 Tracing can record exception content with content capture disabled

**Evidence.** [`telemetry.py`](../backend/app/telemetry.py)'s
`assistant_turn_span` and `model_call_span` use
`start_as_current_span` with default exception recording. With an in-memory
OpenTelemetry exporter and content capture false, raising
`ValueError("AUDIT_CONTENT_MARKER")` inside a model span emitted that marker as
`exception.message`, with a stack trace.

**Impact.** Disabling explicit model input/output capture does not redact exception
events. Provider/parser exception text may contain content. Production application
log filtering is a different pipeline and does not sanitize these spans. This
reproduction used a harmless marker; it is not evidence of a real credential leak.

**Decision.** Choose the permitted exception fields and enforce that contract on
exported spans. Verify both direct-call and instrumented assistant failures before
enabling production tracing.

## F04 Token budgets differ between defaults and operator profiles

**Evidence.** [`config.py`](../backend/app/config.py), the
[example env](../backend/.env.example), and deployment commands disagree:

| Setting | Python default | Example / recorded operator profile |
| --- | ---: | ---: |
| Per-request assistant output | 2,500 | 3,000 |
| Cumulative input | 75,000 | 60,000 |
| Per-request input | 50,000 | 32,000 |
| Cumulative output | 10,000 | 6,000 |

The uncommitted tests now match the Python defaults. Copying the example env still
overrides them. The [configuration reference](configuration.md) makes the
difference explicit; no runtime values were changed.

**Impact.** Environments can behave differently while appearing to follow the
same setup. The older quota arithmetic does not apply unchanged to the defaults,
and per-turn caps do not coordinate concurrent users.

**Decision.** Select the intended profile, align the runtime/example/operator
values, and check the deployed values before assessing quota behavior.

## F05 Benchmark and page-citation requirements exceed current capabilities

**Evidence.** All 6,373 validated chunks have `page_number=None`. The active
[chunker](../backend/ingestion/chunk_documents.py) provides sections and canonical
Markdown offsets. The [client brief](client-brief.md) and
[answer benchmark](../backend/evaluation/benchmarks/filings_deep_research_v1.md)
ask for page-specific citations.

DR-01, DR-02, DR-03, and DR-14 require evidence from ten filings. The turn permits
eight total tool calls, including search. Citation validation requires explicitly
read evidence; each read tool is scoped to one filing. Ten filings therefore
require at least ten reads plus a search, beyond the default budget.

**Impact.** These benchmark requirements cannot be fully met under the current
implementation/profile. There is no automated runner for the fifteen-case
Markdown benchmark.

**Decision.** Choose whether to add trustworthy page mapping and broader research
execution or explicitly change the acceptance contract. Do not mark the current
benchmark passed based on retrieval or unit-test scores.

## F06 Upload completeness does not prove embedding identity

**Evidence.** [`validate_existing_chunk_version`](../backend/ingestion/supabase_chunks.py)
samples one chunk and checks parser, chunker, and source checksum, but not embedding
model/dimensions. [`_document_upload_is_complete`](../backend/ingestion/upload_checkpoints.py)
then checks count and final index. The
[verification command](../backend/ingestion/verify_ingestion.py) checks source and
chunk metadata/counts, but not stored embedding identity, vector values, or text
equality.

**Impact.** A same-dimension model change or stale row can be skipped and reported
complete despite differing from valid local vectors. Validating the local
checkpoint does not prove the database contains it. Source-document upserts are
also separate from chunk migration, so replacing canonical Markdown first can
temporarily mismatch old chunks/citations.

**Decision.** Define a corpus/embedding identity and the comparison required before
skipping uploads. Plan source and chunk migration together, including existing
citations. This audit found a verification gap, not proof that hosted vectors are
currently wrong.

## F07 Downloader replacement is destructive and not reproducible by default

**Evidence.** [`data/download.py`](../data/download.py) defaults
`CLEAR_OUTPUT_DIR=True`, removes the download directory before network work,
and writes the new manifest after all downloads finish. Its years come from the
current UTC year, and the SEC contact remains a placeholder.

**Impact.** A failure can leave an incomplete replacement after deleting a working
corpus snapshot. A later-year rerun changes the selected annual-report years and
cannot reproduce the frozen benchmark automatically.

**Decision.** Choose snapshot/replacement behavior, explicit corpus years, and a
configured contact before rerunning downloads. The data README now describes the
actual behavior; the downloader itself is unchanged.

## F08 Corpus scope and pilot access need explicit decisions

**Evidence.** The [brief](client-brief.md) targets a five-company annual-report
pilot and eventual S&P 500 10-K/10-Q coverage for 2020–2025. The local corpus adds
two BSP prospectuses. The downloader recognizes 20-F/S-1 as well, while the active
parser supports only 10-K/F-1/424B4. No active 10-Q pipeline is present.

The browser has no signup screen, but the
[Auth dependency](../backend/app/auth/dependencies.py) accepts valid users from
the configured Supabase project. The user-sync migration has no email allowlist.
Public signup must be disabled in hosted Supabase settings for the documented
manual-provisioning policy; that setting was not checked live.

**Impact.** Corpus eligibility and private-pilot enrollment are not fully expressed
as application-enforced rules. A missing signup button alone does not close the
Supabase signup API.

**Decision.** Confirm supported forms/issuers and whether hosted signup controls
are sufficient or an application allowlist is required. Treat broader 10-Q/S&P
coverage as future work, not completed functionality.

## F09 Grounding validates citations, not every factual inference

**Evidence.** The [validator](../backend/app/grounding/validator.py) verifies status
rules, marker/citation agreement, current-turn evidence reads, and excerpt
matching. It does not determine whether every factual sentence follows from that
excerpt or whether a calculation is correct. A supported answer needs at least
one citation; the prompt carries the per-claim requirement.

The [conversation screen](../frontend/src/components/chat/chat-conversation.tsx)
says every factual answer is checked against its cited passage, and the
[message view](../frontend/src/components/chat/chat-message.tsx) labels sources
“verified.”

**Impact.** The UI can imply a stronger fact-verification guarantee than the code
provides. Accurate source excerpts can accompany unsupported interpretation.

**Decision.** Agree on the meaning of verified, adjust wording if necessary, and
select human/model evaluation coverage for claim support and numerical accuracy.
The architecture now states the deterministic boundary accurately.

## F10 Unpaginated database reads can truncate chat history

**Evidence.** [`list_threads` and `load_thread`](../backend/app/database/chats.py)
do not paginate thread, message, or citation reads. Messages are ordered oldest
first. The [orchestrator](../backend/app/chat/orchestrator.py) derives the next
position from `len(messages)`.

Supabase documents a default maximum of 1,000 returned rows, configurable per
project: [Python select reference](https://supabase.com/docs/reference/python/select).

**Impact.** Above the hosted row cap, older-first loading loses recent messages,
citations can be incomplete, and the next position can disagree with the database,
causing repeated turn conflicts. At the default cap, this affects a thread after
it grows past 500 complete user/assistant pairs. Actual hosted cap was not queried.

**Decision.** Define paginated history/thread APIs and obtain the next message
position independently of a potentially truncated list.

## F11 Stop can hide a turn that has already been saved

**Evidence.** The [frontend abort branch](../frontend/src/components/chat/chat-conversation.tsx)
restores the draft, removes its user message, clears failure state, and returns
without `reconcileCommittedTurn`. Error/disconnect handling does reconcile.
The [backend](../backend/app/chat/orchestrator.py) commits before streaming final
answer text.

**Impact.** Stop in the commit-to-delivery window can leave the browser showing
an unsent draft while the database already contains the turn. Submitting again
creates a new client message ID, so idempotency does not prevent a duplicate.
This is a static race finding; an authenticated browser reproduction remains open.

**Decision.** Define cancellation semantics around persistence and reconcile
aborted requests without blindly discarding a committed result.

## F12 Usage reporting is incomplete across model workloads

**Evidence.** [`telemetry._record_usage`](../backend/app/telemetry.py) maps
`input_tokens`, but embeddings return `prompt_tokens`. An offline response
stub with 123 prompt/total tokens produced `app.usage.total_tokens=123` and no
`gen_ai.usage.input_tokens`.

[Persisted `AssistantUsage`](../backend/app/assistant/outputs.py) comes from the
PydanticAI run. Direct keyword and embedding calls have their own usage and are
not added to that record. The new search inspector correctly distinguishes actual
provider usage from local estimates and simulates no billed assistant request.

**Impact.** A trace dashboard using standard embedding input fields will undercount;
stored assistant-turn usage is not total system spend. Nullable cost estimates
should not be treated as a complete Azure invoice.

**Decision.** Fix the embedding usage mapping and decide whether turn accounting
should aggregate all three workloads or label each scope explicitly.

## F13 Prompt instructions lack matching tools or output paths

**Evidence.** [`policy.py`](../backend/app/assistant/policy.py) tells the assistant
to write code to calculate values, but only search/read retrieval tools are
registered. It also allows stopping after search to request clarification, while
the validator rejects a conversational response after search and requires the
exact fixed sentence for insufficient evidence.

The policy asks for the user's language, yet mandatory refusal sentences are
fixed English strings.

**Impact.** There is no executable calculation facility or clean status for a
citation-free clarification after search. The model can face incompatible output
instructions and consume correction retries or fall back to an unhelpful refusal.
These conflicts do not imply that every affected turn fails.

**Decision.** Define supported calculation, clarification, and language behavior;
then align prompt, tools, schemas, and validation together.

## F14 Embedding batches exceed the recorded deployment quota profile

**Evidence.** [Embedding batching](../backend/ingestion/create_embeddings.py)
defaults to 128 inputs and a 250,000-token batch ceiling. Offline batching of the
validated current corpus produces 68 requests; 59 exceed 10,000 input tokens and
the largest contains 51,195 tokens.

The [August Azure record](guides/azure-foundry-setup.md#recorded-resources) lists
10,000 TPM for the embedding deployment. The batch loop has no quota-aware pacing;
bounded SDK retries are not a shared throughput controller.

**Impact.** Re-embedding under that allocation may throttle even though requests
meet model/API item limits. Current live quota and a fresh paid run were not
checked, so this is an operational mismatch requiring verification.

**Decision.** Confirm the intended embedding capacity and choose token-aware batch
sizes/pacing or a deliberate temporary ingestion allocation.

## F15 Alternate Settings instances only partially control behavior

**Evidence.** [`create_app`](../backend/app/main.py) and
[`DocumentAssistant`](../backend/app/assistant/agent.py) accept a Settings
instance. [Tools](../backend/app/assistant/tools.py),
[history](../backend/app/assistant/history.py), output-field limits, policy text,
and grounding still read module-global settings; some are captured at import time.

**Impact.** An alternate app/assistant configuration can govern model budgets while
search/history/validation limits come from a different instance. This matters for
tests and future embedded/multiple-app use; the ordinary one-process singleton
configuration is internally consistent with its own env.

**Decision.** Keep a documented single configuration model, or propagate settings
consistently if alternate instances are intended to be supported.

## Dead code and cleanup candidates

Nothing listed here was deleted.

| Candidate | Assessment | Decision |
| --- | --- | --- |
| [`backend/test.py`](../backend/test.py) | Only imports Alembic; no assertions, no references found, and not a collected `test_*.py` file | Remove after confirming it has no local operator purpose |
| [React](../frontend/src/assets/react.svg), [Vite](../frontend/src/assets/vite.svg), [hero](../frontend/src/assets/hero.png), [icons](../frontend/public/icons.svg) starter assets | No references found in active frontend files | Remove unused assets if no design work depends on them |
| [Archived ingestion](../backend/ingestion/archive/README.md) | Intentionally inactive, with replaced Docling/direct implementations and experiments | Keep clearly archived or remove after a retention decision; not a runtime dependency |
| [Older branch inspector](../backend/evaluation/inspect_retrieval.py) | Different purpose from the new production-tool inspector; not automatically dead. Its internally created Azure client is never explicitly closed | Retain and repair client ownership if still useful, otherwise retire explicitly |
| [Retrieval runner](../backend/evaluation/run_retrieval.py) and [embedding runner](../backend/ingestion/embed_checkpoints.py) | Azure cleanup occurs on the success path; failures can bypass it | Use reliable cleanup if these tools remain supported |
| [Image backups](../azure-image-backups/README.md) and [storage backups](../azure-storage-backups/README.md) | Separate invoice-review project; about 81 MiB + 8.3 MiB of ignored private recovery data; local hashes match | Move to an intentional private recovery location or retain with clear ownership; do not delete the sole recovery copy |
| [`.npmrc`](../frontend/.npmrc) comment | Suggests `--ignore-workspace-root-check` as a package-release-age override; that flag concerns the workspace root check | Correct the comment in a later config/code cleanup |
| [Frontend bundle](../frontend/package.json) | Current build emits an 801.87 kB JS chunk (235.57 kB gzip) and a size warning | Profile before deciding on splitting or dependency removal |

The current `favicon.svg` is referenced by `index.html`. The `shadcn` package
is referenced by the CSS import `shadcn/tailwind.css`. Neither should be removed
based on the unused-starter-asset finding. Migration history also remains active
even when an old migration description mentions Docling.

## Documentation changes made

- Added a documentation index, configuration reference, dedicated evaluation
  guide, and this report.
- Reworked the repository/backend/frontend READMEs and local setup guides around
  the implemented app, with actual paths, required settings, and useful checks.
- Replaced stale build-phase checkboxes with implementation status, explicit
  decisions, and operational gates.
- Condensed architecture and chat workflow descriptions around current request,
  retrieval, grounding, persistence, and streaming behavior.
- Distinguished runtime defaults from earlier operator profiles; documented
  optional tracing and the production search-tool inspector.
- Consolidated deployment commands in the Railway runbook and marked release
  observations, quotas, and old test counts as historical.
- Corrected ingestion/archive links, clarified verification limits and downloader
  effects, and labeled old benchmark results as incompatible with current chunks.
- Corrected factual paths/check commands in AGENTS files while retaining repository
  policies. Preserved the client brief and benchmark's financial gold values.
- Identified the recovery notes as belonging to a separate application.

## Validation

| Check | Result |
| --- | --- |
| Offline backend suite | **278 passed, 11 integration tests deselected** |
| Ruff lint: app, tests, ingestion, evaluation, playground | **Passed** |
| Ruff format check over the same paths | **One existing mismatch**: `evaluation/inspect_retrieval.py` at the `build_live_retriever` signature; 137 files already formatted |
| Frontend ESLint | **Passed** |
| Frontend production build | **Passed**, including `tsc -b`; bundle-size warning above |
| Offline Alembic SQL | **Passed** through `20260823_0008`; no database connection/mutation |
| SEC parser dry run | **27 documents validated**, 600 sections, 34,310 blocks, 1,907 tables |
| Local chunk and embedding loaders | **27 checkpoints / 6,373 chunks / 6,373 vectors validated**, including identity, checksums, counts, dimensions and local format rules |
| Evaluation reference matching | **14 of 14 expected passages missing** from current checkpoints |
| Printed-page field inventory | **0 of 6,373 populated** |
| Local backup checksums | Image archive and all seven storage checksum entries matched |
| Telemetry reproductions | Confirmed exception-content export and missing embedding input-token attribute with an in-memory exporter |
| Documentation verification | 30 Markdown files / 235 local links checked; no broken links or unclosed code fences; `git diff --check` passed |
| Source preservation | All 204 snapshotted non-document files unchanged |

The backend suite ran with Azure tracing/content capture explicitly disabled,
using the existing environment. No dependencies were updated for this review.
The environment used Python 3.13.7, uv 0.12.0, Node 22.21.0, and pnpm 11.18.0.

Outstanding live checks: deployed revisions/variables, actual Azure quota/exporter
delivery, Supabase migration/corpus/grants/Auth settings, signed-in browser behavior,
two-user isolation, and the corrected live quality evaluation. Local success does
not replace these checks.

## Suggested decision order

1. Agree on the trust boundary and tracing content policy (F02/F03).
2. Repair evaluation labels and choose an achievable acceptance contract (F01/F05/F09/F13).
3. Align budgets, embedding identity, and ingestion quota behavior (F04/F06/F14).
4. Address pagination/cancellation and settle corpus/access scope (F07/F08/F10/F11).
5. Improve usage/configuration consistency and approve cleanup candidates (F12/F15).

This is a decision record for subsequent work. No application fix or deletion is
implied by a finding's priority.
