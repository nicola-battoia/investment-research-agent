# First-step ingestion metrics

Historical local measurement, preserved without changing its values. Use the
[active ingestion guide](../README.md#10-inspect-corpus-metrics) to generate a new
report; this file does not verify the current hosted database.

Recorded: `2026-08-26 00:27:41 CEST`

```text
Tokenizer model: text-embedding-3-small

Markdown document                                         Tokens
--------------------------------------------------  ------------
2025/aapl_10-k_2025-10-31_0000320193-25-000079.md         69,011
2024/aapl_10-k_2024-11-01_0000320193-24-000123.md         68,162
2023/aapl_10-k_2023-11-03_0000320193-23-000106.md         67,044
2022/aapl_10-k_2022-10-28_0000320193-22-000108.md         69,114
2021/aapl_10-k_2021-10-29_0000320193-21-000105.md         70,236
2025/msft_10-k_2025-07-30_0000950170-25-100235.md         74,989
2024/msft_10-k_2024-07-30_0000950170-24-087843.md         84,694
2023/msft_10-k_2023-07-27_0000950170-23-035122.md         80,837
2022/msft_10-k_2022-07-28_0001564590-22-026876.md        109,195
2021/msft_10-k_2021-07-29_0001564590-21-039151.md        110,209
2025/nvda_10-k_2025-02-26_0001045810-25-000023.md        100,128
2024/nvda_10-k_2024-02-21_0001045810-24-000029.md        104,956
2023/nvda_10-k_2023-02-24_0001045810-23-000017.md        100,625
2022/nvda_10-k_2022-03-18_0001045810-22-000036.md         95,482
2021/nvda_10-k_2021-02-26_0001045810-21-000010.md         94,749
2025/amzn_10-k_2026-02-06_0001018724-26-000004.md         86,177
2024/amzn_10-k_2025-02-07_0001018724-25-000004.md         83,873
2023/amzn_10-k_2024-02-02_0001018724-24-000008.md         84,925
2022/amzn_10-k_2023-02-03_0001018724-23-000004.md         80,524
2021/amzn_10-k_2022-02-04_0001018724-22-000005.md         76,879
2025/googl_10-k_2026-02-05_0001652044-26-000018.md       110,523
2024/googl_10-k_2025-02-05_0001652044-25-000014.md       111,122
2023/googl_10-k_2024-01-31_0001652044-24-000022.md       107,074
2022/googl_10-k_2023-02-03_0001652044-23-000016.md       101,067
2021/googl_10-k_2022-02-02_0001652044-22-000019.md       101,794
2026/bsp_424b4_2026-07-01_0001104659-26-079884.md        364,700
2026/bsp_f-1_2026-06-08_0001104659-26-071170.md          361,676

Total tokens: 2,969,765
Mean tokens per document: 109,991.30

Chunk metrics
Chunks: 6,373
Tokens: 2,150,656
Length (tokens): min 25, max 1,736, mean 337.46, median 338.00
Small chunks: ≤20 0, ≤50 7, ≤100 59, <150 763
Below 100: 40 (40 atomic table exceptions)
Minimum-size merges: 944 (69 prose chunks above 500)
Tables: 1,907
Punctuation-only: 0
Exact duplicate extras across corpus: 558
Estimated raw vector storage: 37.3 MiB
```
