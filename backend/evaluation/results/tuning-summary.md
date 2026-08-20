# Phase 7 retrieval tuning

The frozen ten-case evaluation set was run against the ingested sample corpus on
2026-08-19. Every run used 50 candidates per branch, a final limit of 10, and
RRF `k=60`. The first tuning pass used the normalized raw question for lexical
retrieval. After broadening Postgres full-text matching to an OR query while
retaining a strict-query score boost, only the semantic/lexical weights changed.

| Semantic weight | Lexical weight | Hybrid NDCG@10 | Hybrid hit rate@10 | Hybrid evidence recall@10 | Accepted |
| ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | 1 | 0.5881 | 1.0 | 1.0 | No |
| 2 | 1 | 0.7365 | 1.0 | 1.0 | No |
| 4 | 1 | 0.7848 | 1.0 | 1.0 | No |
| 10 | 1 | 0.8988 | 1.0 | 1.0 | No |
| 12 | 1 | 0.8994 | 1.0 | 1.0 | No |
| 15 | 1 | 0.8994 | 1.0 | 1.0 | No |
| 20 | 1 | 0.9003 | 1.0 | 1.0 | Yes |

At the selected 20:1 weights, semantic-only NDCG@10 was 0.9003 and
lexical-only NDCG@10 was 0.2609. Hybrid matched the stronger baseline while
preserving an independently ranked lexical branch for exact-term evidence. The
machine-readable accepted run is `retrieval-baseline.json`.

## AI keyword extraction

The lexical branch was then changed to extract typed SEC-specific keyword groups
in parallel with semantic embedding. A first prompt allowed speculative query
expansion and failed acceptance, so the final prompt permits only concepts stated
in the question and close lexical forms. Model selection was evaluated rather than
chosen from a single example.

| Lexical input | Keyword model | Lexical NDCG@10 | Lexical hit rate@10 | Hybrid NDCG@10 | Mean case latency | Accepted |
| --- | --- | ---: | ---: | ---: | ---: | :---: |
| Normalized raw question | None | 0.2609 | 0.6 | 0.9003 | 0.81 s | Yes |
| Typed explicit concepts | `gpt-5-mini` | 0.2312 | 0.6 | 0.9003 | 8.82 s | Yes |
| Typed explicit concepts | `gpt-5.4-nano` | 0.4006 | 0.7 | 0.9003 | 1.59 s | Yes |

`gpt-5.4-nano` is the selected default because it improved lexical quality over
the raw-question baseline while adding substantially less latency than
`gpt-5-mini`. Hybrid retained 1.0 hit rate and evidence-group recall at the
existing 20:1 RRF weights.
