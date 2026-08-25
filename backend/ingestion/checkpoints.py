"""Durable per-document checkpoints for chunks and embedding vectors."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from app.retrieval.display_tables import StoredDisplayTable
from ingestion.chunk_documents import (
    CHUNKER_VERSION,
    OpenAITokenCounter,
    PreparedChunk,
    TokenCounter,
    chunk_document,
    document_paths,
)
from ingestion.ingest_documents import SourceDocumentRow
from ingestion.sec_parser import PARSER_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_SCHEMA_VERSION = 1
DEFAULT_CHECKPOINT_ROOT = REPOSITORY_ROOT / "data" / "ingestion_runs" / CHUNKER_VERSION
CHUNKS_FILENAME = "chunks.jsonl"
CHUNKS_MARKDOWN_FILENAME = "chunks.md"
CHUNK_CHECKPOINT_FILENAME = "checkpoint.json"
EMBEDDINGS_DIRECTORY_NAME = "embeddings"
EMBEDDINGS_FILENAME = "embeddings.jsonl.gz"
EMBEDDING_CHECKPOINT_FILENAME = "checkpoint.json"


@dataclass(frozen=True)
class DocumentCheckpointPaths:
    directory: Path
    chunks: Path
    chunks_markdown: Path
    checkpoint: Path
    embeddings_directory: Path
    embeddings: Path
    embedding_checkpoint: Path


@dataclass(frozen=True)
class ChunkCheckpoint:
    schema_version: int
    accession_number: str
    ticker: str
    form: str
    content_checksum: str
    parser_version: str
    chunker_version: str
    embedding_model: str
    embedding_dimensions: int
    markdown_path: str
    parsed_path: str
    chunk_count: int
    chunk_token_count: int
    table_chunk_count: int
    chunks_sha256: str

    def to_dict(self) -> dict[str, object]:
        return dict(vars(self))

    @classmethod
    def from_dict(cls, value: object) -> ChunkCheckpoint:
        data = _object(value, "chunk checkpoint")
        return cls(
            schema_version=_integer(data, "schema_version"),
            accession_number=_string(data, "accession_number"),
            ticker=_string(data, "ticker"),
            form=_string(data, "form"),
            content_checksum=_digest(data, "content_checksum"),
            parser_version=_string(data, "parser_version"),
            chunker_version=_string(data, "chunker_version"),
            embedding_model=_string(data, "embedding_model"),
            embedding_dimensions=_integer(data, "embedding_dimensions"),
            markdown_path=_string(data, "markdown_path"),
            parsed_path=_string(data, "parsed_path"),
            chunk_count=_integer(data, "chunk_count"),
            chunk_token_count=_integer(data, "chunk_token_count"),
            table_chunk_count=_integer(data, "table_chunk_count", minimum=0),
            chunks_sha256=_digest(data, "chunks_sha256"),
        )


@dataclass(frozen=True)
class EmbeddingCheckpoint:
    schema_version: int
    accession_number: str
    content_checksum: str
    parser_version: str
    chunker_version: str
    chunks_sha256: str
    embedding_model: str
    embedding_dimensions: int
    embedding_count: int
    embedding_input_tokens: int
    embedding_request_count: int
    embeddings_sha256: str

    def to_dict(self) -> dict[str, object]:
        return dict(vars(self))

    @classmethod
    def from_dict(cls, value: object) -> EmbeddingCheckpoint:
        data = _object(value, "embedding checkpoint")
        return cls(
            schema_version=_integer(data, "schema_version"),
            accession_number=_string(data, "accession_number"),
            content_checksum=_digest(data, "content_checksum"),
            parser_version=_string(data, "parser_version"),
            chunker_version=_string(data, "chunker_version"),
            chunks_sha256=_digest(data, "chunks_sha256"),
            embedding_model=_string(data, "embedding_model"),
            embedding_dimensions=_integer(data, "embedding_dimensions"),
            embedding_count=_integer(data, "embedding_count"),
            embedding_input_tokens=_integer(
                data,
                "embedding_input_tokens",
                minimum=0,
            ),
            embedding_request_count=_integer(data, "embedding_request_count"),
            embeddings_sha256=_digest(data, "embeddings_sha256"),
        )


def checkpoint_paths(
    accession_number: str,
    checkpoint_root: Path = DEFAULT_CHECKPOINT_ROOT,
) -> DocumentCheckpointPaths:
    if not accession_number or any(
        character not in "0123456789-" for character in accession_number
    ):
        raise ValueError(f"Invalid accession number: {accession_number!r}")
    directory = checkpoint_root / accession_number
    embeddings_directory = directory / EMBEDDINGS_DIRECTORY_NAME
    return DocumentCheckpointPaths(
        directory=directory,
        chunks=directory / CHUNKS_FILENAME,
        chunks_markdown=directory / CHUNKS_MARKDOWN_FILENAME,
        checkpoint=directory / CHUNK_CHECKPOINT_FILENAME,
        embeddings_directory=embeddings_directory,
        embeddings=embeddings_directory / EMBEDDINGS_FILENAME,
        embedding_checkpoint=(embeddings_directory / EMBEDDING_CHECKPOINT_FILENAME),
    )


def prepare_document_checkpoint(
    source_row: SourceDocumentRow,
    *,
    embedding_model: str,
    embedding_dimensions: int,
    checkpoint_root: Path = DEFAULT_CHECKPOINT_ROOT,
) -> tuple[ChunkCheckpoint, list[PreparedChunk], bool]:
    paths = checkpoint_paths(source_row["accession_number"], checkpoint_root)
    token_counter = OpenAITokenCounter(embedding_model)
    if paths.directory.exists():
        checkpoint, chunks = load_document_chunks(
            source_row,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            checkpoint_root=checkpoint_root,
            token_counter=token_counter,
        )
        return checkpoint, chunks, False

    parsed_path, markdown_path = document_paths(source_row)
    chunks = chunk_document(parsed_path, markdown_path, token_counter)
    checkpoint = _write_chunk_checkpoint(
        paths,
        source_row,
        chunks,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        parsed_path=parsed_path,
        markdown_path=markdown_path,
    )
    return checkpoint, chunks, True


def load_document_chunks(
    source_row: SourceDocumentRow,
    *,
    embedding_model: str,
    embedding_dimensions: int,
    checkpoint_root: Path = DEFAULT_CHECKPOINT_ROOT,
    token_counter: TokenCounter | None = None,
) -> tuple[ChunkCheckpoint, list[PreparedChunk]]:
    paths = checkpoint_paths(source_row["accession_number"], checkpoint_root)
    checkpoint = ChunkCheckpoint.from_dict(
        json.loads(paths.checkpoint.read_text(encoding="utf-8"))
    )
    _validate_chunk_checkpoint_identity(
        checkpoint,
        source_row,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
    )
    actual_sha256 = _file_sha256(paths.chunks)
    if actual_sha256 != checkpoint.chunks_sha256:
        raise ValueError(f"Chunk checkpoint checksum mismatch: {paths.chunks}")

    counter = token_counter or OpenAITokenCounter(embedding_model)
    chunks = [
        _chunk_from_record(json.loads(line))
        for line in paths.chunks.read_text(encoding="utf-8").splitlines()
        if line
    ]
    _validate_chunks(chunks, checkpoint, counter)
    return checkpoint, chunks


def save_document_embeddings(
    source_row: SourceDocumentRow,
    chunk_checkpoint: ChunkCheckpoint,
    vectors: Sequence[list[float]],
    *,
    embedding_model: str,
    embedding_dimensions: int,
    embedding_input_tokens: int,
    embedding_request_count: int,
    checkpoint_root: Path = DEFAULT_CHECKPOINT_ROOT,
) -> EmbeddingCheckpoint:
    paths = checkpoint_paths(source_row["accession_number"], checkpoint_root)
    _validate_chunk_checkpoint_identity(
        chunk_checkpoint,
        source_row,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
    )
    if paths.embeddings_directory.exists():
        raise FileExistsError(
            "Embedding checkpoint already exists and will not be overwritten: "
            f"{paths.embeddings_directory}"
        )
    _validate_vectors(
        vectors,
        expected_count=chunk_checkpoint.chunk_count,
        expected_dimensions=embedding_dimensions,
    )

    paths.directory.mkdir(parents=True, exist_ok=True)
    temporary_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{EMBEDDINGS_DIRECTORY_NAME}-",
            dir=paths.directory,
        )
    )
    try:
        vectors_path = temporary_directory / EMBEDDINGS_FILENAME
        with gzip.open(vectors_path, "wt", encoding="utf-8", newline="\n") as output:
            for index, vector in enumerate(vectors):
                output.write(
                    json.dumps(
                        {"chunk_index": index, "embedding": vector},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                output.write("\n")

        embedding_checkpoint = EmbeddingCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            accession_number=source_row["accession_number"],
            content_checksum=source_row["content_checksum"],
            parser_version=PARSER_VERSION,
            chunker_version=CHUNKER_VERSION,
            chunks_sha256=chunk_checkpoint.chunks_sha256,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            embedding_count=len(vectors),
            embedding_input_tokens=embedding_input_tokens,
            embedding_request_count=embedding_request_count,
            embeddings_sha256=_file_sha256(vectors_path),
        )
        _write_json(
            temporary_directory / EMBEDDING_CHECKPOINT_FILENAME,
            embedding_checkpoint.to_dict(),
        )
        os.replace(temporary_directory, paths.embeddings_directory)
    except BaseException:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise
    return embedding_checkpoint


def load_document_embeddings(
    source_row: SourceDocumentRow,
    chunk_checkpoint: ChunkCheckpoint,
    *,
    embedding_model: str,
    embedding_dimensions: int,
    checkpoint_root: Path = DEFAULT_CHECKPOINT_ROOT,
) -> tuple[EmbeddingCheckpoint, list[list[float]]]:
    paths = checkpoint_paths(source_row["accession_number"], checkpoint_root)
    _validate_chunk_checkpoint_identity(
        chunk_checkpoint,
        source_row,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
    )
    embedding_checkpoint = EmbeddingCheckpoint.from_dict(
        json.loads(paths.embedding_checkpoint.read_text(encoding="utf-8"))
    )
    _validate_embedding_checkpoint_identity(
        embedding_checkpoint,
        source_row,
        chunk_checkpoint,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
    )
    actual_sha256 = _file_sha256(paths.embeddings)
    if actual_sha256 != embedding_checkpoint.embeddings_sha256:
        raise ValueError(f"Embedding checkpoint checksum mismatch: {paths.embeddings}")

    vectors = []
    with gzip.open(paths.embeddings, "rt", encoding="utf-8") as source:
        for expected_index, line in enumerate(source):
            record = _object(json.loads(line), "embedding record")
            chunk_index = _integer(record, "chunk_index", minimum=0)
            if chunk_index != expected_index:
                raise ValueError("Embedding checkpoint indexes are not contiguous")
            value = record.get("embedding")
            if not isinstance(value, list):
                raise TypeError("Embedding record must contain a vector list")
            vector = []
            for item in value:
                if isinstance(item, bool) or not isinstance(item, int | float):
                    raise TypeError("Embedding vector values must be numbers")
                number = float(item)
                if not math.isfinite(number):
                    raise ValueError("Embedding vector values must be finite")
                vector.append(number)
            vectors.append(vector)
    _validate_vectors(
        vectors,
        expected_count=embedding_checkpoint.embedding_count,
        expected_dimensions=embedding_dimensions,
    )
    return embedding_checkpoint, vectors


def render_chunks_markdown(chunks: Sequence[PreparedChunk]) -> str:
    parts = [
        "# Generated chunks\n",
        (
            "Each section below is the exact text sent to the embedding model. "
            "Source offsets refer to the normalized Markdown document.\n"
        ),
    ]
    for chunk in chunks:
        block_ids = ", ".join(str(value) for value in chunk.metadata["block_ids"])
        parts.extend(
            [
                f"## Chunk {chunk.chunk_index}\n",
                f"- Tokens: {chunk.token_count}\n",
                f"- Section: {chunk.section_title or 'None'}\n",
                f"- Contains table: {chunk.metadata['contains_table']}\n",
                f"- Block IDs: `{block_ids}`\n",
                f"- Source offsets: {chunk.source_start}–{chunk.source_end}\n",
                "````text\n",
                chunk.text,
                "\n````\n",
            ]
        )
    return "\n".join(parts)


def select_source_rows(
    source_rows: Sequence[SourceDocumentRow],
    accession_number: str | None,
) -> list[SourceDocumentRow]:
    if accession_number is None:
        return list(source_rows)
    selected = [
        row for row in source_rows if row["accession_number"] == accession_number
    ]
    if not selected:
        raise ValueError(f"Accession number is not in the manifest: {accession_number}")
    return selected


def _write_chunk_checkpoint(
    paths: DocumentCheckpointPaths,
    source_row: SourceDocumentRow,
    chunks: Sequence[PreparedChunk],
    *,
    embedding_model: str,
    embedding_dimensions: int,
    parsed_path: Path,
    markdown_path: Path,
) -> ChunkCheckpoint:
    paths.directory.parent.mkdir(parents=True, exist_ok=True)
    temporary_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{source_row['accession_number']}-",
            dir=paths.directory.parent,
        )
    )
    try:
        chunks_bytes = b"".join(
            (
                json.dumps(
                    _chunk_to_record(chunk),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            for chunk in chunks
        )
        (temporary_directory / CHUNKS_FILENAME).write_bytes(chunks_bytes)
        (temporary_directory / CHUNKS_MARKDOWN_FILENAME).write_text(
            render_chunks_markdown(chunks),
            encoding="utf-8",
        )
        checkpoint = ChunkCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            accession_number=source_row["accession_number"],
            ticker=source_row["ticker"],
            form=source_row["filing_type"],
            content_checksum=source_row["content_checksum"],
            parser_version=PARSER_VERSION,
            chunker_version=CHUNKER_VERSION,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            markdown_path=str(markdown_path.relative_to(REPOSITORY_ROOT)),
            parsed_path=str(parsed_path.relative_to(REPOSITORY_ROOT)),
            chunk_count=len(chunks),
            chunk_token_count=sum(chunk.token_count for chunk in chunks),
            table_chunk_count=sum(chunk.display_table is not None for chunk in chunks),
            chunks_sha256=hashlib.sha256(chunks_bytes).hexdigest(),
        )
        _write_json(
            temporary_directory / CHUNK_CHECKPOINT_FILENAME,
            checkpoint.to_dict(),
        )
        os.replace(temporary_directory, paths.directory)
    except BaseException:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise
    return checkpoint


def _chunk_to_record(chunk: PreparedChunk) -> dict[str, object]:
    return {
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "token_count": chunk.token_count,
        "page_number": chunk.page_number,
        "section_title": chunk.section_title,
        "source_start": chunk.source_start,
        "source_end": chunk.source_end,
        "metadata": chunk.metadata,
        "display_table": (
            chunk.display_table.model_dump(mode="json")
            if chunk.display_table is not None
            else None
        ),
    }


def _chunk_from_record(value: object) -> PreparedChunk:
    data = _object(value, "chunk record")
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise TypeError("Chunk metadata must be an object")
    display_value = data.get("display_table")
    display_table = (
        StoredDisplayTable.model_validate(display_value)
        if display_value is not None
        else None
    )
    return PreparedChunk(
        chunk_index=_integer(data, "chunk_index", minimum=0),
        text=_string(data, "text"),
        token_count=_integer(data, "token_count"),
        page_number=_optional_integer(data, "page_number"),
        section_title=_optional_string(data, "section_title"),
        source_start=_optional_integer(data, "source_start", minimum=0),
        source_end=_optional_integer(data, "source_end"),
        metadata=cast(dict[str, object], metadata),
        display_table=display_table,
    )


def _validate_chunk_checkpoint_identity(
    checkpoint: ChunkCheckpoint,
    source_row: SourceDocumentRow,
    *,
    embedding_model: str,
    embedding_dimensions: int,
) -> None:
    expected = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "accession_number": source_row["accession_number"],
        "ticker": source_row["ticker"],
        "form": source_row["filing_type"],
        "content_checksum": source_row["content_checksum"],
        "parser_version": PARSER_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
    }
    mismatches = [
        key
        for key, expected_value in expected.items()
        if getattr(checkpoint, key) != expected_value
    ]
    if mismatches:
        raise ValueError(
            "Chunk checkpoint does not match the active pipeline: "
            + ", ".join(mismatches)
        )


def _validate_embedding_checkpoint_identity(
    checkpoint: EmbeddingCheckpoint,
    source_row: SourceDocumentRow,
    chunk_checkpoint: ChunkCheckpoint,
    *,
    embedding_model: str,
    embedding_dimensions: int,
) -> None:
    expected = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "accession_number": source_row["accession_number"],
        "content_checksum": source_row["content_checksum"],
        "parser_version": PARSER_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "chunks_sha256": chunk_checkpoint.chunks_sha256,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
        "embedding_count": chunk_checkpoint.chunk_count,
    }
    mismatches = [
        key
        for key, expected_value in expected.items()
        if getattr(checkpoint, key) != expected_value
    ]
    if mismatches:
        raise ValueError(
            "Embedding checkpoint does not match its chunks: " + ", ".join(mismatches)
        )


def _validate_chunks(
    chunks: Sequence[PreparedChunk],
    checkpoint: ChunkCheckpoint,
    token_counter: TokenCounter,
) -> None:
    if len(chunks) != checkpoint.chunk_count:
        raise ValueError("Chunk checkpoint count does not match chunks.jsonl")
    if [chunk.chunk_index for chunk in chunks] != list(range(len(chunks))):
        raise ValueError("Chunk checkpoint indexes are not contiguous")
    if sum(chunk.token_count for chunk in chunks) != checkpoint.chunk_token_count:
        raise ValueError("Chunk checkpoint token total does not match chunks.jsonl")
    if (
        sum(chunk.display_table is not None for chunk in chunks)
        != checkpoint.table_chunk_count
    ):
        raise ValueError("Chunk checkpoint table count does not match chunks.jsonl")
    for chunk in chunks:
        if token_counter.count_tokens(chunk.text) != chunk.token_count:
            raise ValueError(f"Chunk {chunk.chunk_index} token count changed")
        if not any(character.isalnum() for character in chunk.text):
            raise ValueError(f"Chunk {chunk.chunk_index} contains no information")
        if chunk.display_table is not None:
            for row in chunk.display_table.rows:
                for cell in row.cells:
                    if cell.text:
                        if cell.text_start is None or cell.text_end is None:
                            raise ValueError("Table cell is missing text offsets")
                        if chunk.text[cell.text_start : cell.text_end] != cell.text:
                            raise ValueError(
                                "Table cell offsets do not match chunk text"
                            )


def _validate_vectors(
    vectors: Sequence[list[float]],
    *,
    expected_count: int,
    expected_dimensions: int,
) -> None:
    if len(vectors) != expected_count:
        raise ValueError(
            f"Expected {expected_count} embeddings, received {len(vectors)}"
        )
    for index, vector in enumerate(vectors):
        if len(vector) != expected_dimensions:
            raise ValueError(
                f"Embedding {index} has {len(vector)} dimensions; "
                f"expected {expected_dimensions}"
            )
        if not all(math.isfinite(float(value)) for value in vector):
            raise ValueError(f"Embedding {index} contains a non-finite value")


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise TypeError(f"Field {key!r} must be a non-empty string")
    return value


def _optional_string(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TypeError(f"Field {key!r} must be null or a non-empty string")
    return value


def _integer(
    data: dict[str, object],
    key: str,
    *,
    minimum: int = 1,
) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TypeError(f"Field {key!r} must be an integer >= {minimum}")
    return value


def _optional_integer(
    data: dict[str, object],
    key: str,
    *,
    minimum: int = 1,
) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TypeError(f"Field {key!r} must be null or an integer >= {minimum}")
    return value


def _digest(data: dict[str, object], key: str) -> str:
    value = _string(data, key)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise TypeError(f"Field {key!r} must be a lowercase SHA-256 digest")
    return value
