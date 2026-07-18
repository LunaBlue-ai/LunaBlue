#!/usr/bin/env sh
# Downloads the default embedding GGUF model into models/ for semantic
# search. Default: nomic-embed-text-v1.5 Q8 (Apache-2.0, ~140 MB), saved as
# models/embedding.gguf to match .env.example's EMBEDDING_MODEL_PATH default.
# Usage: scripts/download_embedding_model.sh [gguf-url] [out-file]
# See models/README.md for substituting another model.

set -eu

DEFAULT_URL="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root="$script_dir/.."
models_dir="$repo_root/models"
mkdir -p "$models_dir"

url="${1:-$DEFAULT_URL}"
out_file="${2:-$models_dir/embedding.gguf}"

if [ -f "$out_file" ]; then
    echo "Embedding model already present: $out_file"
    echo "Delete it first to re-download."
    exit 0
fi

# Download to a temp name and rename on success, so an interrupted download
# never leaves a partial file where EMBEDDING_MODEL_PATH expects a complete one.
partial="$out_file.partial"

echo "Downloading $url"
echo "       to $out_file (~140 MB)"

if command -v curl >/dev/null 2>&1; then
    curl -L --fail --retry 3 -C - -o "$partial" "$url"
elif command -v wget >/dev/null 2>&1; then
    wget -c -O "$partial" "$url"
else
    echo "error: neither curl nor wget found" >&2
    exit 1
fi

mv "$partial" "$out_file"
echo "Done. Embedding model saved to $out_file"
echo "EMBEDDING_MODEL_PATH in .env.example already points here (./models/embedding.gguf)."
