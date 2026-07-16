# LunaBlue-Docs

LunaBlue is a local-first AI assistant that runs entirely on your own machine. A single Python service hosts the web UI, the orchestration engine, and the language model itself — no remote model servers, no data leaving your hardware.

This repository holds the documentation for designing and building LunaBlue.

## Goals

- **Local first.** The assistant is built around a locally running LLM (`llama.cpp`), keeping prompts, responses, and data private and self-contained.
- **Companion, not just a chatbot.** The LLM coordinates work — planning, spawning background agents, and resolving tasks — rather than only generating direct answers.
- **One self-contained service.** A single FastAPI process serves the React UI, runs LangGraph orchestration, and executes the model in-process.
- **Live and transparent.** Runtime state is pushed to the UI over WebSockets, so users can watch prompts, agents, and progress in real time.
- **Auditable by design.** Every prompt request, reviewed prompt, response, and governance decision is persisted to Postgres for traceability.

## Architecture at a glance

| Piece | Technology | Role |
|---|---|---|
| Frontend | React (Vite) | Chat UI, agent status, live progress |
| Backend | Python + FastAPI | Serves the UI, APIs, and WebSockets |
| Orchestration | LangGraph | Main request graph and background agent subgraphs |
| Model runtime | `llama-cpp-python` | Single in-process local LLM instance |
| State | In-memory | Session, graph, and agent state, streamed to the UI |
| Audit | Postgres | Durable log of prompts, responses, and decisions |

How a request flows: the user submits a prompt in the React UI → FastAPI ingests, governs, and logs it → the LangGraph orchestrator runs prompt engineering, LLM review, and any agent spawning in-process → live state streams to the UI over WebSockets → the response and audit trail are persisted to Postgres.

## Documentation

- [Architecture.md](Architecture.md) — full system architecture, directory structure, and design principles.
- [BuildPlan.md](BuildPlan.md) — the 18-step incremental plan for building the solution to full capability.
- [Steps/](Steps/README.md) — a detailed, ready-to-use LLM prompt for executing each build plan step.
- [Components/API.md](Components/API.md) — the FastAPI service, LangGraph orchestration, and local LLM loop.
- [Components/WEB.md](Components/WEB.md) — the React frontend.
- [Components/AUDIT.md](Components/AUDIT.md) — the Postgres log/audit store.
- [DataRetention.md](DataRetention.md) — data retention and privacy safeguards: audit redaction and per-table retention windows.

## License

This project is licensed under the terms of the repository [LICENSE](../LICENSE).
