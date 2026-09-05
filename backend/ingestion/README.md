# SEC filing ingestion

This pipeline turns downloaded SEC filing HTML into clean, retrieval-ready chunks
in Supabase. It uses a focused SEC parser because filings express structure through
anchors, CSS, and layout tables rather than reliable `<h1>`–`<h6>` elements.

```text
data/downloads/<year>/*.htm
    → SEC HTML parser
    → data/markdown/*.md + data/parsed_documents/*.json
    → section-aware chunks (100-token minimum, normally at most 500)
    → local chunks.jsonl + readable chunks.md
    → local compressed OpenAI embedding checkpoints
    → source_documents + document_chunks in Supabase
```

The active parser supports `10-K`, `F-1`, and `424B4`. The previous Docling
implementation is preserved under [`archive/docling_pipeline/`](archive/docling_pipeline/)
but is not imported or executed.

## Start here

Run commands from `backend/` unless using the repository-root shell scripts.
Install the locked environment and configure `.env` first. Existing local
downloads can be reused; fetching is not part of the numbered pipeline.

| Stage | External calls / writes |
| --- | --- |
| Parse and prepare | Local files; no model or database calls |
| Embed | Paid Azure embedding calls; local checkpoint writes |
| Upload | Supabase writes using the service-role key; no model calls |
| Verify | Supabase reads and local checkpoint checks |

For the usual path use `01_prepare_local.sh`, review its local output, then
`02_create_embeddings.sh`, `03_upload_supabase.sh`, and
`04_verify_supabase.sh`. Their commands appear in section 9. Source-document
upsert is explained early below but can wait until the upload stage.

Current limitations: printed page numbers are unavailable; database completeness
checks do not prove vector/model equivalence; the retrieval evaluation's labels
need remapping. These are tracked in the [audit](../../docs/repository-audit.md).
Embedding batches are bounded by tokens/items, not a shared tokens-per-minute
scheduler. Check the actual Azure quota before regenerating a corpus.

## Active files

The active package stays flat so every stage remains easy to run with
`python -m ingestion.<module>`. Files are grouped by responsibility here instead of
being hidden behind extra package layers:

| Responsibility | Files |
| --- | --- |
| Parse SEC HTML | `sec_parser.py`, `parse_documents.py` |
| Build chunks | `chunk_documents.py` |
| Save and validate local work | `checkpoints.py`, `prepare_checkpoints.py` |
| Create embeddings | `create_embeddings.py`, `embed_checkpoints.py` |
| Build and upload database rows | `ingest_documents.py`, `supabase_chunks.py`, `upload_checkpoints.py` |
| Verify and maintain | `verify_ingestion.py`, `helpers.py`, `reset_ingestion.py` |
| Operator commands | `scripts/` |

Historical code lives under [`archive/`](archive/) and is never used by active
commands. Dated measurements are in [`metrics/`](metrics/).

## 1. Downloaded inputs

[`data/download.py`](../../data/download.py) downloads raw filing HTML and writes
`data/downloads/manifest.json`. The manifest provides the form, accession number,
dates, SEC URL, and local path used by every later stage.

Raw HTML remains the source of truth. Parsing does not call SEC EDGAR or any other
network service. Read [the downloader notes](../../data/README.md#before-running-the-downloader)
before fetching: its default clears existing downloads, years roll with the
calendar, and some downloadable forms are not supported by this parser.

## 2. Parse SEC HTML

Run from `backend/`:

```bash
uv run python -m ingestion.parse_documents

# Parse and validate one filing without writing artifacts.
uv run python -m ingestion.parse_documents \
  --accession-number 0000320193-24-000123 \
  --dry-run
```

[`parse_documents.py`](parse_documents.py) reads the manifest and calls
[`parse_sec_filing()`](sec_parser.py) for each HTML file:

```python
document = parse_sec_filing(
    source_path.read_bytes(),
    form=filing["form"],
    source_path=local_path.as_posix(),
)
markdown = render_markdown(document)
```

It writes two files with matching relative paths:

```text
data/downloads/2024/aapl_....htm
    → data/markdown/2024/aapl_....md
    → data/parsed_documents/2024/aapl_....json
```

The Markdown is the canonical readable document stored in
`source_documents.normalized_markdown`. The JSON preserves sections, blocks, table
geometry, parser metadata, and exact block offsets into that Markdown.

### HTML cleanup

[`sec_parser.py`](sec_parser.py) uses `lxml`'s tolerant HTML parser. It removes:

- scripts, styles, comments, hidden nodes, `ix:header`, and `ix:exclude`;
- table-of-contents/navigation tables;
- empty or punctuation-only nodes and tables;
- repeated short page furniture and filing chrome;
- exact adjacent duplicates.

Visible inline-XBRL values remain ordinary visible text because elements such as
`ix:nonnumeric` are not removed.

### Section detection

For 10-K documents, the parser recognizes canonical `PART` and `ITEM` labels. For
prospectuses, it recognizes titles such as Risk Factors, Business, MD&A, and
Underwriting.

Linked table-of-contents targets are used when present. Otherwise, short canonical
body titles are used:

```python
heading = candidate.anchor_heading
if heading is None:
    heading = _section_heading(form, candidate.text)
```

The corpus parser rejects a filing when critical sections are missing. A 10-K must
contain Items 1, 1A, 7, and 8. F-1 and 424B4 filings must contain Risk Factors,
Business, MD&A, and Financial Statements; 424B4 must also contain Underwriting.

### Paragraphs, lists, and tables

Content is emitted in DOM order as paragraphs, list items, subheadings, or tables.
Tables are classified before being retained:

- empty and navigation tables are dropped;
- bullet-layout tables become list items;
- simple text-layout tables become paragraphs;
- financial/data tables retain their rows, columns, spans, headers, and empty cells.

Ambiguous multi-column tables are retained so potentially material financial data
is not silently discarded.

### Markdown offsets

Markdown is rendered deterministically. Each block records its exact range:

```python
block.markdown_start = current_length
append(rendered_block)
block.markdown_end = current_length
```

Chunk citations can therefore refer back to the canonical Markdown rather than to
positions in the original layout-heavy HTML.

## 3. Store source documents

Validate or write source documents with:

```bash
uv run python -m ingestion.ingest_documents --dry-run
uv run python -m ingestion.ingest_documents
```

[`ingest_documents.py`](ingest_documents.py) loads the Markdown and matching parsed
JSON, validates their form, path, parser version, and checksum, then builds one row
per filing:

```python
row = {
    "accession_number": accession_number,
    "normalized_markdown": markdown,
    "extraction_metadata": {
        "parser": "sec_html",
        "parser_version": "sec_html_v1",
        "parsed_local_path": parsed_relative_path.as_posix(),
        "parse_audit": parsed.audit,
    },
    "content_checksum": sha256(markdown_bytes).hexdigest(),
}
```

Rows are upserted by accession number. Later checkpoint/upload checks compare the
source checksum with the chunk version. Source upserts themselves are separate
writes, so do not replace canonical Markdown ahead of a planned chunk migration:
old chunks/citations may still refer to the previous document.

## 4. Create meaningful chunks

[`chunk_documents.py`](chunk_documents.py) reads the structured JSON rather than
splitting Markdown by characters.

The important limits are:

```python
MIN_TARGET_TOKENS = 150
MIN_CHUNK_TOKENS = 100
MAX_CHUNK_TOKENS = 500
MAX_MERGED_CHUNK_TOKENS = 600
MAX_EMBEDDING_INPUT_TOKENS = 8_192
```

### Prose chunking

Within each section, adjacent paragraphs and list items are accumulated until the
next item would make the complete contextualized text exceed 500 tokens:

```python
candidate_text = section_heading + "\n\n" + accumulated_body
if current_parts and token_counter.count_tokens(candidate_text) > 500:
    emit_current_chunk()
```

The section and active subsection headings count toward the 500-token limit. A
chunk consequently looks like:

```text
Item 1A. Risk Factors
Competition

The markets for the company’s products are highly competitive...
```

Additional rules:

- chunks normally stay inside one section;
- headings attach to the content after them and are never emitted alone;
- a large paragraph splits at sentence boundaries, then at whitespace if needed;
- there is no overlap, so body text and embedding storage are not duplicated;
- after normal chunking, any chunk below 100 tokens is merged with the following
  chunk, continuing forward until it reaches 100 tokens;
- if a forward merge is not possible, the short chunk is merged backward;
- these minimum-size merges may reach 600 tokens, so a 90-token section beside a
  490-token section does not remain as a separate noisy vector;
- when a merge crosses a section boundary, both headings stay in the text and
  `section_keys` / `section_titles` preserve the full context in metadata.

### Table exception

Real tables remain complete because row fragments without headers lose meaning.
They may exceed the 500-token prose target, up to the 8,192-token embedding input
limit. A short table introduction is attached to the table rather than becoming a
tiny standalone chunk.

The embedded table text is compact:

```text
Item 8. Financial Statements and Supplementary Data

Revenue consisted of the following:

[TABLE]
Year | Revenue
2025 | $100
```

`display_table` separately retains full cell geometry and offsets for rendering and
highlighting. A table above 8,192 tokens stops ingestion with a clear error instead
of being silently truncated. Small tables are merged with adjacent prose when this
preserves one table per chunk. Two complete tables are never merged because one
database row has one `display_table` geometry object; an otherwise unmergeable table
below 100 tokens remains atomic and receives
`minimum_token_exception: "atomic_table"`. This narrow exception preserves real
financial tables rather than corrupting their citation geometry.

Every prepared chunk retains the existing ingestion contract:

```python
@dataclass(frozen=True)
class PreparedChunk:
    chunk_index: int
    text: str
    token_count: int
    page_number: int | None
    section_title: str | None
    source_start: int | None
    source_end: int | None
    metadata: dict[str, object]
    display_table: StoredDisplayTable | None = None
```

The current parser/chunker does not populate `page_number`. Citations use section
titles and offsets into canonical Markdown; these are not printed PDF page numbers.

## 5. Save local chunk checkpoints

After parsing and dry-run validation, materialize every chunk locally:

```bash
uv run --locked python -m ingestion.prepare_checkpoints
```

Each filing receives a versioned directory:

```text
data/ingestion_runs/sec_sections_v2/<accession>/
├── checkpoint.json
├── chunks.jsonl
└── chunks.md
```

- `chunks.jsonl` contains every field produced by `PreparedChunk`, including text,
  token count, section/source offsets, metadata, and complete table geometry.
- `chunks.md` is the same chunk list formatted for human inspection.
- `checkpoint.json` binds those files to the accession number, source checksum,
  parser and chunker versions, embedding model and dimensions, counts, and the
  SHA-256 checksum of `chunks.jsonl`.

The complete document directory is written to a temporary sibling and renamed only
after validation. Existing matching checkpoints are validated and reused; a
mismatch stops the run instead of silently replacing paid work.

## 6. Save resumable embeddings

Create embeddings from the local chunk checkpoints:

```bash
uv run --locked python -m ingestion.embed_checkpoints
```

This is the paid stage. It works one filing at a time. After OpenAI returns every
vector for one filing, the vectors and their own checkpoint are written atomically:

```text
data/ingestion_runs/sec_sections_v2/<accession>/embeddings/
├── checkpoint.json
└── embeddings.jsonl.gz
```

The embedding checkpoint records the exact chunk-file checksum, model, dimensions,
vector count, API token usage, and vector-file checksum. On restart, valid completed
filings are loaded and skipped. A failed current filing is the only one that may
need another OpenAI call.

To create or validate one filing only:

```bash
uv run --locked python -m ingestion.embed_checkpoints \
  --accession-number 0000320193-24-000123
```

## 7. Upload from checkpoints

First upsert the source documents in the manifest (27 in the recorded corpus), then upload
chunks without calling OpenAI:

```bash
uv run --locked python -m ingestion.ingest_documents
uv run --locked python -m ingestion.upload_checkpoints
```

The uploader resolves each `source_documents.id` by accession number and calls
[`build_document_chunk_rows()`](supabase_chunks.py). Every database field is
therefore populated through the same tested path:

```python
{
    "document_id": resolved_source_document_id,
    "chunk_index": chunk.chunk_index,
    "text": chunk.text,
    "token_count": chunk.token_count,
    "page_number": chunk.page_number,
    "section_title": chunk.section_title,
    "source_start": chunk.source_start,
    "source_end": chunk.source_end,
    "metadata": filing_and_chunk_metadata,
    "display_table": complete_table_geometry,
    "embedding": checkpoint_vector,
    "updated_at": upload_timestamp,
}
```

Uploads are idempotent by `(document_id, chunk_index)`. Before skipping an existing
filing, the uploader checks parser/chunker/source-checksum metadata on one sampled
chunk plus the row count and final index. A partial upload is completed from local
vectors without paying for new embeddings. The skip check does not compare every
stored row, vector, or embedding-model identity; see the
[audit](../../docs/repository-audit.md#f06-upload-completeness-does-not-prove-embedding-identity).

## 8. Verify Supabase independently

After upload, compare Supabase against every local checkpoint:

```bash
uv run --locked python -m ingestion.verify_ingestion
```

The verifier checks the exact accession set, source checksums/parser version, chunk
counts and contiguous indexes, table counts, and parser/chunker/checksum metadata on
every uploaded chunk. It does not compare stored text/vectors byte-for-byte with
local checkpoints or validate uploaded embedding-model identity. Treat it as a
structural consistency check, not complete corpus equivalence.

## 9. Bash scripts

Run individual stages from the repository root:

```bash
backend/ingestion/scripts/01_prepare_local.sh
backend/ingestion/scripts/02_create_embeddings.sh
backend/ingestion/scripts/03_upload_supabase.sh
backend/ingestion/scripts/04_verify_supabase.sh
```

Embedding and upload scripts accept an optional accession number. In the upload
script this narrows only the **chunk upload**: it still upserts all source documents
first. Matching local checkpoints and uploads are reused under the checks above.

The guarded all-in-one command is:

```bash
backend/ingestion/scripts/run_pipeline.sh run-paid-embeddings-and-upload
```

It intentionally requires the explicit argument because it calls the paid OpenAI
API and writes to Supabase. It does not call the full reset. The chunk upsert helper
can delete trailing rows beyond the new final index during an upload; the command
is not a blanket guarantee that no rows are deleted.

## 10. Inspect corpus metrics

Run:

```bash
uv run python -m ingestion.helpers
```

The report includes document tokens, chunk count, total tokens, min/max/mean/median,
small-chunk counts, tables, punctuation-only chunks, exact duplicates, and estimated
raw vector storage.

The recorded 27-file ingestion run produced:

- 6,373 chunks instead of 40,920;
- 338-token median and 337-token mean;
- zero prose chunks below 100 tokens;
- 40 chunks below 100 tokens, all explicit atomic-table exceptions;
- zero punctuation-only chunks;
- 1,907 complete tables;
- about 37.3 MiB of raw 1,536-dimensional float vectors.

The dated first-run report is preserved under
[`metrics/`](metrics/). Retrieval evaluation expectations must be
updated for the new chunk indexes before the frozen evaluation is run again.

## 11. One-time reset

Changing chunk boundaries in place would make old chat citations point at different
text. Inspect the destructive reset first:

```bash
uv run python -m ingestion.reset_ingestion
```

This reports all chat threads, messages, citations, chunks, and the source documents
that will remain. Execute it only when the complete chat/chunk deletion is intended:

```bash
uv run python -m ingestion.reset_ingestion \
  --confirm delete-all-chats-and-chunks
```

In one transaction, the command deletes all chat threads (cascading to messages and
citations) and then all chunks. It does not delete `source_documents`.

The reset is not part of the Bash pipeline and must never run automatically. After
ingestion, update the retrieval evaluation’s expected chunk indexes and run the
frozen retrieval evaluation before considering the cutover complete.
