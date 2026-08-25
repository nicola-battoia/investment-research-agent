from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from postgrest import ReturnMethod

from ingestion.ingest_documents import (
    load_source_document_rows,
    upsert_source_documents,
)
from ingestion.sec_parser import ParsedBlock, ParsedDocument, ParsedSection

INGESTED_AT = datetime(2026, 8, 19, 10, 30, tzinfo=UTC)


def test_load_source_document_rows_builds_every_database_field(tmp_path) -> None:
    markdown_dir = tmp_path / "markdown"
    markdown_path = markdown_dir / "2024" / "aapl.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text("# Apple\n\nAnnual report.\n", encoding="utf-8")
    parsed_dir = tmp_path / "parsed"
    _write_parsed(parsed_dir, "# Apple\n\nAnnual report.\n")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    rows = load_source_document_rows(
        manifest_path,
        markdown_dir,
        parsed_dir,
        ingested_at=INGESTED_AT,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row == {
        "company": "Apple Inc.",
        "ticker": "AAPL",
        "filing_type": "10-K",
        "filing_date": "2024-11-01",
        "report_date": "2024-09-28",
        "accession_number": "0000320193-24-000123",
        "sec_url": "https://www.sec.gov/example.htm",
        "normalized_markdown": "# Apple\n\nAnnual report.\n",
        "extraction_metadata": {
            "cik": "0000320193",
            "primary_document": "aapl-20240928.htm",
            "source_format": "htm",
            "source_local_path": "2024/aapl.htm",
            "markdown_local_path": "2024/aapl.md",
            "parsed_local_path": "2024/aapl.json",
            "markdown_bytes": 24,
            "markdown_characters": 24,
            "parsed_bytes": (parsed_dir / "2024" / "aapl.json").stat().st_size,
            "parser": "sec_html",
            "parser_version": "sec_html_v1",
            "source_sha256": "0" * 64,
            "parse_audit": {},
            "manifest_generated_at_utc": "2026-08-15T10:53:44+00:00",
            "report_date_source": "manifest",
        },
        "content_checksum": hashlib.sha256(b"# Apple\n\nAnnual report.\n").hexdigest(),
        "updated_at": "2026-08-19T10:30:00+00:00",
    }


def test_missing_report_date_uses_filing_date_and_records_fallback(tmp_path) -> None:
    manifest = _manifest()
    manifest["filings"][0]["report_date"] = ""
    markdown_dir = tmp_path / "markdown"
    markdown_path = markdown_dir / "2024" / "aapl.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text("Filing text", encoding="utf-8")
    parsed_dir = tmp_path / "parsed"
    _write_parsed(parsed_dir, "Filing text")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    row = load_source_document_rows(manifest_path, markdown_dir, parsed_dir)[0]

    assert row["report_date"] == "2024-11-01"
    assert row["extraction_metadata"]["report_date_source"] == "filing_date_fallback"


def test_load_source_document_rows_requires_every_markdown_file(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        load_source_document_rows(
            manifest_path,
            tmp_path / "markdown",
            tmp_path / "parsed",
        )


def test_upsert_source_documents_uses_accession_number_conflict() -> None:
    row = MagicMock()
    execute = AsyncMock(return_value=SimpleNamespace(data=[]))
    table = MagicMock()
    table.upsert.return_value = SimpleNamespace(execute=execute)
    client = MagicMock()
    client.table.return_value = table

    asyncio.run(upsert_source_documents(client, [row]))

    client.table.assert_called_once_with("source_documents")
    table.upsert.assert_called_once_with(
        row,
        on_conflict="accession_number",
        returning=ReturnMethod.minimal,
    )
    execute.assert_awaited_once_with()


def _manifest() -> dict[str, object]:
    return {
        "generated_at_utc": "2026-08-15T10:53:44+00:00",
        "filings": [
            {
                "ticker": "AAPL",
                "cik": "0000320193",
                "form": "10-K",
                "filing_date": "2024-11-01",
                "report_date": "2024-09-28",
                "accession_number": "0000320193-24-000123",
                "primary_document": "aapl-20240928.htm",
                "source_url": "https://www.sec.gov/example.htm",
                "local_path": "2024/aapl.htm",
            }
        ],
    }


def _write_parsed(parsed_dir, markdown: str) -> None:
    parsed_path = parsed_dir / "2024" / "aapl.json"
    parsed_path.parent.mkdir(parents=True)
    document = ParsedDocument(
        form="10-K",
        source_path="2024/aapl.htm",
        source_sha256="0" * 64,
        markdown_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        audit={},
        sections=[
            ParsedSection(
                key="front_matter",
                title="Front Matter",
                detection_method="default",
                blocks=[
                    ParsedBlock(
                        id="b00001",
                        kind="paragraph",
                        text="Annual report.",
                        html_locator="/html/body/div",
                    )
                ],
            )
        ],
    )
    parsed_path.write_text(json.dumps(document.to_dict()), encoding="utf-8")
