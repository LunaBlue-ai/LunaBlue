"""The first concrete background agent: multi-step research (Step 14).

A LangGraph subgraph with three sequential nodes::

    START -> decompose -> investigate -> summarize -> END

``decompose`` asks the model to break the task into a few sub-questions,
``investigate`` answers each one in turn, and ``summarize`` synthesizes the
findings into the final result. Every step (and every sub-question inside
``investigate``) reports progress through the context, so the agent exercises
the full live-state/audit progress path while it runs.

All model calls go through :meth:`AgentContext.generate` — the single shared
runtime at background priority — and the prompt templates live in
``app/llm/prompts/research_*.md`` like every other node's. The subgraph is
built per execution with the context bound into the nodes, mirroring how
``build_main_graph`` binds its dependencies.
"""

import re
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from app.llm.runtime import load_system_prompt
from app.orchestration.agents.base import AgentContext, AgentResult, BackgroundAgent

# One leading list marker: "1." / "1)" / "-" / "*".
_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+")

_DEFAULT_MAX_QUESTIONS = 3
# Progress fractions: decompose ends at 0.15, investigation spans up to 0.8,
# summarize claims the rest (completion itself is reported by the runner).
_DECOMPOSE_END = 0.15
_INVESTIGATE_END = 0.8

# Per-step generation params: planning is deterministic and short; answers
# and the summary are bounded so a multi-call agent stays responsive.
_DECOMPOSE_PARAMS: dict[str, Any] = {"temperature": 0.0, "max_tokens": 192}
_INVESTIGATE_PARAMS: dict[str, Any] = {"max_tokens": 256}
_SUMMARIZE_PARAMS: dict[str, Any] = {"max_tokens": 384}


class ResearchState(TypedDict):
    """State carried through the research subgraph."""

    task: str
    questions: NotRequired[list[str]]
    findings: NotRequired[list[dict[str, str]]]
    summary: NotRequired[str]


def parse_sub_questions(text: str, *, limit: int) -> list[str]:
    """Extract the numbered/bulleted sub-questions from model output."""
    questions = []
    for line in text.splitlines():
        stripped = _LIST_MARKER.sub("", line).strip()
        if stripped and _LIST_MARKER.match(line):
            questions.append(stripped)
        if len(questions) >= limit:
            break
    return questions


class ResearchAgent(BackgroundAgent):
    """Decompose a task, investigate each sub-question, summarize findings."""

    kind = "research"

    async def run(self, context: AgentContext) -> AgentResult:
        graph = self._build_graph(context)
        state = await graph.ainvoke({"task": context.spec.task})
        summary = state["summary"]
        return AgentResult(
            summary=summary,
            payload={
                "task": state["task"],
                "questions": state["questions"],
                "findings": state["findings"],
                "summary": summary,
            },
        )

    def _build_graph(self, context: AgentContext):
        """Compile the subgraph with ``context`` bound into the nodes."""
        max_questions = int(
            context.spec.params.get("max_questions", _DEFAULT_MAX_QUESTIONS)
        )

        async def decompose(state: ResearchState) -> dict[str, Any]:
            await context.report_progress(
                "decomposing", fraction=0.0, detail="breaking the task down"
            )
            instructions = load_system_prompt("research_decompose").format(
                max_questions=max_questions
            )
            result = await context.generate(
                f"{instructions}\n\nResearch task:\n---\n{state['task']}\n---",
                **_DECOMPOSE_PARAMS,
            )
            questions = parse_sub_questions(result.text, limit=max_questions)
            if not questions:
                # Unparseable plan: investigate the task itself rather than fail.
                questions = [state["task"]]
            return {"questions": questions}

        async def investigate(state: ResearchState) -> dict[str, Any]:
            questions = state["questions"]
            system = load_system_prompt("research_investigate")
            findings: list[dict[str, str]] = []
            span = _INVESTIGATE_END - _DECOMPOSE_END
            for index, question in enumerate(questions):
                await context.report_progress(
                    "investigating",
                    fraction=_DECOMPOSE_END + span * (index / len(questions)),
                    detail=f"sub-question {index + 1}/{len(questions)}",
                )
                result = await context.generate(
                    f"Research task: {state['task']}\n\nSub-question: {question}",
                    system=system,
                    **_INVESTIGATE_PARAMS,
                )
                findings.append({"question": question, "answer": result.text})
            return {"findings": findings}

        async def summarize(state: ResearchState) -> dict[str, Any]:
            await context.report_progress(
                "summarizing",
                fraction=_INVESTIGATE_END,
                detail="synthesizing findings",
            )
            instructions = load_system_prompt("research_summarize")
            findings = "\n\n".join(
                f"Sub-question: {f['question']}\nFinding: {f['answer']}"
                for f in state["findings"]
            )
            result = await context.generate(
                f"{instructions}\n\nResearch task:\n---\n{state['task']}\n---\n\n"
                f"Findings:\n{findings}",
                **_SUMMARIZE_PARAMS,
            )
            return {"summary": result.text.strip()}

        graph = StateGraph(ResearchState)
        graph.add_node("decompose", decompose)
        graph.add_node("investigate", investigate)
        graph.add_node("summarize", summarize)
        graph.add_edge(START, "decompose")
        graph.add_edge("decompose", "investigate")
        graph.add_edge("investigate", "summarize")
        graph.add_edge("summarize", END)
        return graph.compile()
