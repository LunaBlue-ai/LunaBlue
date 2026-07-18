#!/usr/bin/env sh
# Downloads the default GGUF model into models/ for the local LLM runtime.
# Default: Phi-3-mini-4k-instruct Q4 (MIT license, ~2.3 GB, CPU-friendly),
# saved as models/model.gguf to match .env.example's MODEL_PATH default.
# Usage: scripts/download_model.sh [gguf-url] [out-file]
# See models/README.md for substituting another model.

set -eu

DEFAULT_URL="https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root="$script_dir/.."
models_dir="$repo_root/models"
mkdir -p "$models_dir"

url="${1:-$DEFAULT_URL}"
out_file="${2:-$models_dir/model.gguf}"

if [ -f "$out_file" ]; then
    echo "Model already present: $out_file"
    echo "Delete it first to re-download."
    exit 0
fi

# Download to a temp name and rename on success, so an interrupted download
# never leaves a partial file where MODEL_PATH expects a complete one.
partial="$out_file.partial"

echo "Downloading $url"
echo "       to $out_file (~2.3 GB, this can take a while)"

if command -v curl >/dev/null 2>&1; then
    curl -L --fail --retry 3 -C - -o "$partial" "$url"
elif command -v wget >/dev/null 2>&1; then
    wget -c -O "$partial" "$url"
else
    echo "error: neither curl nor wget found" >&2
    exit 1
fi

mv "$partial" "$out_file"
echo "Done. Model saved to $out_file"
echo "MODEL_PATH in .env.example already points here (./models/model.gguf)."
