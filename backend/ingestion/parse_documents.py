"""Parse downloaded SEC HTML into clean Markdown and structured JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ingestion.sec_parser import ParsedDocument, parse_sec_filing, render_markdown

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS_DIR = REPOSITORY_ROOT / "data" / "downloads"
MANIFEST_PATH = DOWNLOADS_DIR / "manifest.json"
MARKDOWN_DIR = REPOSITORY_ROOT / "data" / "markdown"
PARSED_DOCUMENTS_DIR = REPOSITORY_ROOT / "data" / "parsed_documents"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParseResult:
    accession_number: str
    markdown_path: Path
    parsed_path: Path
    section_count: int
    block_count: int
    table_count: int
    markdown_tokens_source_characters: int


def parse_manifest_documents(
    manifest_path: Path = MANIFEST_PATH,
    downloads_dir: Path = DOWNLOADS_DIR,
    markdown_dir: Path = MARKDOWN_DIR,
    parsed_documents_dir: Path = PARSED_DOCUMENTS_DIR,
    *,
    accession_number: str | None = None,
    write: bool = True,
) -> list[ParseResult]:
    manifest_value: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest_value, dict):
        raise TypeError("Download manifest must contain a JSON object")
    filings = manifest_value.get("filings")
    if not isinstance(filings, list):
        raise TypeError("Download manifest field 'filings' must be a list")

    selected = []
    for index, filing_value in enumerate(filings):
        if not isinstance(filing_value, dict):
            raise TypeError(f"Manifest filing at index {index} must be an object")
        filing = cast(dict[str, object], filing_value)
        if (
            accession_number is None
            or _required_string(filing, "accession_number") == accession_number
        ):
            selected.append(filing)
    if accession_number is not None and not selected:
        raise ValueError(f"Accession number is not in the manifest: {accession_number}")

    results = []
    for index, filing in enumerate(selected, start=1):
        local_path = _relative_html_path(_required_string(filing, "local_path"))
        source_path = downloads_dir / local_path
        source = source_path.read_bytes()
        document = parse_sec_filing(
            source,
            form=_required_string(filing, "form"),
            source_path=local_path.as_posix(),
        )
        _validate_required_sections(document)
        markdown = render_markdown(document)
        _add_artifact_metadata(document, source, markdown)

        markdown_path = (markdown_dir / local_path).with_suffix(".md")
        parsed_path = (parsed_documents_dir / local_path).with_suffix(".json")
        if write:
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            parsed_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(markdown, encoding="utf-8")
            parsed_path.write_text(
                json.dumps(document.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        block_count = sum(len(section.blocks) for section in document.sections)
        table_count = sum(
            block.kind == "table"
            for section in document.sections
            for block in section.blocks
        )
        result = ParseResult(
            accession_number=_required_string(filing, "accession_number"),
            markdown_path=markdown_path,
            parsed_path=parsed_path,
            section_count=len(document.sections),
            block_count=block_count,
            table_count=table_count,
            markdown_tokens_source_characters=len(markdown),
        )
        results.append(result)
        logger.info(
            "[%d/%d] Parsed %s: %d sections, %d blocks, %d tables",
            index,
            len(selected),
            result.accession_number,
            result.section_count,
            result.block_count,
            result.table_count,
        )
    return results


def _add_artifact_metadata(
    document: ParsedDocument,
    source: bytes,
    markdown: str,
) -> None:
    document.audit["source_bytes"] = len(source)
    document.audit["markdown_characters"] = len(markdown)
    document.source_sha256 = hashlib.sha256(source).hexdigest()
    document.markdown_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _validate_required_sections(document: ParsedDocument) -> None:
    if document.form == "10-K":
        required = {"item_1", "item_1a", "item_7", "item_8"}
    else:
        required = {"risk_factors", "business", "mda", "financial_statements"}
        if document.form == "424B4":
            required.add("underwriting")
    actual = {section.key for section in document.sections}
    missing = sorted(required - actual)
    if missing:
        raise ValueError(
            f"Parsed {document.form} is missing required sections: {', '.join(missing)}"
        )


def _relative_html_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Manifest local_path must be relative: {path}")
    if path.suffix.lower() not in {".htm", ".html"}:
        raise ValueError(f"Manifest local_path is not an HTML file: {path}")
    return path


def _required_string(data: dict[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Manifest field {field!r} must be a non-empty string")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse downloaded SEC HTML into Markdown and structured JSON."
    )
    parser.add_argument(
        "--accession-number",
        help="Parse one filing instead of every filing in the manifest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing generated files.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    results = parse_manifest_documents(
        accession_number=args.accession_number,
        write=not args.dry_run,
    )
    logger.info(
        "%s %d documents: %d sections, %d blocks, %d tables",
        "Validated" if args.dry_run else "Wrote",
        len(results),
        sum(result.section_count for result in results),
        sum(result.block_count for result in results),
        sum(result.table_count for result in results),
    )


if __name__ == "__main__":
    main()
