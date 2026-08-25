#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly CONFIRMATION="run-paid-embeddings-and-upload"

if (( $# != 1 )) || [[ "$1" != "${CONFIRMATION}" ]]; then
  printf 'This command creates paid embeddings and writes to Supabase.\n' >&2
  printf 'Usage: %s %s\n' "$0" "${CONFIRMATION}" >&2
  exit 2
fi

"${SCRIPT_DIR}/01_prepare_local.sh"
"${SCRIPT_DIR}/02_create_embeddings.sh"
"${SCRIPT_DIR}/03_upload_supabase.sh"
"${SCRIPT_DIR}/04_verify_supabase.sh"

printf '\nThe complete checkpointed ingestion pipeline finished successfully.\n'
