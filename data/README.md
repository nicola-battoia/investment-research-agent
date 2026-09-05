# Local corpus and generated data

This directory contains the source downloader and ignored local corpus artifacts.
Payloads are not included in a fresh clone.

| Path | Purpose |
| --- | --- |
| `download.py` | SEC EDGAR downloader and corpus configuration |
| `downloads/` | Raw filings grouped by year, plus `manifest.json` |
| `markdown/` | Canonical Markdown rendered by the SEC parser |
| `parsed_documents/` | Parsed sections, blocks, table geometry, and Markdown offsets |
| `ingestion_runs/sec_sections_v2/` | Per-document chunk and compressed embedding checkpoints |
| `archive/docling_documents/` | Legacy outputs retained for comparison |

## Existing local snapshot

The manifest generated on **2026-08-15** contains 27 filings: 25 annual reports
for AAPL, AMZN, GOOGL, MSFT, and NVDA covering fiscal 2021–2025, plus BSP F-1 and
424B4 filings. The September 5 audit found 6,373 current chunks. This describes the
local checkout; it is not verification of the hosted database.

## Before running the downloader

Review [`download.py`](download.py) first:

- `CLEAR_OUTPUT_DIR=True` clears the existing download directory before fetching.
  A failed run can leave an incomplete replacement.
- Configure an appropriate SEC `USER_AGENT` rather than using the placeholder.
- Target years are calculated from the current UTC year. Rerunning in a later year
  does not reproduce the frozen pilot automatically.
- Downloader choices include forms beyond the active parser's support. The
  parser accepts `10-K`, `F-1`, and `424B4`; downloader support for another form
  does not make it ingestible.
- The BSP prospectuses extend the client brief's five-company pilot. Keep or
  remove them only after deciding the intended corpus.

To fetch after reviewing those settings, run from the repository root:

```bash
uv run data/download.py
```

Then follow the [ingestion guide](../backend/ingestion/README.md). Its parse and
checkpoint stages can use local files without contacting SEC EDGAR; embeddings
call Azure and uploads write Supabase. Do not redownload just to run a local
inspection or rebuild the frontend.
