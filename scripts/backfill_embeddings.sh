#!/usr/bin/env sh
# Backfills embeddings for audit rows stored before embeddings existed:
# embeds prompt/response text with the local embedding model and writes the
# vectors into the sqlite-vec store. Idempotent - safe to re-run.
# Usage: scripts/backfill_embeddings.sh [--dry-run] [--batch-size N]
# Requires the embedding model (scripts/download_embedding_model.sh).

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
backend_dir="$script_dir/../backend"

# Prefer the backend virtualenv's python; fall back to whatever is on PATH.
if [ -x "$backend_dir/.venv/bin/python" ]; then
    python="$backend_dir/.venv/bin/python"
elif [ -x "$backend_dir/.venv/Scripts/python.exe" ]; then
    python="$backend_dir/.venv/Scripts/python.exe"
else
    python="python"
fi

cd "$backend_dir"
exec "$python" -m app.audit.embeddings_backfill "$@"
