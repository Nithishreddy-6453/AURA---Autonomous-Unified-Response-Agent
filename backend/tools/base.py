from abc import ABC, abstractmethod
from typing import Any, Dict
from pydantic import BaseModel, Field

from backend.models.observation import Observation


class ToolParameterSchema(BaseModel):
    """Schema descriptor for a tool's expected input."""

    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class Tool(ABC):
    """Abstract interface defining a tool capability.

    LLM = reasoning/decision layer
    Runtime = execution control
    Tools = capabilities
    Environment = source of observations

    No LLM calls should ever be placed inside tools.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier of the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human and LLM-readable description of what the tool accomplishes."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        """JSON Schema dictionary describing the accepted arguments."""
        pass

    @property
    def risk_level(self) -> "ActionRisk":
        """Base risk classification of the tool (defaults to READ)."""
        from backend.policy.risk import ActionRisk
        return ActionRisk.READ

    @property
    def capabilities(self) -> list[str]:
        """Declared functional capabilities provided by this tool."""
        return []

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Observation:
        """Execute the tool action and return an Observation."""
        pass
