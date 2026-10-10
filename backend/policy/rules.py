"""Domain-specific risk rules and extension interfaces for AURA policy enforcement."""

from dataclasses import dataclass, field
import logging
from typing import Any, Callable, Dict, Optional, Sequence, Set

from backend.models.action import Action
from backend.models.task import Task
from backend.policy.risk import ActionRisk
from backend.tools.base import Tool

logger = logging.getLogger(__name__)

# Strict severity ranking for risk classification levels.
# Higher value indicates higher security restriction.
RISK_SEVERITY: Dict[ActionRisk, int] = {
    ActionRisk.READ: 0,
    ActionRisk.WRITE: 1,
    ActionRisk.SENSITIVE: 2,
    ActionRisk.DESTRUCTIVE: 3,
}


@dataclass
class DomainRiskRule:
    """Type-safe domain-specific risk classification rule.

    Enables extending policy risk classification without modifying core engine logic.
    Can deterministically match actions by:
    - Explicit tool names (matched against action.tool_name)
    - Declared tool capabilities (matched against tool.capabilities)
    - Keywords in tool name or arguments
    - Optional custom inspection predicate
    """

    name: str
    risk_level: ActionRisk = ActionRisk.SENSITIVE
    description: str = ""
    tool_names: Set[str] = field(default_factory=set)
    capabilities: Set[str] = field(default_factory=set)
    keywords: Set[str] = field(default_factory=set)
    predicate: Optional[Callable[[Task, Action, Optional[Tool]], bool]] = None

    def __post_init__(self) -> None:
        """Safely normalizes matching collections into lowercase sets."""
        if isinstance(self.tool_names, (list, tuple, set)):
            self.tool_names = {str(t).strip().lower() for t in self.tool_names if str(t).strip()}
        else:
            self.tool_names = set()

        if isinstance(self.capabilities, (list, tuple, set)):
            self.capabilities = {str(c).strip().lower() for c in self.capabilities if str(c).strip()}
        else:
            self.capabilities = set()

        if isinstance(self.keywords, (list, tuple, set)):
            self.keywords = {str(k).strip().lower() for k in self.keywords if str(k).strip()}
        else:
            self.keywords = set()

    def matches(
        self,
        task: Optional[Task],
        action: Action,
        tool: Optional[Tool] = None,
    ) -> bool:
        """Deterministically evaluates whether this rule applies to the given action.

        Matching priority:
        1. Explicit tool name (case-insensitive)
        2. Declared tool capabilities (case-insensitive)
        3. Keywords in tool name or arguments (case-insensitive)
        4. Optional custom inspection predicate
        """
        # 1. Match by explicit tool name
        if self.tool_names:
            if action.tool_name.lower() in self.tool_names:
                return True


        # 2. Match by declared tool capabilities
        if self.capabilities and tool is not None:
            tool_caps = {str(c).lower() for c in getattr(tool, "capabilities", [])}
            if any(c in tool_caps for c in self.capabilities):
                return True

        # 3. Match by keywords in tool name or stringified arguments
        if self.keywords:
            tool_name_lower = action.tool_name.lower()
            if any(k in tool_name_lower for k in self.keywords):
                return True
            args_str = str(action.arguments).lower()
            if any(k in args_str for k in self.keywords):
                return True

        # 4. Match by custom inspection predicate
        if self.predicate is not None:
            try:
                if self.predicate(task, action, tool):
                    return True
            except Exception as e:
                logger.warning(
                    f"[POLICY] Domain risk rule '{self.name}' predicate evaluation error: {e}"
                )
                return False

        return False
