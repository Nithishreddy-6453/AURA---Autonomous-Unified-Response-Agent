from typing import Any, Dict
from pydantic import BaseModel, Field

from backend.policy.risk import ActionRisk


class PolicyDecision(BaseModel):
    """Structured decision output from evaluating an action against safety policies."""

    allowed: bool
    requires_human: bool
    blocked: bool
    risk_level: ActionRisk
    reason: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes decision for audit and memory persistence."""
        return {
            "allowed": self.allowed,
            "requires_human": self.requires_human,
            "blocked": self.blocked,
            "risk_level": self.risk_level.value,
            "reason": self.reason,
            "metadata": self.metadata,
        }
