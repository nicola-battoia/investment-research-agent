# Archived ingestion material

Nothing in this directory is imported or executed by the active ingestion
pipeline. These files are retained only to explain earlier experiments and make
past results reproducible when practical.

- `docling_pipeline/` contains the replaced Docling converter, chunker, tests, and
  design notes.
- `direct_pipeline/` contains the replaced in-memory chunk → embed → Supabase
  runner. The active pipeline saves chunks and embeddings locally first.
- `experiments/` contains one-off inspection utilities superseded by the durable
  checkpoint format.
- `metrics/` contains dated historical measurements. Current metrics are generated
  with `uv run python -m ingestion.helpers`.

Archived Python files are reference-only. Their imports, dependencies, and command
examples are not maintained.
