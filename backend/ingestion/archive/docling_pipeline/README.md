# Archived Docling ingestion

This directory preserves the previous Docling 2.119.0 SEC HTML converter,
hierarchical chunker, pipeline documentation, and tests for reference. It is not
imported, packaged, or collected by pytest.

The active pipeline was replaced because SEC filings encode sections in anchors,
CSS, and layout tables rather than ordinary HTML headings. Docling consequently
produced many tiny, unlabelled, or presentation-only chunks.

Generated files were moved to `data/archive/docling_documents/`. They remain
gitignored and are not used by the active ingestion commands.
