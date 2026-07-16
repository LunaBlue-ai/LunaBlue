"""The LangGraph main request graph — the orchestration backbone (Step 9).

Every prompt flows through explicit, auditable nodes::

    START -> prompt_engineering -> llm_review -+-> respond -> END
                                               |         ^
                                               +-> agent_spawn (Step 14)

Step 14: when the review decides background work is warranted
(``state["review"]["needs_background_work"]``) and an
:class:`~app.orchestration.runner.AgentRunner` is bound, the conditional edge
detours through ``agent_spawn``, which fires off a background agent and
records its id — the graph then proceeds straight to ``respond``, never
waiting on the agent.

The graph is compiled once at startup (``build_main_graph`` is called from the
pipeline constructed in the ``main.py`` lifespan) with the single global
:class:`~app.llm.runtime.LlamaRuntime` bound into the nodes that generate.
Nodes themselves stay pure functions of ``(state, injected dependencies)`` —
no module-level singletons — so each is individually testable with a fake
runtime and a hand-built state.

Step 10: when a :class:`~app.state.store.StateStore` is supplied, each node is
wrapped so *entering* it advances the run's phase in the store. The wrappers
keep the nodes themselves clean — no node knows the store exists.
"""

import inspect
import operator
from functools import partial
from typing import Annotated, Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from app.governance.policy import GovernanceMetadata
from app.llm.runtime import LlamaRuntime
from app.orchestration.nodes.agent_spawn import spawn_background_agent
from app.orchestration.nodes.llm_review import review_engineered_prompt
from app.orchestration.nodes.prompt_engineering import engineer_prompt
from app.orchestration.nodes.respond import synthesize_response
from app.orchestration.runner import AgentRunner
from app.state.store import StateStore


class MainGraphState(TypedDict):
    """State carried through the main request graph.

    The first block is the pipeline's input; the rest is produced by nodes.
    ``decisions`` accumulates one JSON-safe record per node (what it did,
    its outcome, and timing) — the audit trail's view into the graph.
    """

    request_id: str
    session_id: str
    reviewed_prompt: str
    governance: GovernanceMetadata
    decisions: Annotated[list[dict[str, Any]], operator.add]

    engineered_prompt: NotRequired[str]
    engineered_system: NotRequired[str]
    review: NotRequired[dict[str, Any]]
    spawned_agent_id: NotRequired[str]
    draft_output: NotRequired[str]
    final_output: NotRequired[str]
    model_id: NotRequired[str]
    usage: NotRequired[dict[str, Any]]


# Which store phase entering each node advances the run to.
_NODE_PHASES = {
    "prompt_engineering": "engineering",
    "llm_review": "reviewing",
    "agent_spawn": "spawning",
    "respond": "responding",
}


def _tracked(name: str, fn: Any, store: StateStore):
    """Wrap a node so entering it advances the run's phase in the store.

    The store ignores updates for terminal runs, so a shielded graph run
    abandoned by a timed-out request never resurrects its (already failed)
    run status.
    """
    phase = _NODE_PHASES[name]

    async def wrapper(state: MainGraphState) -> dict[str, Any]:
        await store.update_run_phase(state["request_id"], phase, node=name)
        result = fn(state)
        if inspect.isawaitable(result):
            result = await result
        return result

    return wrapper


def _route_after_review(state: MainGraphState) -> str:
    """Conditional edge: detour through agent_spawn when the review asked
    for background work."""
    review = state.get("review") or {}
    return "agent_spawn" if review.get("needs_background_work") else "respond"


def build_main_graph(
    runtime: LlamaRuntime,
    store: StateStore | None = None,
    runner: AgentRunner | None = None,
):
    """Assemble and compile the main request graph around ``runtime``.

    Pass ``store`` to get phase tracking and ``runner`` to enable the
    agent-spawn detour (production wiring); without a runner the review's
    verdict is recorded but every run goes straight to respond (node-level
    tests, or a deployment with agents disabled).
    """

    def node(name: str, fn: Any) -> Any:
        return fn if store is None else _tracked(name, fn, store)

    graph = StateGraph(MainGraphState)
    graph.add_node("prompt_engineering", node("prompt_engineering", engineer_prompt))
    graph.add_node(
        "llm_review",
        node("llm_review", partial(review_engineered_prompt, llm_runtime=runtime)),
    )
    graph.add_node(
        "respond", node("respond", partial(synthesize_response, llm_runtime=runtime))
    )

    graph.add_edge(START, "prompt_engineering")
    graph.add_edge("prompt_engineering", "llm_review")
    if runner is None:
        graph.add_edge("llm_review", "respond")
    else:
        graph.add_node(
            "agent_spawn",
            node("agent_spawn", partial(spawn_background_agent, runner=runner)),
        )
        graph.add_conditional_edges(
            "llm_review",
            _route_after_review,
            {"agent_spawn": "agent_spawn", "respond": "respond"},
        )
        graph.add_edge("agent_spawn", "respond")
    graph.add_edge("respond", END)
    return graph.compile()
