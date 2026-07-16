#!/usr/bin/env sh
# Applies the audit retention policy: deletes audit rows older than the
# configured window (AUDIT_RETENTION_DAYS / AUDIT_RETENTION_OVERRIDES in .env).
# Usage: scripts/retention.sh [--dry-run] [--days N]
# Schedule with cron for unattended enforcement; see docs/DataRetention.md.

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
exec "$python" -m app.audit.retention "$@"
