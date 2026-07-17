"""Audit data retention (Step 17, per docs/Components/AUDIT.md).

Deletes audit rows older than a configured window, per table, so stored
prompt content does not accumulate forever. Invoked by ``scripts/retention``
(``python -m app.audit.retention``); schedule it with cron / Task Scheduler
for unattended enforcement. Policy and trade-offs are documented in
docs/DataRetention.md.

Windows come from ``AUDIT_RETENTION_DAYS`` (the default for every table)
plus ``AUDIT_RETENTION_OVERRIDES`` (JSON object, table name -> days); a
window of 0 keeps that table's rows forever. Deletion order respects the
foreign keys (children first), and each table is one bounded DELETE inside
one transaction — an interrupted run leaves a consistent database and the
next run finishes the job.

``--dry-run`` reports what *would* be deleted without touching anything —
the safe way to validate a new window against production data.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.audit import db, models
from app.config import get_settings

logger = logging.getLogger(__name__)

# Deletion order matters: children before parents. prompt_responses cascades
# from prompt_requests and agent_events sets its request FK to NULL, but
# deleting explicitly keeps each table's window independent and the row
# counts honest. Sessions go last; prompt_requests.session_id is SET NULL.
_TABLES = (
    ("prompt_responses", models.PromptResponse, models.PromptResponse.timestamp),
    ("agent_events", models.AgentEvent, models.AgentEvent.timestamp),
    ("prompt_requests", models.PromptRequest, models.PromptRequest.timestamp),
    ("sessions", models.Session, models.Session.updated_at),
)


def resolve_windows(
    default_days: int, overrides: dict[str, int]
) -> dict[str, int]:
    """Effective per-table windows (days); 0 disables a table's retention."""
    return {
        name: overrides.get(name, default_days) for name, _, _ in _TABLES
    }


async def apply_retention(
    *,
    windows: dict[str, int],
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Delete (or, when ``dry_run``, count) rows older than each window.

    Returns the number of affected rows per table. Requires the engine to be
    initialized (``db.init_engine``).
    """
    now = now or datetime.now(timezone.utc)
    affected: dict[str, int] = {}
    for name, model, column in _TABLES:
        days = windows.get(name, 0)
        if days <= 0:
            affected[name] = 0
            continue
        cutoff = now - timedelta(days=days)
        async with db.session_scope() as session:
            if dry_run:
                count = (
                    await session.execute(
                        select(func.count())
                        .select_from(model)
                        .where(column < cutoff)
                    )
                ).scalar_one()
            else:
                result = await session.execute(
                    delete(model).where(column < cutoff)
                )
                count = result.rowcount or 0
        affected[name] = count
        logger.info(
            "retention: %s rows older than %d day(s) in %s%s",
            count,
            days,
            name,
            " (dry run — nothing deleted)" if dry_run else " deleted",
        )
    return affected


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.audit.retention",
        description=(
            "Delete audit rows older than the configured retention window "
            "(AUDIT_RETENTION_DAYS / AUDIT_RETENTION_OVERRIDES)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report affected row counts without deleting anything",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="override AUDIT_RETENTION_DAYS for this run (all tables)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    default_days = (
        args.days if args.days is not None else settings.audit_retention_days
    )
    if default_days < 0:
        parser.error("--days must be >= 0")
    windows = resolve_windows(default_days, settings.audit_retention_overrides)
    if not any(windows.values()):
        print(
            "Retention is disabled (all windows are 0). Set "
            "AUDIT_RETENTION_DAYS or pass --days.",
            file=sys.stderr,
        )
        return 1

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Retention can run standalone before the app ever booted: make sure the
    # database directory exists (SQLite creates the file on first connect).
    db_path = settings.resolved_database_path
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    db.init_engine(settings.resolved_database_url)
    try:
        affected = await apply_retention(windows=windows, dry_run=args.dry_run)
    finally:
        await db.dispose_engine()

    verb = "would delete" if args.dry_run else "deleted"
    for name, count in affected.items():
        window = windows[name]
        print(
            f"{name}: {verb} {count} row(s)"
            + (f" older than {window} day(s)" if window else " (disabled)")
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via scripts/retention
    raise SystemExit(asyncio.run(_main()))
