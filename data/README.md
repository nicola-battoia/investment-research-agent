# Data

Local data artifacts for development live here.

- `downloads/` holds raw source files fetched from SEC EDGAR, grouped by year.
- `markdown/` holds Docling Markdown exports with the same year structure.
- `docling_documents/` holds native `DoclingDocument` JSON exports with the same
  year structure.
- Corpus payloads and generated documents are gitignored because they can get large.
- Fetch a sample corpus with `uv run data/download.py`.
- Convert all downloaded HTML filings with `uv run data/convert_documents.py`.
