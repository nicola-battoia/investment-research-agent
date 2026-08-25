#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BACKEND_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

if (( $# > 1 )); then
  printf 'Usage: %s [ACCESSION_NUMBER]\n' "$0" >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  printf 'Error: uv is not available on PATH.\n' >&2
  exit 127
fi

cd "${BACKEND_DIR}"

printf '\n[1/2] Upserting all source_documents from normalized Markdown\n'
uv run --locked python -m ingestion.ingest_documents

printf '\n[2/2] Uploading document_chunks from local embedding checkpoints\n'
if (( $# == 1 )); then
  uv run --locked python -m ingestion.upload_checkpoints --accession-number "$1"
else
  uv run --locked python -m ingestion.upload_checkpoints
fi

printf '\nUpload complete. Run 04_verify_supabase.sh for an independent check.\n'
