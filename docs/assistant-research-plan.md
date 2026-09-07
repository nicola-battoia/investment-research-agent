# Reliable research turns — investigation and implementation plan

Investigated on **2026-09-07**. This is a proposal, not a description of deployed
behavior. Production code, settings, permissions and the golden dataset were not
changed by this investigation. Seven new real-service QA attempts were recorded.

The assistant needs a budget-aware research controller, better evidence selection,
and a protected answer-generation phase. Increasing capacity helps some questions,
but does not solve the broad comparisons. A useful partial answer must be an
explicit, saved outcome with a way to continue, rather than a failed turn.

Evidence: [case-by-case measurements and experiments](../backend/evaluation/results/research-budget-analysis-2026-09-07.md),
[machine-readable analysis](../backend/evaluation/results/research-budget-analysis-2026-09-07.json),
and [QA checklist](qa-suite-todo.md).

## What actually fails

The September 5 baseline has **eight cumulative-input failures and three tool-call
failures**. The other four cases produced three supported answers and one unhelpful
fixed-sentence refusal. These were fresh conversations, so old chat history did
not cause the failures.

The 75,000-token setting counts input across all assistant requests. It is not a
75,000-token document allowance. Searching adds previews and metadata to the
conversation; the next request includes those results, and later requests include
them again. DR-01 consumed 65,312 provider-reported input tokens across seven
requests; its largest individual request was only 15,548 tokens. The local estimate
for another request brought the projected total to 80,850 and stopped it.

The 50,000-token single-request cap, 10,000 cumulative output cap, and 180-second
deadline were **not the terminal failures in that baseline**. Failed turns lasted
roughly 21–38 seconds. Raising their deadlines or output limits alone would not
have fixed these failures. Request limits can become the next obstruction after
another limit is raised; DR-04 had already used all ten model requests.

## Causes and the changes they justify

### 1. Search consumes the budget before evidence is read

Six failed cases used all five searches before their first successful read:
DR-01, DR-02, DR-03, DR-06, DR-10 and DR-14. DR-01 spent 49,764 input tokens before
that read and received 17 repeated chunk occurrences across 56 search results,
including adjacent context. Registering a source once does not remove repeated
previews from the model's conversation.

Broad top-ten retrieval does not guarantee coverage across five companies and two
years. DR-01's first search returned no Apple or Microsoft passages. Follow-up
searches then concentrated on Apple rather than systematically filling all ten
company/year slots. Simply permitting more searches let the new DR-01 run perform
eight searches, read one irrelevant chunk, and fail at 150,000 cumulative input.

**Change:** build a small task checklist from the user's question: companies,
fiscal years, metrics, units and caveats. Track each slot as missing, found, read or
verified. Search missing slots, read promising results immediately, and stop
repeating queries that add no useful evidence. This runtime checklist must be
derived from the question and corpus, never from private QA gold answers.

Use scoped retrieval with coverage across company/year slots, deduplication and
query-relevant previews. Keep full metadata in the server evidence registry;
return compact handles, company/year, useful labels and text to the model. Preserve
table headers, units, dates, signs and footnotes when selecting rows. Do not replace
source evidence with an unverified model summary. Full passages remain available
for citation validation and the source panel.

### 2. Company filters silently produce empty searches

Four baseline searches in DR-04, DR-06 and DR-11 used short company names that do
not match database names. The SQL predicate compares names exactly after case
normalization: `Microsoft` does not match `Microsoft Corporation`. A September 7
read-only database check returned zero filings for the former and five for `MSFT`.
The existing year filter correctly uses report/fiscal year; that is not this bug.

**Change:** resolve names and aliases to canonical company identities/tickers
before retrieval, using the corpus catalog and explicit aliases. Report an unknown
or ambiguous company as a scope issue instead of pretending the corpus has no
evidence. Never drop a failed filter and silently search unrelated companies.

### 3. Eight tools cannot support the required breadth

DR-01/02/03/14 have evidence in ten filings. Even an unrealistically perfect single
search plus one read per filing requires at least eleven calls with the current
tools. Actual questions need additional passages and searches. DR-05 exhausted its
budget after three searches and five reads despite already locating most of the
required evidence.

**Change:** add a bounded batch-read tool and controlled retrieval across missing
scopes. Limit both the number of returned chunks and their total token size.
Count underlying searches, embedding/keyword requests and read chunks as well as
model-visible tool calls; batching must not disguise unbounded work. Keep bounded
concurrency and a shared provider allowance.

Three baseline failed reads requested `S172`, `S145` and `S77` when those source
handles did not exist. Those numbers did match chunk indexes in the results,
suggesting the model confused the two identifiers. Remove the internal numeric
chunk index from the model-facing view and explain the opaque evidence handle.
Reject invalid handles; do not guess a replacement, since indexes repeat across
filings.

The largest actually read chunk among the baseline failures was only **897 stored
tokens**. Large atomic tables are a possible future pressure, but they are not
the measured primary cause here. Prioritize repeated previews and search behavior
before redesigning ingestion or re-chunking the corpus.

### 4. There is no protected finishing phase

[`DocumentAssistant.run`](../backend/app/assistant/agent.py) makes one bounded agent
run. A quota exception escapes before it returns a validated answer.
[`streaming.py`](../backend/app/chat/streaming.py) maps that exception to an error;
the orchestrator therefore saves no answer or research checkpoint. Retrying starts
the research again. The current heartbeat says that work is happening, but carries
no useful research progress.

**Change:** separate research from synthesis under one server-owned budget. Stop
research before a hard limit, disable retrieval tools for synthesis, and build a
bounded evidence packet. Reserve enough requests, input/output tokens and time for
an answer and one grounding correction. The controller enforces this; a prompt
such as “stop when nearly out of tokens” is not sufficient.

Before starting another operation, require:

```text
spent + bounded next-operation allowance + synthesis/correction reserve <= hard cap
now + bounded next-operation time + finishing reserve < turn deadline
```

Apply these rules to requests, tokens, underlying retrieval operations and time.
Cap the next tool result before running it, not after a huge result arrives.
Account for the correction request including the rejected draft. Keep one aggregate
ledger across research, synthesis and repairs; starting a second agent run must
not reset the budget. Distinguish estimated preflight usage from actual provider
usage and measure estimation error.

If research makes no progress for two targeted attempts, change strategy or finish
with an explicit limitation. Do not consume every available search by default.
If the full request is answered, finish immediately.

### 5. The response contract prevents useful handoffs

The policy mentions asking for clarification and writing calculation code, but
there is no calculation tool. There is also no explicit research clarification or
partial status. A conversational answer is rejected after any filing search, while
`insufficient_evidence` must be exactly one sentence with no citations. Those rules
conflict with the requested behavior, especially the explained abstention in DR-15.

**Change:** extend the output contract and validators with explicit outcomes:

| Outcome | Required behavior |
| --- | --- |
| Complete | Answer the requested scope with supported claims and citations. |
| Partial | State supported findings, exactly what is missing, and the next useful step. Never present an unfinished comparison as a complete ranking. |
| Needs clarification | Ask one focused question that materially changes the research. Any factual background still needs citations. |
| Insufficient evidence | Explain what the inspected evidence supports and why it cannot establish the requested conclusion; cite that evidence. Distinguish “not yet inspected” from “not disclosed.” |

Keep advice refusal and scope routing. Do not use clarification to make the user
repeat a clear question or arbitrarily choose one company from an explicitly
requested five-company comparison. Continue clear, feasible work automatically
inside the turn's budget. Ask for direction when the scope is ambiguous; offer a
continuation when the remaining work needs another turn.

For DR-15, the correct result is an explanation of why disclosed AI spending and
revenue do not establish a comparable company-level AI ROI ranking, with useful
cited alternatives. More research must not pressure the assistant into inventing
that ranking.

Add a small deterministic arithmetic capability using sourced inputs, units,
periods and an allowlisted set of operations. Return formulas and results tied to
evidence. Do not give the assistant unrestricted code execution to calculate ratios.

### 6. Follow-up turns discard the research state

[`history.py`](../backend/app/assistant/history.py) carries recent text pairs and
removes old source markers. Evidence and tool state intentionally start fresh.
Consequently, appending “continue” alone cannot reliably resume the research.

**Change:** persist a compact backend-owned checkpoint: task/scope, missing and
verified findings, source UUIDs and text hashes, exact supporting spans, calculation
inputs/results, corpus version, parent turn, usage and checkpoint version. Store
observable work products, not private model reasoning or an unchecked transcript.

Bind it to the authenticated owner and thread. The client sends only its opaque ID
and the user's new text. Recheck ownership, current thread position and source
hashes; rehydrate evidence and issue fresh citation handles. Changed sources require
revalidation; changed user scope requires revising the checklist. Preserve the
[September 6 server-only write protection](security-fix-2026-09-06.md).

Save a partial answer and its checkpoint atomically. Handle duplicate submissions,
concurrent continuations, deletion, expiry and Stop/disconnect around commit.
Enforce a total research-session allowance across continuations as well as each
turn, so repeated “continue” does not become an unlimited loop. Initially test a
maximum of two research turns and 300,000 cumulative assistant input tokens per
session. Further work needs an explicitly renewed request. Expired work should
offer a fresh, bounded research request.

Stream public progress events such as “Checked 2025 revenue for three of five
companies” or “Preparing an answer; two disclosures remain unverified.” The browser
should show progress, then a persisted answer with Continue and a free-text way to
change direction. Do not stream unvalidated factual prose as a final answer.

For a provider outage, exhausted shared quota or failed synthesis, fall back to a
server-generated work-status message and a saved checkpoint, without invented
financial claims. A database outage cannot guarantee a saved continuation; report
that separately. This is distinct from claiming every possible failure can produce
a researched answer.

## Candidate budgets to validate

These are starting values for experiments **after the controller/context changes**,
not a production recommendation established by the small sample.

| Budget | Recorded current profile | Candidate |
| --- | ---: | --- |
| Model requests | 10 | 18 total; keep 2 available for synthesis/correction |
| Model-visible tool calls | 8 | 16 hard cap; normally finish research by 12 |
| Search calls | 5 | 8 batch calls, with at most 20 underlying scoped searches total |
| Read chunks | One per read call | At most 4 per batch and 40 per turn; enforce token bounds too |
| Cumulative assistant input | 75,000 | 150,000 hard cap; target research finish by 100,000 and reserve dynamically |
| Individual request input | 50,000 hard cap | Keep hard cap; target packed synthesis input at or below 12,000 |
| Individual tool result | Count bounds only | Start with 3,000 tokens for search previews; 4,000 for read batches |
| Output | 3,000/request; 10,000 total | Test 4,000/request and 12,000 total, reserving two finishing outputs |
| Citations | 20 | 32, still requiring exact provenance and a bounded answer |
| Turn time | 180 seconds | Keep 180; target research stop by 120 and reserve at least 30 for finishing |

The two-request reserve takes precedence over nominal soft targets: a larger
estimated final packet or correction must stop research sooner. Time reservations
also need measured latency margins. Clamp tool timeouts and SDK retries to the
remaining research deadline; the current 120-second tool allowance must not eat
the finishing reserve. Start sequentially; concurrency is a separate experiment.

DR-14 has 26 distinct labelled evidence passages. With the existing 20-citation
cap it cannot achieve full labelled citation coverage in one response, even if
all retrieval succeeds. This justifies testing a modest citation increase; it
does not mean every valid answer necessarily needs exactly those 26 passages.

A live control run also hit a provider 429 reporting a 100,000-token rate allowance
and a roughly 65-second reset. Local per-turn limits do not increase that shared
capacity. Add admission control and bounded backoff based on provider headers;
include keyword generation and QA judging in operational accounting. A local
single-process semaphore is insufficient for several backend replicas. Select a
shared quota mechanism only after confirming deployment topology. Show a wait or
resumable status if the delay exceeds the finishing deadline.

## Build order and QA gates

1. **Characterize and preserve the baseline.** Add per-request/context-size,
   coverage, retry and quota diagnostics. Keep the original 15 questions and all
   failures. The analysis and small capacity experiment are complete; the new
   runtime instrumentation remains to be built.
2. **Make stopping useful.** Implement the controller, reserves, output statuses,
   grounded partial synthesis and progress events. Update backend schemas,
   validators, stored message metadata and frontend rendering together. Test a
   forced soft stop with some evidence, no evidence and invalid citations.
3. **Remove wasted work.** Fix company resolution and handle confusion; add
   coverage-guided retrieval, bounded batch reads and evidence packing. Add sourced
   arithmetic. Compare each change against the same dataset, not just a combined
   change that hides which part helped.
4. **Add secure continuation.** Migrate checkpoint storage and the atomic save
   boundary. Test cross-user access/forgery, stale sources, repeated continuation,
   scope correction, reload, Stop, disconnect, concurrent sends and chat deletion.
5. **Tune the proposed profile.** Run all 15 cases sequentially first, with at least
   three repetitions per case. Track complete/partial/clarification separately,
   evidence recall, numeric correctness, caveat coverage, grounding repairs,
   actual usage, latency and external quota failures. Then test realistic shared
   load and browser flows. Change provider capacity only with measured demand.

Release requires correct, supported answers for the 14 answerable cases and an
explained, grounded abstention for DR-15 under normal conditions. A partial response
does not count as a passing complete answer. Test partial/continuation behavior
separately under forced limits, then verify that the combined final answer meets
the original question. If an intentionally multi-turn benchmark is adopted, version
it explicitly and retain the single-turn score. Never remove hard cases to raise
the success rate.

The current evaluator also needs calibration: the new DR-05 answer received 10/10
while omitting two listed caveats, and DR-11 cited valid alternative passages that
the exact evidence labels did not include. Review missing alternatives as new
dataset versions and enforce mandatory rubric findings. Do not use either a high
judge score or exact chunk recall alone as the release gate.

The next implementation should therefore start with **protected synthesis and
company/identifier resolution**, followed by coverage and compact evidence, then
secure continuation. Raising the four experimental budget settings alone should
not be shipped as the solution.
