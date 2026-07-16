# Step 17 Prompt — Harden the Runtime

Use this prompt to execute Step 17 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and `docs/Components/AUDIT.md`). Steps 1–16 delivered the fully featured, fully tested system. This step makes it robust: the service must degrade gracefully — bad prompts, model failures, and database outages produce clean errors and audit entries, never crashes.

## Objective

Systematically harden every runtime seam: timeouts, error handling, startup validation, readiness, and the data retention/redaction safeguards required by `docs/Components/AUDIT.md`.

## Tasks

1. **Startup validation (fail fast):** on boot, validate all settings coherently — model file exists and is readable, database URL parses and (optionally, flag-controlled) connects, static directory state, numeric bounds (context size, GPU layers, queue sizes). Any failure aborts startup with a single actionable error message.
2. **Model execution guards:** configurable timeout on every `LlamaRuntime.generate()` call (foreground and agent); on timeout, the run/agent fails cleanly with an audited event. Add a queue-depth guard: if the generation queue exceeds a configured backlog, new prompt submissions get a fast 503 "busy" rather than unbounded queuing. Handle model crash (llama.cpp exception) by marking the runtime unhealthy, failing in-flight work cleanly, and reporting it via readiness.
3. **Agent guards:** per-agent wall-clock timeout and max-step limits enforced by the `AgentRunner`; runaway agents are cancelled and audited.
4. **Database outage behavior:** readiness reflects DB state; audit writer already tolerates outages (Step 4) — verify its bounded-queue overflow policy under sustained outage and log a periodic aggregate warning rather than per-event spam. API endpoints that *read* Postgres return clean 503s.
5. **Error taxonomy:** consistent JSON error shape across the API (`code`, `message`, `request_id`); map validation, governance rejection, timeout, busy, and internal errors to distinct codes; never leak stack traces or file paths in responses (they go to logs).
6. **Readiness vs. liveness:** `GET /api/health` (liveness — process up) vs. `GET /api/health/ready` (readiness — DB reachable, model loaded and healthy, audit queue not overflowing, runner alive). The StatusBar consumes readiness detail.
7. **Retention and redaction (per `docs/Components/AUDIT.md`):**
   - A configurable redaction pass applied before audit writes: regex-based masking of obvious secrets (API keys, tokens) and configurable PII patterns; the raw prompt column stores redacted text when redaction is enabled — document the trade-off.
   - A retention policy: `scripts/retention` (and/or a startup-scheduled task) that deletes or anonymizes audit rows older than a configured window, per table.
   - Document both in `docs/` (data retention and privacy safeguards section).
8. **WebSocket resilience:** heartbeat/ping so dead connections are reaped; subscriber overflow already drops-oldest (Step 13) — surface a `degraded` flag to that client so the UI can resync via snapshot.
9. Extend the Step 16 suites with tests for each guard above (timeout, busy, DB-down reads, redaction, retention dry-run, error shape).

## Constraints

- Graceful degradation over feature completeness: it is acceptable for a feature to be temporarily unavailable (503) — it is not acceptable to crash, hang, or corrupt state.
- All new limits and policies are configuration, not constants — extend `config.py` and `.env.example`.
- No behavior change on the happy path; existing tests must keep passing.

## Verification

- Kill Postgres mid-session: prompts still generate (audit queues), status reads 503 cleanly, readiness reports degraded, and recovery drains the queue — no crash, no data corruption.
- A generation forced past its timeout fails that run cleanly with an audited timeout event; the next prompt succeeds.
- Flooding the API triggers the 503 busy guard rather than unbounded latency growth.
- A prompt containing a fake API key is stored redacted in `prompt_requests` (with redaction enabled).
- The retention script removes only rows older than the configured window (verify with seeded data).
- Malformed requests, rejections, timeouts, and internal failures all return the documented error shape with distinct codes.
