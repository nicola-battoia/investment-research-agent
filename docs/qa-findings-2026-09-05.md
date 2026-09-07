# Assistant QA findings — 2026-09-05

The September 5 assistant baseline failed most of the deep-research benchmark under the tested
limits. **11 of 15 cases stopped at a budget limit; three produced supported
answers; one returned the fixed insufficient-evidence sentence.** The optional
model grader passed three cases. Those grades are advisory, not human acceptance.

The database integrity concern was confirmed through PostgreSQL role tests
and the public Supabase API: a signed-in user could forge and edit an assistant
answer in their own chat. Cross-user isolation passed. The
[September 6 security fix](security-fix-2026-09-06.md) closes that permission gap.

The September 5 investigation left application permissions, prompts and limits
unchanged and applied the private QA schema. Permission changes were authorized
and implemented on September 6; other decisions remain open in the
[QA checklist](qa-suite-todo.md).

## What was built and run

- Four private tables: `qa.datasets`, `qa.cases`, `qa.runs`, `qa.results`, through
  Alembic migration `20260905_0009`. Browser roles and `service_role` have no schema
  access. QA uses the operator's database connection and is outside retrieval.
- Fifteen questions, reference answers and 144 required evidence groups, with
  exact accession/chunk identities, text hashes, excerpts and equivalent passages.
  Current dataset version: `2026-09-05-sec-sections-v2.2`.
- Database role probes, real-JWT/PostgREST probes, corpus preflight, authenticated
  API/SSE turns, persistence/reload comparison, retrieval/read/citation recall,
  optional answer grading, and failure diagnostics.
- Controlled tests execute the real agent's tool/request/token boundaries and
  tool timeout. Existing tests cover grounding retries, search limits, turn timeout
  and disconnect; a surrounding-call boundary test was added.
- A Markdown report command and commands to seed datasets and rescore recorded
  evidence after labels are improved without paying for new assistant turns.

Verification: **299 offline tests passed**; the live schema privacy/immutability
test passed. The SQL permission audit had **28 passes and seven failures**. The
HTTP audit had **four passes and four failures**, including readback assertions
that confirmed the same two write defects. These are exposed failures, not xfails.

The database contains three retained dataset versions, 45 case rows, four run
records and 36 result rows. These represent fifteen distinct research questions,
not 45 different questions. No runs remain active and no temporary QA accounts
remain. SQL probe fixtures were rolled back; HTTP/assistant accounts and chats
were deleted after testing.

## Q01 — users can forge their own assistant history (high priority)

**Follow-up:** the [September 6 fix](security-fix-2026-09-06.md) closes this
permission gap. The evidence below records the original failing behavior.

The shared filing corpus is read-only to normal users in the tested operations.
The defect concerns **chat messages and citations**, not unrestricted access to
all Supabase data.

Using only a normal user's token and the browser-safe Supabase key, the test:

1. Created a thread owned by that user.
2. Called `complete_chat_turn` through the public REST API with a made-up question
   and assistant answer. Supabase returned HTTP 200, and a read confirmed the
   fabricated assistant record existed.
3. Patched that assistant's text directly. Supabase returned HTTP 200, and a
   second read confirmed the change persisted.

The SQL audit also confirmed that users can insert/delete their assistant rows
and insert/update/delete their citation rows. The current policies check thread
ownership, but do not reserve assistant-authored records for the backend. A user
can bypass the assistant's grounding checks and alter the history later loaded
by the application. Tested reads/writes against the other user's records were
rejected or returned no rows.

**Proposed fix:** restrict assistant-message/citation writes and the completion
function to a backend-controlled boundary. Retain legitimate owned-thread
operations, including deleting a thread. If completion becomes privileged,
recheck ownership, expected position, message identity and citation provenance
inside that boundary. Do not simply grant a more powerful role to the frontend.
Rerun both permission commands and legitimate chat/reload tests after the change.

Evidence: [SQL checks](../backend/evaluation/results/permissions-2026-09-05.json)
and [public API checks](../backend/evaluation/results/permissions-http-2026-09-05.json).

## Q02 — research budgets prevent an answer (high priority)

The baseline used the local application's effective settings with real Supabase
Auth/database and Azure models. It did not query or change deployed Railway
settings. The transport was the production FastAPI/SSE route in an in-process
HTTP client, including normal authentication, tools, grounding and persistence.
Browser rendering and the deployed network path were not exercised.

| Bound | Tested value | Observed outcome |
|---|---:|---|
| Total tool calls | 8 | Three cases stopped here |
| Cumulative assistant input tokens | 75,000 | Eight cases stopped here |
| Input tokens in one request | 50,000 | No live failure attributed to this bound |
| Model requests | 10 | No live failure attributed to this bound |
| Output tokens per request / per turn | 3,000 / 10,000 | No live failure attributed to these bounds |
| Search / surrounding calls | 5 / 2 | Part of the same eight-call tool budget |
| Turn / tool timeout | 180s / 120s | No live timeout in this baseline |

Input usage accumulates across requests. After each tool result, the next model
request sends the retained conversation and evidence again. A large table can
therefore consume input budget repeatedly, even while generated output stays
small. DR-05 had 70,756 reported input tokens and only 387 output tokens; the
preflight estimated 81,968 cumulative input tokens for the next request and
blocked it. The projected number includes a local estimate; it is not additional
provider-billed usage. DR-04 attempted a ninth tool after eight completed tools.

Four cases require ten filings. The current `read_chunk` reads one passage;
`read_surrounding_chunks` reads up to two neighbors in one filing. Even the
conservative lower bound of one read per filing plus one search is eleven calls.
Many cases need several distinct passages per filing, making the real need higher.

**Proposed order of work:**

1. Expose remaining budgets to the research planner and reserve capacity for the
   final answer and grounding correction. A raw limit exception loses all useful
   research from the user's perspective.
2. Design bounded batch reads and a smaller retained evidence representation.
   These address both repeated model requests and cumulative input growth.
3. Define a staged research path for ten-filing comparisons, retaining provenance
   through each stage. Keep calculations reproducible and citation checks intact.
4. Compare explicit candidate profiles in fresh processes using this same dataset.
   Test tool/input budgets together; increasing only one will expose the other.
   Keep per-request context/output limits and deadlines bounded.
5. Measure completion, evidence coverage, factual quality, latency and separately
   reported model/keyword/embedding usage. Choose limits from measurements rather
   than increasing every setting. Do not interpret missing cost data as zero spend.

No candidate profile or application fix has been applied. See the
[case-by-case results](../backend/evaluation/results/qa-baseline-2026-09-05.md).

## Q03 — benchmark inputs and labels needed repair

All fourteen old atomic retrieval references pointed at the previous chunk layout.
They were remapped to the live corpus, and the ten-case retrieval evaluation now
passes its existing acceptance rule. That is evidence about these ten retrieval
questions; it does not establish assistant answer quality.

The live corpus has 27 documents and 6,373 chunks. Every chunk text matched its
local ingestion checkpoint. Re-ingestion was unnecessary. No chunk has populated
page metadata, so the research benchmark now uses verified chunk/section references.
The previous manual printed-page locations were not declared incorrect.

Additional corrections:

- Standalone questions now name the five companies where they previously depended
  on the Markdown introduction. Initial clarification requests were reasonable
  and are excluded from the final research baseline.
- DR-03 now explicitly requests Amazon's capex net of sales and incentives, which
  was already the measure used by its reference answer.
- DR-07's wording distinguishes a combined segment operating loss from a claim
  that AWS transferred cash to every business.
- Verified equivalent MD&A tables now receive credit in DR-07 and DR-08. Their
  successful answers initially had lower label recall despite valid evidence.
- Apple's FY2021 AI-expression absence was checked over its 260,855-character
  canonical Markdown, whose hash matches the database. This proves absence of
  the searched expressions in that text, not arbitrary semantic absence.

Evidence-group recall is the fraction of required facts for which a labelled
passage was retrieved/read/cited. It is **not answer accuracy**, nor is every
unlabelled retrieved passage irrelevant. Extend alternatives through review;
never add a passage solely because the model happened to retrieve it.

## Q04 — explained abstention and grader calibration remain open

DR-15 asks for an unsupported AI-return ranking. The assistant correctly avoids
inventing one, but its fixed `insufficient_evidence` response supplies no explanation
or citations. That branch cannot meet the benchmark's richer abstention rubric.
Decide how an explained, sourced limitation should be represented and validated.

The model grader gives separate findings, citation, caveat and interpretation
scores, and a critical failure overrides the score. It compares meaning and
numbers, not string overlap. It still needs human calibration. For example,
DR-08's answer needs review for the bridge's rounding/order caveat and its loose
“roughly 82%” revenue-growth wording versus the calculated 80.9%.

The initial grader also treated a reasonable company-scope clarification as an
answer defect because it could see gold evidence the assistant had not seen.
The grader instructions were corrected to distinguish that input defect.

## Baseline provenance and remaining coverage

The final evidence-rescore run is `64b5ee7a-8c82-4f84-a48f-13114704f65a`, dataset
`00ae68d1-5a18-405a-9edb-2578fdfc5873`. It pools the ten unchanged questions from
the first full run and the five explicitly scoped reruns. Selection was by case
and latest supplied run, independent of success or score. Questions, gold answers
and runtime settings were checked for compatibility. Only evidence coverage was
recomputed; existing advisory grades were retained with their original run IDs.
All original dataset versions and failures remain in Supabase.

This is one observation per final case, not a statistical reliability estimate.
The shared assistant path is exercised, but the next layers still need browser
Stop/retry/multi-tab checks, broader behavioral and prompt-injection cases,
telemetry privacy checks, repeated trials and human grading calibration. Those
items remain unchecked in the [implementation plan](qa-suite-todo.md).
