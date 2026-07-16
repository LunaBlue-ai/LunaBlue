# Data Retention and Privacy Safeguards

LunaBlue's audit store (`docs/Components/AUDIT.md`) persists every prompt
request, reviewed prompt, model output, and agent event to Postgres. That
durability is the point of the audit trail — but stored prompt content is
also the most sensitive data the system handles. Step 17 adds two
configurable safeguards: **redaction** (mask secrets/PII before rows are
written) and **retention** (delete rows older than a configured window).
Both are off by default and controlled entirely through `.env`
(`config.py`); see `.env.example` for the knob-by-knob reference.

## Redaction

**What it does.** When `AUDIT_REDACTION_ENABLED=true`, a regex-based
redaction pass (`backend/app/audit/redaction.py`) masks well-known secret
shapes — OpenAI/Anthropic-style API keys, AWS access key ids, GitHub/Slack
tokens, JWTs, `Bearer` credentials, `key=value` assignments for
obviously-secret key names, and PEM private-key blocks — replacing each
match with `[REDACTED]`. Deployment-specific PII formats (national id
numbers, employee ids, internal ticket references, …) are added via
`AUDIT_REDACTION_PATTERNS`, a JSON array of extra regexes validated at
startup.

**Where it runs.** On the producer side of the audit writer
(`AuditService.record_prompt_request` / `record_prompt_response`), *before*
the event is enqueued. Unredacted text therefore never sits in the audit
queue, never crosses the consumer, and never reaches Postgres. The fields
covered are `raw_prompt`, `reviewed_prompt`, `llm_output`, and
`final_output`.

**The trade-off.** With redaction enabled, the `prompt_requests.raw_prompt`
column stores the *redacted* text — the original input is unrecoverable from
the audit record. That weakens exact replay/debugging (a masked token cannot
be reproduced) in exchange for a hard guarantee: a leaked audit database is
not a credential store. Redaction is also regex-based and best-effort — it
catches known token shapes and configured patterns, not every possible
secret. Deployments that require exact raw capture should leave redaction
off and instead protect the database itself (encryption at rest, access
control) and shorten the retention window.

## Retention

**What it does.** `scripts/retention` (`retention.ps1` / `retention.sh`,
wrapping `python -m app.audit.retention`) deletes audit rows older than a
configured window, per table:

| Table | Age column | Window |
|---|---|---|
| `prompt_responses` | `timestamp` | `AUDIT_RETENTION_DAYS` (or override) |
| `agent_events` | `timestamp` | `AUDIT_RETENTION_DAYS` (or override) |
| `prompt_requests` | `timestamp` | `AUDIT_RETENTION_DAYS` (or override) |
| `sessions` | `updated_at` | `AUDIT_RETENTION_DAYS` (or override) |

`AUDIT_RETENTION_DAYS` is the default window for every table; `0` (the
default) disables retention and keeps rows forever.
`AUDIT_RETENTION_OVERRIDES` narrows or widens individual tables, e.g.
`{"agent_events": 30}` to age out verbose agent telemetry faster than the
prompt record. Deletion order respects the schema's foreign keys (children
first), each table is one DELETE in its own transaction, and the run is
idempotent — an interrupted run leaves a consistent database and the next
run completes the job.

**Dry runs.** `scripts/retention --dry-run` reports the affected row counts
without deleting anything — validate a new window against production data
before enforcing it. `--days N` overrides the configured default for one
run.

**Scheduling.** The script is deliberately a standalone process (it shares
the app's settings and engine but not its lifecycle). Schedule it with cron
(`0 3 * * * /path/to/LunaBlue/scripts/retention.sh`) or Windows Task
Scheduler for unattended enforcement.

**Consequences for the rest of the system.** Evicted-agent reconstruction
(`GET /api/agents/{id}`) and any other audit-backed reads return 404 for
rows retention has removed — the same behavior as an agent that never
existed. The in-memory live state is unaffected (it has its own, much
shorter retention: `STATE_MAX_FINISHED_RUNS` / `STATE_MAX_FINISHED_AGENTS`).

## Related safeguards

- Everything is local-first: prompts and outputs never leave the machine;
  the audit store is a local Postgres owned by the deployment.
- API error responses never echo prompt content, stack traces, or file
  paths (`backend/app/api/errors.py`); internals go to the process log
  keyed by `request_id`.
- The audit queue is bounded (`AUDIT_MAX_QUEUE_SIZE`): during a database
  outage, at most that many recent events are held in memory, and overflow
  drops the oldest rather than growing without bound.
