"""Load converted SEC filings into the Supabase source_documents table."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict, cast

from postgrest import ReturnMethod

if TYPE_CHECKING:
    from supabase import AsyncClient


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "downloads" / "manifest.json"
MARKDOWN_DIR = REPOSITORY_ROOT / "data" / "markdown"

COMPANY_NAMES = {
    "AAPL": "Apple Inc.",
    "AMZN": "Amazon.com, Inc.",
    "BSP": "Bending Spoons S.p.A.",
    "GOOGL": "Alphabet Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
}

logger = logging.getLogger(__name__)


class SourceDocumentRow(TypedDict):
    company: str
    ticker: str
    filing_type: str
    filing_date: str
    report_date: str
    accession_number: str
    sec_url: str
    normalized_markdown: str
    extraction_metadata: dict[str, object]
    content_checksum: str
    updated_at: str


def load_source_document_rows(
    manifest_path: Path = MANIFEST_PATH,
    markdown_dir: Path = MARKDOWN_DIR,
    *,
    ingested_at: datetime | None = None,
) -> list[SourceDocumentRow]:
    manifest_value: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest_value, dict):
        raise TypeError("Download manifest must contain a JSON object")
    manifest = cast(dict[str, object], manifest_value)

    generated_at = _required_string(manifest, "generated_at_utc")
    filings = manifest.get("filings")
    if not isinstance(filings, list):
        raise TypeError("Download manifest field 'filings' must be a list")

    ingestion_time = (ingested_at or datetime.now(UTC)).isoformat()
    rows = []
    expected_markdown_paths = set()

    for index, filing_value in enumerate(filings):
        if not isinstance(filing_value, dict):
            raise TypeError(f"Manifest filing at index {index} must be an object")
        filing = cast(dict[str, object], filing_value)
        row, markdown_path = _build_source_document_row(
            filing,
            generated_at=generated_at,
            ingestion_time=ingestion_time,
            markdown_dir=markdown_dir,
        )
        rows.append(row)
        expected_markdown_paths.add(markdown_path)

    actual_markdown_paths = set(markdown_dir.rglob("*.md"))
    unexpected_paths = sorted(actual_markdown_paths - expected_markdown_paths)
    if unexpected_paths:
        relative_paths = ", ".join(
            str(path.relative_to(markdown_dir)) for path in unexpected_paths
        )
        raise ValueError(f"Markdown files missing from the manifest: {relative_paths}")

    _require_unique(rows, "accession_number")
    _require_unique(rows, "content_checksum")
    return rows


def _build_source_document_row(
    filing: dict[str, object],
    *,
    generated_at: str,
    ingestion_time: str,
    markdown_dir: Path,
) -> tuple[SourceDocumentRow, Path]:
    ticker = _required_string(filing, "ticker")
    try:
        company = COMPANY_NAMES[ticker]
    except KeyError:
        raise ValueError(f"No company name configured for ticker {ticker!r}") from None

    local_path = Path(_required_string(filing, "local_path"))
    if local_path.is_absolute() or ".." in local_path.parts:
        raise ValueError(f"Manifest local_path must be relative: {local_path}")
    if local_path.suffix.lower() not in {".htm", ".html"}:
        raise ValueError(f"Manifest local_path is not an HTML file: {local_path}")

    markdown_relative_path = local_path.with_suffix(".md")
    markdown_path = markdown_dir / markdown_relative_path
    markdown_bytes = markdown_path.read_bytes()
    markdown = markdown_bytes.decode("utf-8")
    if not markdown.strip():
        raise ValueError(f"Markdown file is empty: {markdown_path}")

    filing_date = _iso_date(_required_string(filing, "filing_date"), "filing_date")
    report_date_value = filing.get("report_date")
    if report_date_value == "":
        report_date = filing_date
        report_date_source = "filing_date_fallback"
    elif isinstance(report_date_value, str):
        report_date = _iso_date(report_date_value, "report_date")
        report_date_source = "manifest"
    else:
        raise ValueError("Manifest field 'report_date' must be a string")

    row: SourceDocumentRow = {
        "company": company,
        "ticker": ticker,
        "filing_type": _required_string(filing, "form"),
        "filing_date": filing_date,
        "report_date": report_date,
        "accession_number": _required_string(filing, "accession_number"),
        "sec_url": _required_string(filing, "source_url"),
        "normalized_markdown": markdown,
        "extraction_metadata": {
            "cik": _required_string(filing, "cik"),
            "primary_document": _required_string(filing, "primary_document"),
            "source_format": local_path.suffix.removeprefix(".").lower(),
            "source_local_path": local_path.as_posix(),
            "markdown_local_path": markdown_relative_path.as_posix(),
            "markdown_bytes": len(markdown_bytes),
            "markdown_characters": len(markdown),
            "converter": "docling",
            "converter_version": "2.119.0",
            "manifest_generated_at_utc": generated_at,
            "report_date_source": report_date_source,
        },
        "content_checksum": hashlib.sha256(markdown_bytes).hexdigest(),
        "updated_at": ingestion_time,
    }
    return row, markdown_path


async def upsert_source_documents(
    client: AsyncClient,
    rows: list[SourceDocumentRow],
) -> None:
    for index, row in enumerate(rows, start=1):
        await (
            client.table("source_documents")
            .upsert(
                row,
                on_conflict="accession_number",
                returning=ReturnMethod.minimal,
            )
            .execute()
        )
        logger.info(
            "[%d/%d] Upserted %s %s (%s)",
            index,
            len(rows),
            row["ticker"],
            row["filing_type"],
            row["accession_number"],
        )


async def ingest_source_documents(rows: list[SourceDocumentRow]) -> None:
    from app.config import settings
    from app.database.supabase import create_admin_supabase_client

    client = await create_admin_supabase_client(settings)
    await upsert_source_documents(client, rows)


def _required_string(data: dict[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Manifest field {field!r} must be a non-empty string")
    return value


def _iso_date(value: str, field: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(
            f"Manifest field {field!r} must use YYYY-MM-DD: {value!r}"
        ) from None


def _require_unique(
    rows: list[SourceDocumentRow],
    field: Literal["accession_number", "content_checksum"],
) -> None:
    values = [row[field] for row in rows]
    duplicates = sorted(value for value in set(values) if values.count(value) > 1)
    if duplicates:
        raise ValueError(f"Duplicate {field} values: {', '.join(duplicates)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upsert converted SEC filings into Supabase source_documents."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize local documents without writing to Supabase.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    rows = load_source_document_rows()
    markdown_bytes = sum(
        int(row["extraction_metadata"]["markdown_bytes"]) for row in rows
    )
    logger.info(
        "Validated %d source documents (%.1f MiB of Markdown)",
        len(rows),
        markdown_bytes / (1024 * 1024),
    )

    if args.dry_run:
        logger.info("Dry run complete; Supabase was not modified")
        return

    asyncio.run(ingest_source_documents(rows))
    logger.info("Ingestion complete; %d source documents upserted", len(rows))


if __name__ == "__main__":
    main()
