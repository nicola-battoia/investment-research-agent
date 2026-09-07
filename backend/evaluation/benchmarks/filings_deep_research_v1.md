# Filings Deep-Research Answer Benchmark v1

## Purpose

This is a reference-answer benchmark for end-to-end testing of Document
Copilot. It is deliberately harder than a fact-lookup or a single-table
question. The cases require the system to retrieve evidence from multiple
filings, reconcile differences in definitions, perform calculations, explain
what the calculations do and do not prove, and cite the relevant filing passages.

The benchmark is intended to test answer quality, not only first-stage
retrieval. The existing `retrieval_cases.json` remains the frozen atomic
retrieval benchmark.

## Current evidence and runtime compatibility (2026-09-05)

The executable companion is [filings_deep_research_v1.json](filings_deep_research_v1.json).
Its 15 cases contain questions, reference answers, required evidence groups,
exact chunk UUIDs, text hashes and excerpts from the current Supabase corpus.
Each evidence group counts once; any listed alternative satisfies that group.
The source is the `sec_sections_v2` corpus: 27 documents and 6,373 chunks.
All live chunk texts were compared with the local ingestion checkpoints and matched.
Only the 25 company 10-Ks are used for these cases; BSP documents are excluded.

The financial table inputs and selected risk passages were checked against the
current chunks. Arithmetic is evaluated from the stated inputs. This is still a
research benchmark, not evidence that the assistant passes it. Independent human
review of qualitative completeness and the machine judge remains a release task.
Whole-document absence claims cannot be proved by retrieving one passage.
The Apple FY2021 AI-expression scan covered all 260,855 characters of its canonical
Markdown, whose SHA-256 matches the database document checksum; it found no `AI`,
`artificial intelligence`, or `machine learning` expressions.

- The current chunks have no populated `page_number`; old manual printed-page
  references have been replaced below by executable chunk references. This does
  not imply that the original printed pages were wrong.
- DR-01, DR-02, DR-03 and DR-14 explicitly compare ten filings. Eight total tool
  calls cannot cover ten filing reads plus a search. Evidence-group recall and
  answer quality are reported separately from turn completion.
- DR-07 can use the FY2022 and FY2025 comparative segment tables to cover all
  five requested fiscal years; five separate filings are unnecessary.
- The standalone prompts now name all five companies where the original relied
  on the document-level scope. The initial literal-prompt run elicited reasonable
  clarification requests; those are test-input defects, not assistant failures.
- DR-03 explicitly uses Amazon's capex net of sales and incentives. Its old
  wording could be read as requiring gross purchases while the gold used net.
- DR-15 requires an explained, cited abstention. The runtime's fixed,
  citation-free `insufficient_evidence` response is a known contract gap.
- The API/SSE runner exercises the actual model, tools, validation and stored
  answer reload. Browser rendering, Stop and multi-tab behavior are separate QA.

Run instructions: [evaluation guide](../README.md). Work plan:
[QA suite TODO](../../../docs/qa-suite-todo.md).

## Corpus scope

- Companies: Apple (`AAPL`), Microsoft (`MSFT`), NVIDIA (`NVDA`), Amazon
  (`AMZN`), and Alphabet (`GOOGL`).
- Fiscal years: 2021 through 2025, inclusive (25 Form 10-K filings).
- The Amazon and Alphabet fiscal 2025 reports were filed in calendar 2026. A
  correct system must filter by report/fiscal year, not assume filing year and
  fiscal year are identical.
- The two BSP offering documents in `data/downloads/2026/` are out of scope.
- All dollar amounts below are in USD. Unless otherwise stated, table inputs
  are in millions and calculated outputs are rounded.

## Evaluation conventions

For every case, a strong answer must:

1. Answer the exact question and show enough arithmetic to reproduce the
   conclusion.
2. Cite the relevant filing passage using its accession, section and current
   chunk identity. Do not invent a printed page number when page metadata is absent.
3. Preserve the filing's fiscal-year convention and disclosure definition.
4. Separate facts from calculations and calculations from interpretation.
5. State material comparability limits. It must not silently treat unlike
   metrics as identical.
6. Refuse unsupported causal or investment conclusions.

Suggested per-case score: 10 points - 6 for required findings, 2 for complete
and correct citations, 1 for the stated caveat, and 1 for disciplined
interpretation. A case passes at 8/10 only if it has no critical failure.
Reasonable rounding tolerance is +/- $0.2 billion, +/- 0.2 percentage points,
or +/- 1% relative error unless a case says otherwise.

Critical failures include inventing a missing disclosure, citing a filing that
does not support the claim, using a calendar-year value for the wrong fiscal
year, double-counting overlapping customer concentrations, or presenting a
causal claim that the filings do not establish.

## Coverage map

| ID | Main stress | Companies | Fiscal years |
|---|---|---|---|
| DR-01 | Cross-company operating leverage | All five | 2021, 2025 |
| DR-02 | Workforce normalization | All five | 2021, 2025 |
| DR-03 | Cash-flow calculation | All five | 2021, 2025 |
| DR-04 | Capex acceleration and business-model caveat | MSFT, GOOGL, AMZN, NVDA | 2023-2025 |
| DR-05 | Segment-economics comparison | MSFT, GOOGL, AMZN | 2021, 2025 |
| DR-06 | Backlog normalization | MSFT, GOOGL, AMZN | 2025 |
| DR-07 | Counterfactual segment analysis | AMZN | 2021-2025 |
| DR-08 | Mix and margin decomposition | AAPL | 2021, 2025 |
| DR-09 | Geographic-definition trap | AAPL, NVDA | 2021, 2025 |
| DR-10 | Demand, customer, and supply concentration | NVDA | 2021, 2025 |
| DR-11 | Accounting-estimate normalization | MSFT, GOOGL | 2022-2023 |
| DR-12 | One-time tax normalization | AAPL | 2023-2025 |
| DR-13 | Non-operating valuation normalization | AMZN | 2021-2022 |
| DR-14 | Qualitative disclosure evolution | All five | 2021, 2025 |
| DR-15 | Supported abstention / causal boundary | All five | 2025 |

---

## DR-01 - Which company converted incremental revenue into operating income most effectively?

**Question**

Use the 10-K filings for Apple (AAPL), Microsoft (MSFT), NVIDIA (NVDA), Amazon (AMZN), and Alphabet (GOOGL).

Across the five companies, calculate the incremental operating margin from
fiscal 2021 to fiscal 2025, defined as `(2025 operating income - 2021 operating
income) / (2025 revenue - 2021 revenue)`. Rank the companies, compare that result
with the change in reported operating margin, and identify the most important
reason not to interpret the ranking as a pure management-efficiency score.

**Why this stresses the system**

Ten filings are needed. The calculation is not reported in any table, and the
answer must distinguish incremental margin from ordinary operating margin.

**Gold answer**

| Rank | Company | Revenue 2021 -> 2025 | Operating income 2021 -> 2025 | Incremental operating margin | Reported operating margin 2021 -> 2025 |
|---:|---|---:|---:|---:|---:|
| 1 | NVIDIA | $16.675B -> $130.497B | $4.532B -> $81.453B | **67.6%** | 27.2% -> 62.4% (+35.2 pp) |
| 2 | Microsoft | $168.088B -> $281.724B | $69.916B -> $128.528B | **51.6%** | 41.6% -> 45.6% (+4.0 pp) |
| 3 | Apple | $365.817B -> $416.161B | $108.949B -> $133.050B | **47.9%** | 29.8% -> 32.0% (+2.2 pp) |
| 4 | Alphabet | $257.637B -> $402.836B | $78.714B -> $129.039B | **34.7%** | 30.6% -> 32.0% (+1.5 pp) |
| 5 | Amazon | $469.822B -> $716.924B | $24.879B -> $79.975B | **22.3%** | 5.3% -> 11.2% (+5.9 pp) |

NVIDIA ranks first by a wide margin. The interpretation cannot be “best
management” from this calculation alone: business mix, cyclicality, pricing,
fiscal calendars, acquisitions, accounting estimates, and each company's
business model differ materially. In particular, NVIDIA's shift toward Data
Center and Microsoft/Alphabet server useful-life changes affect the comparison.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AAPL FY2021: Revenue and operating income; use the column for this fiscal year | `0000320193-21-000105` | `73` |
| AAPL FY2025: Revenue and operating income; use the column for this fiscal year | `0000320193-25-000079` | `76` |
| MSFT FY2021: Revenue and operating income; use the column for this fiscal year | `0001564590-21-039151` | `141` |
| MSFT FY2025: Revenue and operating income; use the column for this fiscal year | `0000950170-25-100235` | `99` |
| NVDA FY2021: Revenue and operating income; use the column for this fiscal year | `0001045810-21-000010` | `99` |
| NVDA FY2025: Revenue and operating income; use the column for this fiscal year | `0001045810-25-000023` | `125` |
| AMZN FY2021: Revenue and operating income; use the column for this fiscal year | `0001018724-22-000005` | `75` |
| AMZN FY2025: Revenue and operating income; use the column for this fiscal year | `0001018724-26-000004` | `77` |
| GOOGL FY2021: Revenue and operating income; use the column for this fiscal year | `0001652044-22-000019` | `98` |
| GOOGL FY2025: Revenue and operating income; use the column for this fiscal year | `0001652044-26-000018` | `102` |

**Critical failure**: ranking by the change in ordinary operating margin rather
than calculating incremental operating margin.

---

## DR-02 - Did revenue per employee improve, and is the ranking truly comparable?

**Question**

Use the 10-K filings for Apple (AAPL), Microsoft (MSFT), NVIDIA (NVDA), Amazon (AMZN), and Alphabet (GOOGL).

Calculate fiscal-year revenue per disclosed employee for all five companies in
2021 and 2025. Which company improved the most, and what disclosure differences
prevent a literal productivity ranking?

**Gold answer**

| Company | 2021 revenue / employees | 2025 revenue / employees | Change |
|---|---:|---:|---:|
| Apple | $365.817B / 154,000 = **$2.38M** | $416.161B / 166,000 = **$2.51M** | **+5.5%** |
| Microsoft | $168.088B / 181,000 = **$0.93M** | $281.724B / 228,000 = **$1.24M** | **+33.1%** |
| NVIDIA | $16.675B / 18,975 = **$0.88M** | $130.497B / 36,000 = **$3.62M** | **+312.5%** |
| Amazon | $469.822B / 1,608,000 = **$0.29M** | $716.924B / 1,576,000 = **$0.45M** | **+55.7%** |
| Alphabet | $257.637B / 156,500 = **$1.65M** | $402.836B / 190,820 = **$2.11M** | **+28.2%** |

NVIDIA improved the most. This is a scale/output ratio, not a clean labor
productivity measure. Apple reports full-time equivalents; Microsoft reports
full-time employees; Amazon includes full-time and part-time employees and also
uses contractors and temporary personnel; the other companies' workforce and
outsourcing models differ. The figures are point-in-time headcounts divided by
full-year revenue, and mix and price changes can dominate labor productivity.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AAPL FY2021: Revenue and operating income; use the column for this fiscal year | `0000320193-21-000105` | `73` |
| AAPL FY2021: Headcount and its definition; year-end rather than annual average | `0000320193-21-000105` | `11` |
| AAPL FY2025: Revenue and operating income; use the column for this fiscal year | `0000320193-25-000079` | `76` |
| AAPL FY2025: Headcount and its definition; year-end rather than annual average | `0000320193-25-000079` | `12` |
| MSFT FY2021: Revenue and operating income; use the column for this fiscal year | `0001564590-21-039151` | `141` |
| MSFT FY2021: Headcount and its definition; year-end rather than annual average | `0001564590-21-039151` | `17` |
| MSFT FY2025: Revenue and operating income; use the column for this fiscal year | `0000950170-25-100235` | `99` |
| MSFT FY2025: Headcount and its definition; year-end rather than annual average | `0000950170-25-100235` | `16` |
| NVDA FY2021: Revenue and operating income; use the column for this fiscal year | `0001045810-21-000010` | `99` |
| NVDA FY2021: Headcount and its definition; year-end rather than annual average | `0001045810-21-000010` | `21` |
| NVDA FY2025: Revenue and operating income; use the column for this fiscal year | `0001045810-25-000023` | `125` |
| NVDA FY2025: Headcount and its definition; year-end rather than annual average | `0001045810-25-000023` | `23` |
| AMZN FY2021: Revenue and operating income; use the column for this fiscal year | `0001018724-22-000005` | `75` |
| AMZN FY2021: Headcount and its definition; year-end rather than annual average | `0001018724-22-000005` | `7` |
| AMZN FY2025: Revenue and operating income; use the column for this fiscal year | `0001018724-26-000004` | `77` |
| AMZN FY2025: Headcount and its definition; year-end rather than annual average | `0001018724-26-000004` | `8` |
| GOOGL FY2021: Revenue and operating income; use the column for this fiscal year | `0001652044-22-000019` | `98` |
| GOOGL FY2021: Headcount and its definition; year-end rather than annual average | `0001652044-22-000019` | `14` |
| GOOGL FY2025: Revenue and operating income; use the column for this fiscal year | `0001652044-26-000018` | `102` |
| GOOGL FY2025: Headcount and its definition; year-end rather than annual average | `0001652044-26-000018` | `12` |

**Critical failure**: calling Amazon's denominator “full-time employees” or
claiming the ratios prove relative employee quality.

---

## DR-03 - How did cash conversion change after cash capital spending?

**Question**

Use the 10-K filings for Apple (AAPL), Microsoft (MSFT), NVIDIA (NVDA), Amazon (AMZN), and Alphabet (GOOGL).

For every company, calculate a filing-based cash free-cash-flow proxy for 2021
and 2025 as operating cash flow less cash purchases/additions of property and
equipment (and intangible assets where NVIDIA combines them); use Amazon's
net-of-sales-and-incentives measure. Divide by revenue.
Rank 2025 and identify the largest improvement and deterioration.

**Gold answer**

| Company | 2021 proxy FCF margin | 2025 proxy FCF margin | Change |
|---|---:|---:|---:|
| NVIDIA | ($5.822B - $1.128B) / $16.675B = **28.1%** | ($64.089B - $3.236B) / $130.497B = **46.6%** | **+18.5 pp** |
| Microsoft | ($76.740B - $20.622B) / $168.088B = **33.4%** | ($136.162B - $64.551B) / $281.724B = **25.4%** | **-8.0 pp** |
| Apple | ($104.038B - $11.085B) / $365.817B = **25.4%** | ($111.482B - $12.715B) / $416.161B = **23.7%** | **-1.7 pp** |
| Alphabet | ($91.652B - $24.640B) / $257.637B = **26.0%** | ($164.713B - $91.447B) / $402.836B = **18.2%** | **-7.8 pp** |
| Amazon | ($46.327B - $55.396B) / $469.822B = **-1.9%** | ($139.514B - $128.320B) / $716.924B = **1.6%** | **+3.5 pp** |

The 2025 rank is NVIDIA, Microsoft, Apple, Alphabet, Amazon. NVIDIA has the
largest improvement; Microsoft has the largest deterioration, narrowly more
than Alphabet. The metric is intentionally a proxy: Amazon uses purchases net
of sales and incentives, NVIDIA combines intangible assets, and leases,
financing obligations, acquisitions, and working-capital timing are not made
fully comparable.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AAPL FY2021: Revenue and operating income; use the column for this fiscal year | `0000320193-21-000105` | `73` |
| AAPL FY2021: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0000320193-21-000105` | `77` |
| AAPL FY2025: Revenue and operating income; use the column for this fiscal year | `0000320193-25-000079` | `76` |
| AAPL FY2025: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0000320193-25-000079` | `80` |
| MSFT FY2021: Revenue and operating income; use the column for this fiscal year | `0001564590-21-039151` | `141` |
| MSFT FY2021: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0001564590-21-039151` | `144` |
| MSFT FY2025: Revenue and operating income; use the column for this fiscal year | `0000950170-25-100235` | `99` |
| MSFT FY2025: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0000950170-25-100235` | `102` |
| NVDA FY2021: Revenue and operating income; use the column for this fiscal year | `0001045810-21-000010` | `99` |
| NVDA FY2021: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0001045810-21-000010` | `103` |
| NVDA FY2025: Revenue and operating income; use the column for this fiscal year | `0001045810-25-000023` | `125` |
| NVDA FY2025: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0001045810-25-000023` | `129` |
| AMZN FY2021: Revenue and operating income; use the column for this fiscal year | `0001018724-22-000005` | `75` |
| AMZN FY2021: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0001018724-22-000005` | `59` |
| AMZN FY2025: Revenue and operating income; use the column for this fiscal year | `0001018724-26-000004` | `77` |
| AMZN FY2025: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0001018724-26-000004` | `65` |
| GOOGL FY2021: Revenue and operating income; use the column for this fiscal year | `0001652044-22-000019` | `98` |
| GOOGL FY2021: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0001652044-22-000019` | `101` |
| GOOGL FY2025: Revenue and operating income; use the column for this fiscal year | `0001652044-26-000018` | `102` |
| GOOGL FY2025: Operating cash flow and cash capex; retain net-of-incentives/intangible definitions | `0001652044-26-000018` | `105` |

**Critical failure**: using EBITDA, reported net income, or total investing cash
flow in place of the stated formula.

---

## DR-04 - Who accelerated infrastructure spending most, and why is NVIDIA's low cash capex misleading?

**Question**

Compare the change in cash capital spending from 2023 to 2025 for Microsoft,
Alphabet, Amazon, and NVIDIA. Also calculate 2025 cash capex as a percentage of
operating cash flow. Does NVIDIA's low percentage mean it has little capacity
or infrastructure exposure?

**Gold answer**

| Company | 2023 -> 2025 cash capex proxy | Growth | 2025 capex / operating cash flow |
|---|---:|---:|---:|
| Alphabet | $32.251B -> $91.447B | **+183.5%** | **55.5%** |
| Amazon | $48.133B -> $128.320B, net | **+166.6%** | **92.0%** |
| Microsoft | $28.107B -> $64.551B | **+129.7%** | **47.4%** |
| NVIDIA | $1.833B -> $3.236B, including intangibles | **+76.5%** | **5.0%** |

Alphabet grew fastest on this percentage measure, while Amazon consumed the
largest share of 2025 operating cash flow. NVIDIA's 5% does **not** mean low
capacity exposure. Its fabless/outsourced model shifts exposure into inventory,
prepayments, supplier capacity commitments, and cloud contracts. At FY2025 end,
NVIDIA disclosed $30.8B of inventory purchase and long-term supply/capacity
obligations and $14.3B of other non-inventory purchase obligations, including
$10.9B of multi-year cloud service agreements. Microsoft also disclosed $32.1B
committed for construction, primarily datacenters.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| MSFT FY2025: Cash capex and operating cash flow (2023 comparatives where present) | `0000950170-25-100235` | `102` |
| GOOGL FY2025: Cash capex and operating cash flow (2023 comparatives where present) | `0001652044-26-000018` | `105` |
| AMZN FY2025: Cash capex and operating cash flow (2023 comparatives where present) | `0001018724-26-000004` | `65` |
| NVDA FY2025: Cash capex and operating cash flow (2023 comparatives where present) | `0001045810-25-000023` | `129` |
| AMZN FY2023: 2023 cash capex net of sales and incentives | `0001018724-24-000008` | `63` |
| NVDA FY2025: Supply and non-inventory/cloud commitments; cancellable/reschedulable amounts are not cash capex | `0001045810-25-000023` | `171` |
| MSFT FY2025: Construction commitments, primarily datacenters | `0000950170-25-100235` | `125` |

**Critical failure**: concluding that NVIDIA has only $3.2B of capacity-related
exposure or adding commitments directly to capex as if they were current-year
cash payments.

---

## DR-05 - How did cloud segment economics change from 2021 to 2025?

**Question**

Compare 2021 and 2025 segment operating margins for AWS, Google Cloud, and
Microsoft Intelligent Cloud. Which improved most, which remained highest, and
why is this not an apples-to-apples ranking of public-cloud profitability?

**Gold answer**

| Disclosure | 2021 revenue / operating income / margin | 2025 revenue / operating income / margin | Margin change |
|---|---:|---:|---:|
| AWS | $62.202B / $18.532B / **29.8%** | $128.725B / $45.606B / **35.4%** | **+5.6 pp** |
| Google Cloud | $19.206B / **-$3.099B** / **-16.1%** | $58.705B / $13.910B / **23.7%** | **+39.8 pp** |
| Microsoft Intelligent Cloud | $60.080B / $26.126B / **43.5%** | $106.265B / $44.589B / **42.0%** | **-1.5 pp** |

Google Cloud improved most and crossed from loss to profit. Microsoft
Intelligent Cloud remained highest by reported segment margin, but its margin
slipped. This is not a pure Azure-versus-AWS-versus-GCP comparison: Intelligent
Cloud includes server products and enterprise services in addition to Azure;
Google Cloud includes Workspace; AWS has its own allocation policy. Microsoft
also changed its segment composition in FY2025 and recast only the presented
prior periods, not its FY2021 filing. Microsoft's 2025 filing further states
that scaling AI infrastructure pressured cloud gross margin.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AMZN FY2021: Segment revenue and operating income; preserve segment scope and loss sign | `0001018724-22-000005` | `143` |
| AMZN FY2025: Segment revenue and operating income; preserve segment scope and loss sign | `0001018724-26-000004` | `151` |
| GOOGL FY2021: Segment revenue and operating income; preserve segment scope and loss sign | `0001652044-22-000019` | `176` |
| GOOGL FY2025: Segment revenue and operating income; preserve segment scope and loss sign | `0001652044-26-000018` | `185` |
| MSFT FY2021: Segment revenue and operating income; preserve segment scope and loss sign | `0001564590-21-039151` | `243` |
| MSFT FY2025: Segment revenue and operating income; preserve segment scope and loss sign | `0000950170-25-100235` | `145` |
| MSFT FY2025: Segment composition changed; presented prior periods recast | `0000950170-25-100235` | `71` |
| MSFT FY2025: Microsoft Cloud gross-margin impact from AI infrastructure | `0000950170-25-100235` | `75` |

**Critical failure**: labeling Microsoft Intelligent Cloud revenue as Azure
revenue or omitting Google Cloud's 2021 loss sign.

---

## DR-06 - Which cloud backlog looks largest relative to revenue, and can it be ranked cleanly?

**Question**

Using the FY2025 filings, compare remaining performance obligations or backlog
for Microsoft, Amazon, and Alphabet. Normalize the disclosed balances to a
relevant revenue denominator, discuss recognition timing, and explain why the
ratios cannot be treated as directly comparable “growth coverage.”

**Gold answer**

- Amazon disclosed approximately **$244B**, primarily AWS, versus FY2025 AWS
  sales of $128.725B: about **1.90x**. Its weighted-average remaining contract
  life was **4.1 years**.
- Alphabet disclosed **$242.8B**, primarily Google Cloud, versus Google Cloud
  revenue of $58.705B: **up to about 4.14x** if all backlog were Cloud. It is an
  upper-bound proxy because the filing says “primarily,” not entirely, Cloud.
  Just over **50%** is expected to be recognized over the next 24 months.
- Microsoft disclosed **$375B** total-company RPO, of which **$368B** was
  commercial. Total RPO / total revenue is about **1.33x**. A commonly tempting
  commercial-RPO / Microsoft-Cloud-revenue ratio is **2.18x** ($368B / $168.9B),
  but those scopes do not match exactly. Microsoft expects about **40%** of total
  RPO over the next 12 months.

Alphabet has the largest indicative ratio, but a strict rank is not supportable.
The companies exclude or include short-duration and cancellable arrangements
differently, the disclosed scopes differ, and backlog is not a forecast: usage,
delivery, cancellations, contract duration, and timing affect recognition.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AMZN FY2025: Backlog scope, amount and recognition timing | `0001018724-26-000004` | `106` |
| GOOGL FY2025: Backlog scope, amount and recognition timing | `0001652044-26-000018` | `121` |
| MSFT FY2025: Backlog scope, amount and recognition timing | `0000950170-25-100235` | `136` |
| AMZN FY2025: Revenue denominator and scope; Cloud and commercial RPO are not identical | `0001018724-26-000004` | `151` |
| GOOGL FY2025: Revenue denominator and scope; Cloud and commercial RPO are not identical | `0001652044-26-000018` | `185` |
| MSFT FY2025: Revenue denominator and scope; Cloud and commercial RPO are not identical | `0000950170-25-100235` | `99` |
| MSFT FY2025: Revenue denominator and scope; Cloud and commercial RPO are not identical | `0000950170-25-100235` | `146` |

**Critical failure**: asserting that all Alphabet backlog is Google Cloud or
that backlog will become revenue in the next year.

---

## DR-07 - In which year did AWS actually keep Amazon operating-profit positive?

**Question**

For each fiscal year 2021-2025, subtract AWS operating income from Amazon's
consolidated operating income. In which years would the remaining segments have
reported a combined operating loss? How should “AWS funded the rest of Amazon”
be phrased precisely?

**Gold answer**

| Fiscal year | Consolidated operating income | AWS operating income | Consolidated less AWS | AWS / consolidated |
|---:|---:|---:|---:|---:|
| 2021 | $24.879B | $18.532B | **+$6.347B** | 74.5% |
| 2022 | $12.248B | $22.841B | **-$10.593B** | 186.5% |
| 2023 | $36.852B | $24.631B | **+$12.221B** | 66.8% |
| 2024 | $68.593B | $39.834B | **+$28.759B** | 58.1% |
| 2025 | $79.975B | $45.606B | **+$34.369B** | 57.0% |

Only **2022** had a combined non-AWS operating loss. AWS also offset the
International segment's losses in 2021-2023, but North America was profitable
in 2021 and 2023. In 2022, AWS operating profit offset the combined operating loss of the other
segments. This does not establish that AWS funded every individual business. The subtraction is an
analytical counterfactual, not a cash-transfer disclosure, and shared cost
allocations could change without AWS.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AMZN FY2022: 2021-2022 AWS, North America, International and consolidated operating income | `0001018724-23-000004` | `147`, `54` |
| AMZN FY2025: 2023-2025 AWS, North America, International and consolidated operating income | `0001018724-26-000004` | `151` |

**Critical failure**: treating AWS's percentage of consolidated operating
income as a revenue share or claiming the counterfactual is a reported measure.

---

## DR-08 - How much of Apple's five-year gross-margin expansion came from Services mix?

**Question**

From 2021 to 2025, quantify Apple's Services share of revenue and gross profit,
the share of incremental revenue and gross profit contributed by Services, and
a two-step gross-margin bridge that holds 2021 product and Services margins
constant at the 2025 revenue mix. What does the bridge imply?

**Gold answer**

- Services revenue rose from **$68.425B to $109.158B**. Its revenue share rose
  from **18.7% to 26.2%** (+7.5 pp).
- Services gross profit rose from **$47.710B to $82.314B**. Its share of total
  gross profit rose from **31.2% to 42.2%** (+11.0 pp).
- Total revenue rose $50.344B; Services supplied **$40.733B, or 80.9%**, of the
  increase.
- Total gross profit rose $42.365B; Services supplied **$34.604B, or 81.7%**, of
  the increase.
- Reported total gross margin rose from **41.8% to 46.9%** (+5.1 pp).
- Applying the filing-rounded 2021 category margins (Products 35.3%, Services
  69.7%) to 2025 category revenue produces an indicative **44.3%** total margin.
  On this sequential bridge, mix contributes about **2.5 pp** and
  category-margin improvement contributes the remaining **2.6 pp**. Using the
  exact category dollar values before rounding produces 44.4%, 2.6 pp, and 2.5
  pp, respectively; either version is acceptable if the arithmetic is shown.

The answer is not simply “Services caused all margin expansion.” Services drove
most incremental gross profit and about half of this order-dependent margin
bridge; improved product and Services category margins explain the rest. A
different decomposition order can allocate interaction differently and should
be disclosed.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AAPL FY2021: Product/Services revenue; total revenue | `0000320193-21-000105` | `73`, `55` |
| AAPL FY2021: Product/Services gross profit and total gross profit | `0000320193-21-000105` | `60` |
| AAPL FY2025: Product/Services revenue; total revenue | `0000320193-25-000079` | `76`, `59` |
| AAPL FY2025: Product/Services gross profit and total gross profit | `0000320193-25-000079` | `61` |

**Critical failure**: using Services revenue share as Services gross-profit
share, or presenting the 2.5 pp decomposition as a company-reported figure.

---

## DR-09 - Did lower reported China revenue mean lower China-related business risk?

**Question**

Compare Apple's Greater China revenue exposure and NVIDIA's China/Hong Kong
billing exposure in 2021 and 2025. Can the percentages be used to conclude that
Apple was more exposed than NVIDIA in 2025, or that China-related risk fell in
proportion to reported revenue?

**Gold answer**

- Apple Greater China revenue was **$68.366B / $365.817B = 18.7%** in 2021 and
  **$64.377B / $416.161B = 15.5%** in 2025, a 3.2 pp decline.
- NVIDIA reported China including Hong Kong at **23% of revenue** in 2021 and
  **$17.108B / $130.497B = 13.1%** in 2025, a roughly 9.9 pp decline in the
  reported billing-location proxy.

A literal end-market ranking is not supportable. Apple generally assigns
geographic segment sales using customer/retail-store location. NVIDIA assigns
geography by billing location even if the indirect customer is elsewhere. In
2025, Singapore was 18% of NVIDIA revenue by billing location, but shipments to
Singapore were less than 2%, illustrating the distortion.

Risk also did not necessarily fall with revenue share. NVIDIA said China Data
Center revenue remained well below pre-export-control levels and described the
risk of effective exclusion from parts of China and other markets. Apple still
had a significant majority of manufacturing through outsourcing partners in
China mainland and other Asian countries, relied on single/limited sources, and
reported 2025 tariff pressure on product gross margin. Sales exposure and
supply-chain/regulatory exposure are different risk channels.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AAPL FY2021: Greater China and total revenue | `0000320193-21-000105` | `58` |
| AAPL FY2025: Greater China and total revenue | `0000320193-25-000079` | `57` |
| NVDA FY2021: China/Hong Kong billing exposure (23%) | `0001045810-21-000010` | `44` |
| NVDA FY2021: Billing geography is not end-customer geography | `0001045810-21-000010` | `76` |
| NVDA FY2025: China/Hong Kong billing revenue and total revenue | `0001045810-25-000023` | `192` |
| NVDA FY2025: Singapore billing share versus shipments | `0001045810-25-000023` | `193` |
| NVDA FY2025: China Data Center revenue and export controls | `0001045810-25-000023` | `90` |
| AAPL FY2025: Asian manufacturing and single/limited sources | `0000320193-25-000079` | `22` |
| AAPL FY2025: 2025 tariff pressure on product gross margin | `0000320193-25-000079` | `63` |
| AAPL FY2025: Geographic allocation follows customer and retail-store location | `0000320193-25-000079` | `17` |

**Critical failure**: treating NVIDIA billing location as final shipment or end
customer location, or adding Singapore to China exposure without evidence.

---

## DR-10 - How did NVIDIA's concentration risk change as Data Center became dominant?

**Question**

Assess NVIDIA's change in business-line, customer, and supply concentration from
2021 to 2025. Quantify each dimension and explain whether the filings support a
claim that explosive growth also reduced concentration risk.

**Gold answer**

- Data Center revenue rose from **$6.696B (40.2% of $16.675B)** in 2021 to
  **$115.186B (88.3% of $130.497B)** in 2025. The four-year CAGR was about
  **103.7%**, but revenue became much more concentrated in one end market.
- No customer represented 10% or more of FY2021 revenue. In FY2025, three direct
  customers represented **12%, 11%, and 11%**, or at least 34% combined. One
  indirect customer was also estimated at 10% or more, but it bought through
  multiple parties including Direct Customer B, so it must **not** be added to
  34% as though non-overlapping.
- At FY2025 end NVIDIA had **$10.1B inventory**, **$30.8B** of inventory purchase
  and long-term supply/capacity obligations (about **3.0x** inventory), **$5.0B**
  of current plus long-term prepaid supply/capacity balances, and $14.3B of
  other purchase obligations including $10.9B of cloud agreements.
- The supply chain remained mainly concentrated in Asia-Pacific and depended on
  foundries, memory suppliers, CoWoS packaging, and contract manufacturers.

Growth did not reduce concentration risk. It increased end-market and disclosed
customer concentration while also increasing forward supply commitments. The
filing describes both shortage risk and excess/obsolescence risk; this is a
two-sided operating leverage, not a one-way demand benefit.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| NVDA FY2021: Data Center and total revenue | `0001045810-21-000010` | `168` |
| NVDA FY2021: No customer reached 10% | `0001045810-21-000010` | `76` |
| NVDA FY2025: Data Center and total revenue | `0001045810-25-000023` | `195` |
| NVDA FY2025: Direct customer shares and overlapping indirect customer | `0001045810-25-000023` | `103` |
| NVDA FY2025: Inventory and supply/capacity obligations | `0001045810-25-000023` | `123` |
| NVDA FY2025: Long-term supply/capacity prepayments | `0001045810-25-000023` | `164` |
| NVDA FY2025: Current supply/capacity prepayments | `0001045810-25-000023` | `165` |
| NVDA FY2025: Commitment scope, cancellation rights and cloud contracts | `0001045810-25-000023` | `171` |
| NVDA FY2025: Foundry, memory, CoWoS and contract-manufacturer dependence | `0001045810-25-000023` | `16` |

**Critical failure**: adding the indirect customer's estimated share to the
direct-customer total, or claiming all $30.8B is non-cancellable.

---

## DR-11 - How much of 2023 operating-income growth came from longer server lives?

**Question**

Microsoft and Alphabet both lengthened server/network-equipment useful lives in
2023. Quantify the disclosed operating-income/depreciation benefit as a share of
each company's year-over-year operating-income increase. What would operating
income growth have been without the disclosed benefit, as a simple analytical
bridge?

**Gold answer**

- Microsoft increased server and network equipment lives from four to six years.
  It disclosed a **$3.7B** FY2023 operating-income benefit. Operating income rose
  from $83.383B to $88.523B, a $5.140B increase; the estimate change equals
  **72.0%** of that increase. Subtracting the disclosed benefit gives $84.823B,
  or about **1.7%** growth instead of reported 6.2%.
- Alphabet changed servers and certain network equipment to six years. It
  disclosed a **$3.9B reduction in depreciation** in 2023. Operating income rose
  from $74.842B to $84.293B, a $9.451B increase; the benefit equals **41.3%** of
  that increase. Subtracting it gives $80.393B, or about **7.4%** growth instead
  of reported 12.6%.

These are prospective GAAP estimate changes, not improprieties, and the simple
bridge is not a full pro-forma restatement. It holds taxes, asset additions,
allocations, and all other factors constant. Microsoft directly disclosed an
operating-income impact; Alphabet disclosed reduced depreciation, which flows
through operating costs, so the comparison should retain that wording.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| MSFT FY2023: 2022-2023 operating income | `0000950170-23-035122` | `111` |
| MSFT FY2023: Useful-life change and effect on operating income | `0000950170-23-035122` | `79` |
| GOOGL FY2023: 2022-2023 operating income | `0001652044-24-000022` | `106` |
| GOOGL FY2023: Useful-life change and depreciation impact | `0001652044-24-000022` | `110` |

**Critical failure**: treating the estimate changes as cash savings or adding
the benefit to reported operating income rather than subtracting it for the
analytical bridge.

---

## DR-12 - Did Apple's 2024 earnings decline reflect weaker operations?

**Question**

Apple's FY2024 revenue and operating income rose, but net income fell. Reconcile
the apparent contradiction using the State Aid Decision. Calculate an
illustrative net income and effective tax rate excluding the disclosed one-time
net tax charge, and compare the adjusted net income with 2023.

**Gold answer**

- FY2024 revenue rose to **$391.035B** from $383.285B and operating income rose
  to **$123.216B** from $114.301B, but net income fell to **$93.736B** from
  $96.995B.
- Apple disclosed a **$10.2B one-time net income-tax charge** related to the
  State Aid Decision. Adding it back produces illustrative adjusted FY2024 net
  income of **$103.936B**, about **7.2% above** 2023 instead of 3.4% below.
- Reported FY2024 pretax income was $123.485B and tax provision was $29.749B.
  Excluding $10.2B gives an illustrative tax provision of $19.549B and rate of
  **15.8%**, versus reported **24.1%** and FY2025's **15.6%**.
- Apple also disclosed a **EUR14.2B / $15.8B cash obligation** to Ireland, with
  settlement funds held in escrow. That cash obligation must not be confused
  with the $10.2B current-period accounting charge.

The filing supports the conclusion that the reported net-income decline was
dominated by the tax item, not operating deterioration. The adjustment is an
analytical add-back, not an Apple-provided non-GAAP measure, and ignores any
second-order tax effects already embedded in “net.”

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AAPL FY2024: Revenue, operating income, pretax income, tax and net income | `0000320193-24-000123` | `71` |
| AAPL FY2024: Net State Aid tax charge versus gross escrow settlement | `0000320193-24-000123` | `95` |
| AAPL FY2025: FY2025 income statement and FY2024/FY2023 comparatives | `0000320193-25-000079` | `76` |
| AAPL FY2025: 2025 effective tax rate (15.6%) | `0000320193-25-000079` | `66` |

**Critical failure**: adding back the $15.8B cash obligation to net income or
calling the tax charge an operating expense.

---

## DR-13 - How much of Amazon's 2021-2022 earnings reversal was Rivian?

**Question**

Amazon swung from $33.364B net income in 2021 to a $2.722B net loss in 2022.
Reconcile the swing using operating income, total non-operating income/expense,
and the Rivian fair-value changes. Calculate pretax income excluding the Rivian
gain/loss. Did Rivian explain all of the deterioration?

**Gold answer**

- Operating income fell from **$24.879B to $12.248B**, a **$12.631B** decline.
- Total non-operating result moved from **+$13.272B to -$18.184B**, a
  **$31.456B** adverse swing.
- Within that, Rivian moved from an **$11.8B valuation gain** to a **$12.7B
  valuation loss**, a **$24.5B** adverse swing, or about 78% of the non-operating
  swing.
- Reported pretax income was $24.879B + $13.272B = **$38.151B** in 2021 and
  $12.248B - $18.184B = **-$5.936B** in 2022.
- Excluding only Rivian gives illustrative pretax income of **$26.351B** in 2021
  and **$6.764B** in 2022 - still a **$19.587B decline**.

Rivian explains much, but not all, of the reversal. Underlying operating income
also fell sharply, and other non-operating items and taxes mattered. A net-income
add-back would require tax assumptions, so the defensible normalization is at
pretax income.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AMZN FY2022: 2021-2022 operating income, non-operating items and pretax income | `0001018724-23-000004` | `77` |
| AMZN FY2022: Rivian valuation gain/loss and its non-operating treatment | `0001018724-23-000004` | `59`, `91` |

**Critical failure**: saying Amazon's operating business lost $2.7B in 2022 or
adding the pretax Rivian loss directly to after-tax net income without a caveat.

---

## DR-14 - How did AI disclosure evolve from opportunity to investable risk?

**Question**

Use the 10-K filings for Apple (AAPL), Microsoft (MSFT), NVIDIA (NVDA), Amazon (AMZN), and Alphabet (GOOGL).

Compare each company's FY2021 and FY2025 10-K treatment of artificial
intelligence. For each company, distinguish opportunity/product language from
explicit downside language in four categories: product/content harm,
regulation/IP, infrastructure/capacity cost, and monetization/demand/return
uncertainty. What changed across the corpus?

**Gold answer**

| Company | FY2021 baseline | Material FY2025 change |
|---|---|---|
| Apple | No explicit AI reference in the filing text; technology, product-safety, IP, regulation, infrastructure, and return risks were generic rather than AI-specific. | Explicitly links AI features to harmful/inaccurate experiences and safety, IP/licensing, changing laws, and competitive execution. It does not disclose an AI-specific revenue, infrastructure cost, or return. |
| Microsoft | AI appeared as an Azure/product capability and acquisition rationale. The filing already warned that flawed algorithms, biased or insufficient datasets, and controversial uses could hurt adoption, create liability, and damage its brand; it also said AI regulation could increase cost or restrict opportunity. Infrastructure and investment-return risks were framed mainly at the broader cloud level. | Product-harm and regulatory language becomes generative-AI-specific and adds IP/data risks. The major financial change is explicit large-scale AI infrastructure/capacity cost and the risk that AI investments do not produce sufficient demand or returns. FY2025 cloud gross margin was pressured by scaling AI infrastructure. |
| NVIDIA | AI was already the core Data Center demand thesis and product opportunity. The filing had privacy/use and general adoption risks, but not a generative-AI monetization or capacity-commitment framework. | The risk shifts toward customer ability to fund AI infrastructure, forecast volatility, export controls and regulation, annual product transitions, supply/capacity commitments, and inability to quantify generative-AI demand precisely. Product/content harm remains less central than for software platforms. |
| Amazon | AI/ML appeared in AWS offerings, shared technology spending, and broad regulatory lists; spending could not be cleanly allocated to AI, but the filing did not give a distinct AI return framework. | AI becomes a named competitive, talent, infrastructure-spending, legal/reputational, adoption, and return risk; Amazon says benefits from newer AI/automation activities may not meet expectations and impacts can be difficult to isolate and quantify. |
| Alphabet | AI research and product improvement were prominent opportunities. The filing already said AI/ML products created ethical, technological, legal, and regulatory challenges, and its broader new-venture disclosure warned that investments might not earn an adequate return. Infrastructure risk was discussed mainly at the cloud/company level. | All four categories become specifically tied to modern AI: harmful or inaccurate output and discrimination, IP/privacy, AI regulation, very large AI infrastructure investment, capacity and energy constraints, competition and user-behavior change, and uncertain commercial returns. |

The corpus-wide change is not that AI first appeared in 2025. Microsoft,
NVIDIA, Amazon, and Alphabet already discussed AI in 2021. What changed was the
specificity and financial materiality of downside disclosure: generative-AI
product harms, new regulation, power/datacenter/supply constraints, large
committed spending, and uncertain monetization became explicit. Apple is the
clearest “absent to explicit” transition.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AAPL FY2021: Generic product/technology risks; absence of AI requires the recorded whole-filing scan | `0000320193-21-000105` | `25` |
| AAPL FY2025: AI product harm, IP and regulatory risks | `0000320193-25-000079` | `24` |
| AAPL FY2025: AI product harm, IP and regulatory risks | `0000320193-25-000079` | `26` |
| AAPL FY2025: AI product harm, IP and regulatory risks | `0000320193-25-000079` | `35` |
| MSFT FY2021: AI opportunity and already-present algorithm/bias risks | `0001564590-21-039151` | `5` |
| MSFT FY2021: AI opportunity and already-present algorithm/bias risks | `0001564590-21-039151` | `69` |
| MSFT FY2025: AI investment/return uncertainty, product harm, IP/regulation and margin cost | `0000950170-25-100235` | `30` |
| MSFT FY2025: AI investment/return uncertainty, product harm, IP/regulation and margin cost | `0000950170-25-100235` | `31` |
| MSFT FY2025: AI investment/return uncertainty, product harm, IP/regulation and margin cost | `0000950170-25-100235` | `43` |
| MSFT FY2025: AI investment/return uncertainty, product harm, IP/regulation and margin cost | `0000950170-25-100235` | `75` |
| NVDA FY2021: AI opportunity and privacy/use risk | `0001045810-21-000010` | `6` |
| NVDA FY2021: AI opportunity and privacy/use risk | `0001045810-21-000010` | `51` |
| NVDA FY2025: Demand uncertainty, capacity/supply commitments and export controls | `0001045810-25-000023` | `34` |
| NVDA FY2025: Demand uncertainty, capacity/supply commitments and export controls | `0001045810-25-000023` | `37` |
| NVDA FY2025: Demand uncertainty, capacity/supply commitments and export controls | `0001045810-25-000023` | `90` |
| NVDA FY2025: Demand uncertainty, capacity/supply commitments and export controls | `0001045810-25-000023` | `171` |
| AMZN FY2021: AI opportunity, shared technology and broad regulatory exposure | `0001018724-22-000005` | `29` |
| AMZN FY2021: AI opportunity, shared technology and broad regulatory exposure | `0001018724-22-000005` | `41` |
| AMZN FY2025: AI adoption/return uncertainty, IP and inability to isolate impacts | `0001018724-26-000004` | `14` |
| AMZN FY2025: AI adoption/return uncertainty, IP and inability to isolate impacts | `0001018724-26-000004` | `19` |
| AMZN FY2025: AI adoption/return uncertainty, IP and inability to isolate impacts | `0001018724-26-000004` | `54` |
| GOOGL FY2021: Existing investment-return and ethical/legal AI risks | `0001652044-22-000019` | `19` |
| GOOGL FY2021: Existing investment-return and ethical/legal AI risks | `0001652044-22-000019` | `20` |
| GOOGL FY2025: AI investment returns, IP/competition and energy/capacity constraints | `0001652044-26-000018` | `16` |
| GOOGL FY2025: AI investment returns, IP/competition and energy/capacity constraints | `0001652044-26-000018` | `19` |
| GOOGL FY2025: AI investment returns, IP/competition and energy/capacity constraints | `0001652044-26-000018` | `22` |

**Critical failure**: claiming none of the companies discussed AI in 2021, or
equating an increase in mentions with proof of higher realized financial risk.

---

## DR-15 - Do the filings prove which company earned the best return on generative AI?

**Question**

Use the 10-K filings for Apple (AAPL), Microsoft (MSFT), NVIDIA (NVDA), Amazon (AMZN), and Alphabet (GOOGL).

Using only this corpus, identify which of the five companies earned the highest
return on generative-AI investment by FY2025 and quantify how many basis points
of its margin expansion were caused by generative AI.

**Gold answer**

The requested ranking and causal basis-point calculation are **not supported by
the filings**. A correct answer should refuse to manufacture them, while still
summarizing the evidence that is available:

- None of the five provides a consistent generative-AI investment denominator,
  generative-AI revenue/profit numerator, or ROIC/ROI measure.
- Consolidated capex and shared infrastructure support AI, cloud, internal
  workloads, and other services; segment allocations and business models differ.
- Microsoft gives a specific cost direction - Microsoft Cloud gross margin fell
  to 69% partly because of scaling AI infrastructure, offset partly by Azure
  efficiencies - but this does not disclose AI ROI or the causal effect on
  consolidated operating margin.
- Amazon says the effects of AI and other macro/technology factors are difficult
  to predict, isolate, and quantify, and that intended benefits may not meet
  expectations.
- NVIDIA says it is difficult to estimate with reasonable precision the impact
  of generative AI on reported revenue or forecast demand.
- Alphabet says AI-related investments may not be commercially viable or earn
  an adequate return, while its capex is shared across user, enterprise, and
  internal research needs.
- Apple's filings do not separately disclose AI investment or AI-driven revenue
  and margin.

The strongest supported conclusion is that the filings show large AI-related
investment, demand narratives, and some disclosed cost pressure, but do not
identify a cross-company return metric or isolate causal margin effects. The
system should offer the calculations it *can* support (for example DR-03 to
DR-06) and clearly stop at the causal boundary.

**Required evidence (current corpus)**

| Required fact group | Accession | Chunk index (alternatives) |
|---|---|---|
| AAPL FY2025: AI risk and consolidated financial/cash-flow disclosures; these are not AI-only ROI | `0000320193-25-000079` | `24` |
| AAPL FY2025: AI risk and consolidated financial/cash-flow disclosures; these are not AI-only ROI | `0000320193-25-000079` | `76` |
| AAPL FY2025: AI risk and consolidated financial/cash-flow disclosures; these are not AI-only ROI | `0000320193-25-000079` | `80` |
| MSFT FY2025: AI cloud gross-margin pressure and shared cash capex | `0000950170-25-100235` | `75` |
| MSFT FY2025: AI cloud gross-margin pressure and shared cash capex | `0000950170-25-100235` | `102` |
| AMZN FY2025: Returns may disappoint; AI effects cannot be isolated | `0001018724-26-000004` | `14` |
| AMZN FY2025: Returns may disappoint; AI effects cannot be isolated | `0001018724-26-000004` | `54` |
| NVDA FY2025: Generative-AI demand cannot be precisely estimated; supply/cloud commitments | `0001045810-25-000023` | `37` |
| NVDA FY2025: Generative-AI demand cannot be precisely estimated; supply/cloud commitments | `0001045810-25-000023` | `171` |
| GOOGL FY2025: AI returns not assured; consolidated capex is not an AI-only denominator | `0001652044-26-000018` | `16` |
| GOOGL FY2025: AI returns not assured; consolidated capex is not an AI-only denominator | `0001652044-26-000018` | `105` |

**Critical failure**: selecting a winner, computing AI ROI from total company
capex, or attributing total margin change to AI because management mentioned AI
in the same filing.

---

## Suggested run-level acceptance criteria

A pilot run should be considered credible only if:

- At least 12 of 15 cases score 8/10 or better.
- DR-15 returns an explicit supported abstention.
- DR-05, DR-06, DR-09, and DR-10 preserve their comparability/overlap caveats.
- No answer has a critical failure.
- At least 95% of material numeric claims have a citation to the correct filing
  and printed page.
- Every calculated value can be reproduced from cited inputs within the stated
  tolerance.

Failures should be classified separately as retrieval, table extraction,
arithmetic, citation, synthesis, comparability, or unsupported-inference errors.
That separation matters: a fluent final answer can hide a retrieval miss, and a
correct number can still be unusable if its citation points to the wrong filing
or page.
