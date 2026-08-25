from __future__ import annotations

import hashlib
import json

import pytest

from ingestion import checkpoints
from ingestion.checkpoints import (
    checkpoint_paths,
    load_document_chunks,
    load_document_embeddings,
    prepare_document_checkpoint,
    save_document_embeddings,
)
from ingestion.ingest_documents import SourceDocumentRow
from ingestion.sec_parser import (
    ParsedBlock,
    ParsedDocument,
    ParsedSection,
    render_markdown,
)


def test_chunk_and_embedding_checkpoints_round_trip_atomically(
    tmp_path,
    monkeypatch,
) -> None:
    document = ParsedDocument(
        form="10-K",
        source_path="2024/sample.htm",
        audit={},
        sections=[
            ParsedSection(
                key="item_1a",
                title="Item 1A. Risk Factors",
                detection_method="body_heading",
                blocks=[
                    ParsedBlock(
                        id="b00001",
                        kind="paragraph",
                        text=" ".join(f"risk{index}" for index in range(150)),
                        html_locator="/html/body/p",
                    )
                ],
            )
        ],
    )
    markdown = render_markdown(document)
    parsed_path = tmp_path / "data" / "parsed_documents" / "2024" / "sample.json"
    markdown_path = tmp_path / "data" / "markdown" / "2024" / "sample.md"
    parsed_path.parent.mkdir(parents=True)
    markdown_path.parent.mkdir(parents=True)
    parsed_path.write_text(json.dumps(document.to_dict()), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    monkeypatch.setattr(checkpoints, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        checkpoints,
        "document_paths",
        lambda _row: (parsed_path, markdown_path),
    )
    source_row = _source_row(markdown)
    checkpoint_root = tmp_path / "checkpoints"

    chunk_checkpoint, chunks, created = prepare_document_checkpoint(
        source_row,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
        checkpoint_root=checkpoint_root,
    )

    assert created is True
    assert chunk_checkpoint.chunk_count == len(chunks)
    assert checkpoint_paths(
        source_row["accession_number"], checkpoint_root
    ).chunks_markdown.is_file()

    repeated_checkpoint, repeated_chunks, repeated_created = (
        prepare_document_checkpoint(
            source_row,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=3,
            checkpoint_root=checkpoint_root,
        )
    )
    assert repeated_created is False
    assert repeated_checkpoint == chunk_checkpoint
    assert repeated_chunks == chunks

    vectors = [[0.1, 0.2, 0.3] for _chunk in chunks]
    embedding_checkpoint = save_document_embeddings(
        source_row,
        chunk_checkpoint,
        vectors,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
        embedding_input_tokens=chunk_checkpoint.chunk_token_count,
        embedding_request_count=1,
        checkpoint_root=checkpoint_root,
    )
    loaded_embedding_checkpoint, loaded_vectors = load_document_embeddings(
        source_row,
        chunk_checkpoint,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
        checkpoint_root=checkpoint_root,
    )

    assert loaded_embedding_checkpoint == embedding_checkpoint
    assert loaded_vectors == vectors
    assert not list(checkpoint_root.rglob("*.tmp"))


def test_chunk_checkpoint_rejects_file_changes(tmp_path, monkeypatch) -> None:
    document = ParsedDocument(
        form="10-K",
        source_path="2024/sample.htm",
        audit={},
        sections=[
            ParsedSection(
                key="item_1a",
                title="Item 1A. Risk Factors",
                detection_method="body_heading",
                blocks=[
                    ParsedBlock(
                        id="b00001",
                        kind="paragraph",
                        text=" ".join(f"risk{index}" for index in range(150)),
                        html_locator="/html/body/p",
                    )
                ],
            )
        ],
    )
    markdown = render_markdown(document)
    parsed_path = tmp_path / "data" / "parsed_documents" / "sample.json"
    markdown_path = tmp_path / "data" / "markdown" / "sample.md"
    parsed_path.parent.mkdir(parents=True)
    markdown_path.parent.mkdir(parents=True)
    parsed_path.write_text(json.dumps(document.to_dict()), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    monkeypatch.setattr(checkpoints, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        checkpoints,
        "document_paths",
        lambda _row: (parsed_path, markdown_path),
    )
    source_row = _source_row(markdown)
    checkpoint_root = tmp_path / "checkpoints"
    prepare_document_checkpoint(
        source_row,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
        checkpoint_root=checkpoint_root,
    )
    paths = checkpoint_paths(source_row["accession_number"], checkpoint_root)
    paths.chunks.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_document_chunks(
            source_row,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=3,
            checkpoint_root=checkpoint_root,
        )


def _source_row(markdown: str) -> SourceDocumentRow:
    return {
        "company": "Apple Inc.",
        "ticker": "AAPL",
        "filing_type": "10-K",
        "filing_date": "2024-11-01",
        "report_date": "2024-09-28",
        "accession_number": "0000320193-24-000123",
        "sec_url": "https://www.sec.gov/example.htm",
        "normalized_markdown": markdown,
        "extraction_metadata": {},
        "content_checksum": hashlib.sha256(markdown.encode()).hexdigest(),
        "updated_at": "2026-08-26T00:00:00+00:00",
    }
