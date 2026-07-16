# Step 6 Prompt — Add Governance Intake

Use this prompt to execute Step 6 of [BuildPlan.md](../BuildPlan.md).

---

You are building **LunaBlue** (see `docs/Architecture.md` and the Governance section of `docs/Components/API.md`). Steps 1–5 delivered a FastAPI service where `POST /api/prompt` validates input, audits a `PromptRequestEvent`, and returns a stubbed response.

## Objective

Implement the governance intake layer that sits between the API and (future) orchestration: normalize and enrich incoming prompt text, tag requests with policy metadata and safety directives, and audit both the raw and reviewed prompt.

## Tasks

1. Implement `backend/app/governance/intake.py`:
   - A `PromptIntake` component with a method like `review(raw_text, context) -> ReviewedPrompt`.
   - Normalization: trim, collapse redundant whitespace, normalize unicode, enforce configured length bounds.
   - Enrichment: attach session context, a `prompt_version` (increments if the same session resubmits), and an intake timestamp.
   - `ReviewedPrompt` result type carrying: `reviewed_text`, `prompt_version`, and the governance metadata from `policy.py`.
2. Implement `backend/app/governance/policy.py`:
   - A `PolicyEngine` producing `GovernanceMetadata`: policy tags (e.g. topic/category hints), safety directives to be prepended or applied at generation time, and decision rationale strings.
   - A configurable strict mode (`settings.governance_strict_mode`): in strict mode, prompts matching configured deny rules are rejected with a clear reason; otherwise they are tagged and allowed.
   - Keep rules data-driven (a simple declarative rule list) so they can evolve without code changes.
3. Integrate into the prompt route: raw text → `PromptIntake.review()` → the reviewed prompt and `GovernanceMetadata` are included in the `PromptRequestEvent` (populating the `reviewed_prompt` and governance columns from Step 3).
4. Rejected prompts return a 4xx with the policy reason and are audited with a `rejected` governance flag.

## Constraints

- Governance logic lives only in `governance/` — the route calls it, the (future) graph consumes its output; neither reimplements it.
- Governance must be deterministic and fast (no LLM calls here — LLM-based review is a graph node in Step 9).
- Every governance decision is auditable: tags, directives, and rationale all land in Postgres.

## Verification

- Submitting a messy prompt (padded whitespace, odd unicode) produces a normalized `reviewed_prompt` in `prompt_requests` alongside the untouched raw text.
- Governance metadata (tags, directives, rationale) is present in the audit row as structured JSON.
- With strict mode on, a prompt matching a deny rule returns a 4xx with the reason, and the audit row shows the rejection.
- With strict mode off, the same prompt passes through tagged.
