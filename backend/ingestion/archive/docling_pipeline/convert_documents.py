# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "docling==2.119.0",
# ]
# ///
from __future__ import annotations

import logging
from pathlib import Path

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.document_converter import DocumentConverter

DATA_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = DATA_DIR / "downloads"
MARKDOWN_DIR = DATA_DIR / "markdown"
DOCLING_DOCUMENTS_DIR = DATA_DIR / "docling_documents"
HTML_SUFFIXES = {".htm", ".html"}

logger = logging.getLogger(__name__)


def find_html_files() -> list[Path]:
    return sorted(
        path
        for path in DOWNLOADS_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in HTML_SUFFIXES
    )


def output_paths(source_path: Path) -> tuple[Path, Path]:
    relative_path = source_path.relative_to(DOWNLOADS_DIR)
    markdown_path = (MARKDOWN_DIR / relative_path).with_suffix(".md")
    docling_path = (DOCLING_DOCUMENTS_DIR / relative_path).with_suffix(".json")
    return markdown_path, docling_path


def convert_file(source_path: Path, converter: DocumentConverter) -> ConversionStatus:
    result = converter.convert(source_path, raises_on_error=False)
    if result.status not in {
        ConversionStatus.SUCCESS,
        ConversionStatus.PARTIAL_SUCCESS,
    }:
        errors = "; ".join(error.error_message for error in result.errors)
        raise RuntimeError(errors or f"Docling returned status {result.status.value}")

    markdown_path, docling_path = output_paths(source_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    docling_path.parent.mkdir(parents=True, exist_ok=True)
    result.document.save_as_markdown(markdown_path)
    result.document.save_as_json(docling_path)

    for error in result.errors:
        logger.warning("%s: %s", source_path, error.error_message)
    return result.status


def convert_documents() -> tuple[int, int, int]:
    if not DOWNLOADS_DIR.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {DOWNLOADS_DIR}")

    source_paths = find_html_files()
    if not source_paths:
        raise FileNotFoundError(f"No HTML files found under: {DOWNLOADS_DIR}")

    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    DOCLING_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    converter = DocumentConverter(allowed_formats=[InputFormat.HTML])

    success_count = 0
    partial_count = 0
    failure_count = 0

    for index, source_path in enumerate(source_paths, start=1):
        relative_path = source_path.relative_to(DOWNLOADS_DIR)
        logger.info("[%d/%d] Converting %s", index, len(source_paths), relative_path)
        try:
            status = convert_file(source_path, converter)
        except Exception:
            failure_count += 1
            logger.exception("Failed to convert %s", relative_path)
            continue

        if status == ConversionStatus.PARTIAL_SUCCESS:
            partial_count += 1
        else:
            success_count += 1

    return success_count, partial_count, failure_count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    success_count, partial_count, failure_count = convert_documents()
    logger.info(
        "Finished: %d succeeded, %d partially succeeded, %d failed",
        success_count,
        partial_count,
        failure_count,
    )
    logger.info("Markdown output: %s", MARKDOWN_DIR)
    logger.info("DoclingDocument JSON output: %s", DOCLING_DOCUMENTS_DIR)

    if failure_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
