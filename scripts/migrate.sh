#!/usr/bin/env sh
# Runs Alembic migrations (upgrade head) against the configured database.
# The database URL comes from DATABASE_URL / .env via the app settings.
# Usage: scripts/migrate.sh [extra alembic args, e.g. downgrade base]

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
backend_dir="$script_dir/../backend"

# Prefer the backend virtualenv's alembic; fall back to whatever is on PATH.
if [ -x "$backend_dir/.venv/bin/alembic" ]; then
    alembic="$backend_dir/.venv/bin/alembic"
elif [ -x "$backend_dir/.venv/Scripts/alembic.exe" ]; then
    alembic="$backend_dir/.venv/Scripts/alembic.exe"
else
    alembic="alembic"
fi

cd "$backend_dir"

if [ "$#" -gt 0 ]; then
    exec "$alembic" "$@"
else
    exec "$alembic" upgrade head
fi
