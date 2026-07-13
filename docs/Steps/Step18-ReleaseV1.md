# Step 18 Prompt — Finish Setup and Release v1.0

Use this prompt to execute Step 18 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md`). Steps 1–17 delivered the complete, hardened, tested system. This final step brings the solution to **full capability**: a new user must reach a working local assistant — live agents, streaming UI, full audit trail — from a fresh clone, following documented steps that you have actually verified.

## Objective

Polish setup automation, verify the entire clean-machine path end to end, synchronize the documentation with what was actually built, and tag the v1.0 release.

## Tasks

1. **Setup automation:** finalize `scripts/setup.ps1` and `scripts/setup.sh` to perform, idempotently and with clear progress output: prerequisite checks (Python version, Node version, Docker) with actionable failure messages → create/activate the Python venv → install backend (`pip install -e backend[dev]`) → `npm ci` in `frontend/` → copy `.env.example` to `.env` if absent. The script must be safe to re-run.
2. **Clean-machine verification (the heart of this step):** from a fresh clone in a pristine environment (new directory, no venv, no `node_modules`, empty Docker volumes), execute and time the full documented path:
   1. `scripts/setup`
   2. `docker compose up -d postgres`
   3. `scripts/migrate`
   4. `scripts/download_model`
   5. `scripts/build_frontend`
   6. start the service
   7. open the UI, run a prompt, watch live phases, trigger an agent, see it complete in the AgentPanel, and confirm the audit chain in Postgres.
   Fix every friction point you hit — missing error message, undocumented prerequisite, wrong default — rather than documenting around it.
3. **Documentation sync:** walk `docs/Architecture.md`, `docs/Components/*.md`, and `docs/BuildPlan.md` against the real code. Correct drift (renamed modules, changed endpoints, added settings) so the docs describe the system as built. Update the root `README.md` with the final quickstart (the exact verified sequence above), prerequisites, and a screenshot or short capture of the UI if practical.
4. **Release hygiene:**
   - Full quality gate: `pytest` green, frontend tests green, lint/type-check clean, CI green.
   - Version the app (backend `pyproject.toml` version, surfaced in `/api/health` and the StatusBar).
   - Write `CHANGELOG.md` for v1.0 summarizing capabilities by phase.
   - Tag `v1.0.0` on the main branch.
5. **Capability statement:** append a short "v1.0 capabilities" section to the README: local-first chat with an in-process llama.cpp model, governed and fully audited prompt lifecycle, LangGraph orchestration, live WebSocket state, background agents with UI visibility, hardened failure behavior — and known limitations (single-node, single model, concurrency profile).

## Constraints

- Nothing ships that you did not verify on the clean-machine path — "works on my machine" state is a failure of this step.
- Documentation must match reality; where code and docs disagree, fix whichever is wrong, deliberately.
- No new features: scope is polish, verification, documentation, and release.

## Verification

- A fresh clone on a machine with only Python, Node, and Docker reaches a working assistant using nothing but the README quickstart — every command succeeds first try.
- The full demo path works: prompt → live phases → real answer → agent spawned → agent completes in the AgentPanel → complete audit chain visible in Postgres.
- CI is green on the tagged commit; `/api/health` reports v1.0.0.
- `docs/` accurately describes the shipped system.
- The `v1.0.0` tag exists and `CHANGELOG.md` tells the story. **LunaBlue is at full capability.**
