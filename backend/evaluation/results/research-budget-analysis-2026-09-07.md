# Research budget investigation — 2026-09-07

The [implementation plan](../../../docs/assistant-research-plan.md) explains the proposed changes. This report records measurements, not a production rollout. The [JSON summary](research-budget-analysis-2026-09-07.json) contains the per-request counts, searches, repeats, retries and effective profiles.

## Method and scope

- Reanalyzed all 15 recorded September 5 cases, preserving the compatible baseline and its source runs.
- Revalidated the dataset against all 6,373 live chunks on September 7; fingerprint, identities, hashes and excerpts still match.
- Executed seven new real assistant API/SSE attempts with Supabase authentication, retrieval, Azure generation, grounding and reload. These use local FastAPI TestClient, not a deployed browser. Temporary accounts/chats were removed; private QA results remain.
- Historical and current local settings and policy hash match. Current code includes the September 6 security fix. New runs record code hashes; historical traces do not prove the current deployed configuration.
- Provider usage in the trace is cumulative. Per-request input is the difference between consecutive responses. Projected stop counts come from the local character-based estimator and are not billed usage.
- Read chunk sizes use ingestion token counts. They exclude search previews, schemas, instructions and repeated conversation context. Large trace/display-table JSON is not the same as model input.

## Original 15-case baseline

Run `64b5ee7a-8c82-4f84-a48f-13114704f65a`; dataset `00ae68d1-5a18-405a-9edb-2578fdfc5873`.

S = search, R = read one chunk, N = read neighbors. Tool sequence counts successful completions; failed attempts remain in the JSON. Evidence percentages measure required-group coverage, not answer accuracy.

| Case | Outcome | Tools | Model responses | Actual input total | Largest request | Projected input at stop | Read evidence |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| DR-01 | input limit | SSSSSRN | 7 | 65,312 | 15,548 | 80,850 | 10% |
| DR-02 | input limit | SSSSSNR | 8 | 73,988 | 14,903 | 89,289 | 5% |
| DR-03 | input limit | SSSSSRNR | 8 | 73,568 | 15,538 | 88,826 | 10% |
| DR-04 | tool limit | SSSRSSRR | 10 | 68,017 | 11,788 | — | 29% |
| DR-05 | input limit | SSSRRRRR | 9 | 70,756 | 10,808 | 81,968 | 62% |
| DR-06 | input limit | SSSSSRRR | 9 | 65,102 | 11,534 | 78,404 | 14% |
| DR-07 | supported | SRRR | 6 | 26,175 | 6,246 | — | 100% |
| DR-08 | supported | SSRRRRRR | 9 | 67,852 | 10,031 | — | 100% |
| DR-09 | tool limit | SSRRRRNR | 9 | 61,615 | 9,477 | — | 10% |
| DR-10 | input limit | SSSSSRRN | 8 | 72,029 | 14,060 | 87,658 | 11% |
| DR-11 | tool limit | SSRSSRRS | 9 | 60,042 | 12,810 | — | 25% |
| DR-12 | input limit | SSRNSRNR | 8 | 68,324 | 13,848 | 81,791 | 50% |
| DR-13 | supported | SRR | 5 | 19,380 | 5,191 | — | 100% |
| DR-14 | input limit | SSSSSRR | 8 | 66,874 | 12,733 | 81,868 | 8% |
| DR-15 | insufficient_evidence | SS | 3 | 10,362 | 5,344 | — | 0% |

Eight failures are cumulative input limits; three are tool-call limits. No baseline terminal failure was an output cap, single-request context cap or deadline. All eleven failed turns had no assistant answer saved. The supported cases were DR-07/08/13; DR-15 returned the fixed insufficient-evidence sentence.

## September 7 capacity experiment

Only these settings changed in the candidate subprocess:

| Setting | Control | Candidate |
| --- | ---: | ---: |
| `assistant_max_total_input_tokens` | 75,000 | 150,000 |
| `assistant_max_tool_calls` | 8 | 16 |
| `assistant_max_model_requests` | 10 | 18 |
| `assistant_max_search_calls` | 5 | 8 |

The model, policy, dataset and all other settings were unchanged. Environment overrides did not edit `.env` or production. There was one attempt per selected case per profile, plus a serial repeat of DR-11. This is diagnostic evidence, not a statistically reliable estimate of improvement.

| Run/profile | Case | Outcome | Seconds | Actual input | Tools | Read / cited evidence | Advisory score |
| --- | --- | --- | ---: | ---: | ---: | --- | ---: |
| Control | DR-01 | `assistant_input_tokens_limit` | 28.58 | 66,894 | 7 | 10% / 0% | — |
| Control | DR-05 | `assistant_input_tokens_limit` | 48.67 | 71,984 | 8 | 62% / 0% | — |
| Control | DR-11 | `assistant_rate_limited` | 51.45 | 12,724 | 4 | 0% / 0% | — |
| Candidate | DR-01 | `assistant_input_tokens_limit` | 60.79 | 138,783 | 9 | 0% / 0% | — |
| Candidate | DR-05 | `supported` | 118.62 | 148,126 | 12 | 75% / 75% | 10 |
| Candidate | DR-11 | `supported` | 52.1 | 60,650 | 8 | 0% / 0% | 10 |
| Control, serial repeat | DR-11 | `assistant_tool_calls_limit` | 37.0 | 68,577 | 8 | 0% / 0% | — |

Run IDs:

- Control: `5a269f92-9081-44fe-a384-46b42298b300`.
- Candidate: `b72ec8b9-d0e8-4699-b2f8-982e80586ef4`.
- Control, serial repeat: `ab7fccc5-b680-4b66-924d-a96ae586bc07`.

The first control and candidate processes overlapped. Control DR-11 received an Azure 429 with a reported 100,000-token allowance and about 65 seconds until reset. Shared contention may have contributed; the provider payload does not isolate the cause or establish a safe concurrency level. After those runs ended, the serial control repeat failed at the original eight-tool cap. All attempts remain reported; the 429 is not relabelled as an application-budget failure.

### Interpretation

- **DR-01:** Extra budget did not solve research planning. The candidate performed eight searches, one successful read and a failed ninth search attempt. It returned 95 previews/context occurrences, including 33 repeats, and had 0% required read coverage. Actual input reached 138,783; the next request was estimated to bring it to 161,911.
- **DR-05:** The candidate produced the core numeric comparison and its citations correctly, but used 148,126 of 150,000 input tokens and about 119 seconds. It had two invalid-source retries. It omitted the Microsoft segment-recast and AI-infrastructure margin caveats; the advisory judge acknowledged both omissions while awarding 10/10. Treat this as a useful but incomplete response requiring rubric review, not a production acceptance pass.
- **DR-11:** The candidate produced a useful calculation and caveats, using eight tools and 60,650 input tokens—within the original numerical ceilings. Therefore this success cannot be attributed solely to the larger limits; model/retrieval path variability matters. The serial control used five searches and three reads, then requested a ninth tool.
- Both candidate answers persisted and matched reloaded text/citations. No new answer was accepted as human-reviewed. The experiment supports combining retrieval/controller changes with a moderate capacity increase; it does not demonstrate that all 15 questions now work.

## Additional verified findings

- Company aliases: all four empty baseline searches used short names that did not match the stored exact names. `lower(company) = 'microsoft'` matches 0 filings; `ticker = 'MSFT'` matches 5. Resolve scope before searching.
- Read-handle confusion: invalid `S172`, `S145`, `S77` match chunk-index numbers present in the results; valid handles were different. The same index can occur in several filings, so automatic guessing is unsafe.
- The largest read chunk in a failed baseline case was 897 stored tokens. Across those cases, only 687–3,660 unique full-source tokens were read, while repeated context consumed 60,042–73,988 assistant input tokens. These are different measurements, not a direct compression ratio.
- DR-14 has 26 required groups mapped to 26 distinct chunks; the 20-citation cap prevents 100% labelled citation coverage in a single answer. The full gold answer is 3,231 characters, so the existing 10,000-character answer cap is not inherently too small for its prose.
- DR-11 candidate citations used equivalent passages outside the current labels: Microsoft FY2023 chunks 82 and 117, Alphabet FY2023 chunks 66 and 68. Direct text review found the operating-income figures and useful-life effects there. The recorded 0% exact read/citation recall is therefore not proof of unsupported prose. Preserve this result and review a new label version; do not silently rescore it as a pass.
- Candidate DR-05 advisory grading used 63,166 input tokens, separate from its 148,126 assistant input. Judge payloads include large display citation structures plus full passages; reduce duplication and schedule grading separately so QA itself does not crowd out assistant capacity. Embedding/keyword usage is also outside the main assistant ledger.

## Reproduce the trace analysis

From `backend/` (no model calls or database writes):

```bash
uv run --locked python -m evaluation.qa.analyze_budgets \
  --input evaluation/results/qa-reviewed-baseline-2026-09-05.json \
          evaluation/results/qa-budget-control-2026-09-07.json \
          evaluation/results/qa-budget-candidate-2026-09-07.json \
          evaluation/results/qa-budget-control-serial-2026-09-07.json \
  --output evaluation/results/research-budget-analysis-2026-09-07.json
```

Raw `qa-*.json` files are local/ignored; corresponding runs and results are retained in the private QA schema. The small analysis summary is retained in the repository. To repeat the live candidate run, use the normal QA runner in a separate process with the four environment overrides above; run profiles sequentially and respect provider cooldowns. Do not treat nonzero QA exit status as missing data—the runner records failed cases.

## Verification of this investigation

- All 22 analyzed case summaries reconcile with their recorded cumulative usage and completed tool counts.
- Relevant existing assistant, streaming, Azure-service and QA tests: **52 passed, 4 live tests deselected**. This verifies the current behavior, not the proposed controller.
- The new analysis command passed Ruff and formatting checks; documentation links and whitespace checks passed.
- All three new QA runs finished recording their selected cases, including failures. The final database check found **zero remaining temporary QA accounts**.
