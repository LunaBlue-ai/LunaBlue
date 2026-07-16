#!/usr/bin/env sh
# Builds the React frontend and copies the bundle into backend/app/static/
# so a single FastAPI process serves both the UI and the API
# (docs/Architecture.md). Usage: scripts/build_frontend.sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root="$script_dir/.."
frontend_dir="$repo_root/frontend"
static_dir="$repo_root/backend/app/static"
dist_dir="$frontend_dir/dist"

cd "$frontend_dir"
if [ -f package-lock.json ]; then
    npm ci
else
    npm install
fi
npm run build

if [ ! -f "$dist_dir/index.html" ]; then
    echo "error: build succeeded but $dist_dir/index.html is missing" >&2
    exit 1
fi

# Clear the previous bundle but keep the .gitkeep that pins the (otherwise
# gitignored) directory in the repository.
mkdir -p "$static_dir"
for entry in "$static_dir"/* "$static_dir"/.[!.]* "$static_dir"/..?*; do
    [ -e "$entry" ] || continue
    [ "$(basename "$entry")" = ".gitkeep" ] && continue
    rm -rf "$entry"
done

cp -R "$dist_dir"/. "$static_dir"/

if [ ! -f "$static_dir/index.html" ]; then
    echo "error: copy failed, $static_dir/index.html is missing" >&2
    exit 1
fi

echo "Frontend bundle copied to $static_dir"
echo "Start the backend (uvicorn app.main:app --port 8000) and open http://localhost:8000/"
