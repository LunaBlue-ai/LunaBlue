"""Background agent subgraphs (Step 14).

Each module implements one agent kind on the contract in :mod:`.base`;
``BUILTIN_AGENT_TYPES`` is the default kind → class registry the
:class:`~app.orchestration.runner.AgentRunner` executes from.
"""

from app.orchestration.agents.base import BackgroundAgent
from app.orchestration.agents.research import ResearchAgent

BUILTIN_AGENT_TYPES: dict[str, type[BackgroundAgent]] = {
    ResearchAgent.kind: ResearchAgent,
}
