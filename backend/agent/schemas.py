from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PlanActionSchema(BaseModel):
    """Structured representation of an action in a generated plan."""

    tool_name: str = Field(description="Name of the registered tool to execute.")
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments passed to the tool conforming to its schema.",
    )


class PlanResponseSchema(BaseModel):
    """Structured output expected from the planning LLM."""

    goal: str = Field(description="The goal or summarized objective of the plan.")
    actions: List[PlanActionSchema] = Field(
        default_factory=list,
        description="Ordered list of actions to execute.",
    )
    is_feasible: bool = Field(
        default=True,
        description="False if the task cannot be fulfilled with available tools.",
    )
    unsupported_reason: Optional[str] = Field(
        default=None,
        description="Explanation if the task cannot be planned due to missing tools.",
    )


class PlanningResult(BaseModel):
    """Internal result wrapper for the planner's operation."""

    success: bool
    plan_id: Optional[str] = None
    goal: Optional[str] = None
    actions: List[PlanActionSchema] = Field(default_factory=list)
    error: Optional[str] = None
