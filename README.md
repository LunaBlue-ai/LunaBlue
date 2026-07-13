# LunaBlue

LunaBlue is a local-first AI assistant that runs entirely on your own machine: a single Python FastAPI process serves the React UI, runs LangGraph orchestration, and executes an in-process `llama-cpp-python` LLM. Runtime state lives in memory and streams to the UI over WebSockets, while a full audit trail of prompts, responses, and governance decisions is persisted to Postgres — no remote model servers, no data leaving your hardware.

## Documentation

- [docs/Architecture.md](docs/Architecture.md) — full system architecture, directory structure, and design principles.
- [docs/BuildPlan.md](docs/BuildPlan.md) — the 18-step incremental plan for building the solution.

## Getting started

> Placeholder — completed in Step 18 of the [build plan](docs/BuildPlan.md).
