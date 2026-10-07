from backend.agent.state import AgentState
from backend.agent.schemas import PlanActionSchema, PlanResponseSchema, PlanningResult


def __getattr__(name: str):
    if name == "AgentRuntime":
        from backend.agent.runtime import AgentRuntime
        return AgentRuntime
    if name == "Planner":
        from backend.agent.planner import Planner
        return Planner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentState",
    "PlanActionSchema",
    "PlanResponseSchema",
    "PlanningResult",
    "Planner",
    "AgentRuntime",
]
