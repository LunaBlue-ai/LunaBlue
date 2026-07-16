# Step Prompts

One prompt file per step of [BuildPlan.md](../BuildPlan.md). Each file is a self-contained prompt for an LLM coding agent: it carries the project context, what prior steps delivered, detailed tasks with file paths, the architecture constraints that must hold, and verification criteria matching the step's checkpoint. Execute them in order — each prompt assumes the previous steps are complete.

## Phase 1 — Foundation and the first prompt loop

1. [Step01-ScaffoldRepository.md](Step01-ScaffoldRepository.md) — repository skeleton per the architecture's directory structure
2. [Step02-BackendSkeleton.md](Step02-BackendSkeleton.md) — FastAPI app factory, config, health endpoint
3. [Step03-PostgresAndSchema.md](Step03-PostgresAndSchema.md) — SQLAlchemy, Alembic, and the audit schema
4. [Step04-AuditService.md](Step04-AuditService.md) — off-hot-path structured audit writer
5. [Step05-PromptApi.md](Step05-PromptApi.md) — `POST /api/prompt` with a stubbed response
6. [Step06-GovernanceIntake.md](Step06-GovernanceIntake.md) — prompt normalization, policy tagging, strict mode
7. [Step07-LlmRuntime.md](Step07-LlmRuntime.md) — the single global llama.cpp runtime + model download
8. [Step08-EndToEndLoop.md](Step08-EndToEndLoop.md) — the minimal vertical slice: real answers, full audit chain

## Phase 2 — Orchestration, frontend, and agents

9. [Step09-LangGraphMainGraph.md](Step09-LangGraphMainGraph.md) — the main request graph and its nodes
10. [Step10-SharedStateStore.md](Step10-SharedStateStore.md) — in-memory state store and run status APIs
11. [Step11-FrontendScaffold.md](Step11-FrontendScaffold.md) — Vite React chat UI in dev mode
12. [Step12-FrontendBuildIntegration.md](Step12-FrontendBuildIntegration.md) — single-process serving from `backend/app/static`
13. [Step13-WebSocketsLiveState.md](Step13-WebSocketsLiveState.md) — event bus, `/ws` endpoint, live UI with polling fallback
14. [Step14-BackgroundAgents.md](Step14-BackgroundAgents.md) — agent contract, runner, and the agent-spawn node
15. [Step15-AgentUi.md](Step15-AgentUi.md) — agent APIs, AgentPanel, and StatusBar

## Phase 3 — Quality, hardening, and release

16. [Step16-TestSuites.md](Step16-TestSuites.md) — consolidated CI-ready suites with the LLM stubbed
17. [Step17-Hardening.md](Step17-Hardening.md) — timeouts, graceful degradation, retention and redaction
18. [Step18-ReleaseV1.md](Step18-ReleaseV1.md) — clean-machine verification, docs sync, v1.0 release
