import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Set

from backend.models.action import Action
from backend.models.task import Task
from backend.policy.decision import PolicyDecision
from backend.policy.risk import ActionRisk
from backend.tools.base import Tool

logger = logging.getLogger(__name__)


def compute_action_fingerprint(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
    """Computes a deterministic SHA-256 fingerprint for a tool name and canonicalized arguments.

    Arguments are serialized with sorted keys and normalized separators so dictionary key order
    does not affect the fingerprint.
    """
    canonical_json = json.dumps(
        arguments or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    payload = f"{tool_name}:{canonical_json}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ActionPolicy(ABC):
    """Abstract interface defining the centralized safety and action policy enforcement engine."""

    @abstractmethod
    def evaluate(
        self,
        task: Task,
        action: Action,
        tool: Optional[Tool] = None,
    ) -> PolicyDecision:
        """Evaluates whether the requested action is permitted, blocked, or requires human approval."""
        pass


class DefaultActionPolicy(ActionPolicy):
    """Conservative default safety and action policy for AURA.

    Enforces:
    - READ actions: ALLOWED
    - Ordinary data-entry WRITE actions: ALLOWED (in local sandbox)
    - SENSITIVE actions: REQUIRES_HUMAN approval
    - DESTRUCTIVE actions: BLOCKED
    - Unknown or unregistered tools: BLOCKED
    """

    DEFAULT_DESTRUCTIVE_KEYWORDS: Set[str] = {
        "delete",
        "drop",
        "truncate",
        "destroy",
        "purge",
        "remove_database",
        "wipe",
    }

    DEFAULT_SENSITIVE_KEYWORDS: Set[str] = {
        "payment",
        "wire_transfer",
        "authorize",
        "sensitive_submit",
        "execute_transfer",
    }

    def __init__(
        self,
        sensitive_tools: Optional[Set[str]] = None,
        destructive_tools: Optional[Set[str]] = None,
        sensitive_keywords: Optional[Set[str]] = None,
        destructive_keywords: Optional[Set[str]] = None,
        custom_matcher: Optional[Callable[[Task, Action, Optional[Tool]], Optional[PolicyDecision]]] = None,
    ) -> None:
        self.sensitive_tools: Set[str] = sensitive_tools or set()
        self.destructive_tools: Set[str] = destructive_tools or set()
        self.sensitive_keywords: Set[str] = (
            sensitive_keywords or self.DEFAULT_SENSITIVE_KEYWORDS
        )
        self.destructive_keywords: Set[str] = (
            destructive_keywords or self.DEFAULT_DESTRUCTIVE_KEYWORDS
        )
        self.custom_matcher = custom_matcher

    def evaluate(
        self,
        task: Task,
        action: Action,
        tool: Optional[Tool] = None,
    ) -> PolicyDecision:
        """Evaluates an action against safety rules prior to tool execution."""
        # 1. Allow optional custom matcher to override or customize
        if self.custom_matcher:
            custom_decision = self.custom_matcher(task, action, tool)
            if custom_decision is not None:
                return custom_decision

        # 2. Block unknown or unregistered tools
        if tool is None:
            return PolicyDecision(
                allowed=False,
                requires_human=False,
                blocked=True,
                risk_level=ActionRisk.DESTRUCTIVE,
                reason=f"Tool '{action.tool_name}' is not registered or permitted in this environment.",
                metadata={"action_id": action.action_id, "tool_name": action.tool_name},
            )

        # 3. Classify risk level based on tool metadata and action context
        risk_level = self._classify_action_risk(action, tool)

        # 4. Check if human approval was already granted and binds to exact action identity
        action_fp = compute_action_fingerprint(action.tool_name, action.arguments)
        approved_fp = task.metadata.get("approved_action_fingerprint")

        is_consumed = task.metadata.get("approval_consumed", False)
        is_approved = False
        if task.metadata.get("approval_status") == "APPROVED" and not is_consumed:
            if approved_fp:
                if approved_fp == action_fp:
                    is_approved = True
                else:
                    logger.warning(
                        f"[APPROVAL] Fingerprint mismatch! Action '{action.tool_name}' with args {action.arguments} "
                        f"produced fingerprint '{action_fp}', which does not match approved '{approved_fp}'. "
                        "Authorization invalidated."
                    )
            elif (
                task.metadata.get("approved_action_id") == action.action_id
                or task.metadata.get("approved_tool_name") == action.tool_name
            ):
                is_approved = True

        # 5. Apply risk-level policy rules
        if risk_level == ActionRisk.DESTRUCTIVE:
            return PolicyDecision(
                allowed=False,
                requires_human=False,
                blocked=True,
                risk_level=ActionRisk.DESTRUCTIVE,
                reason=f"Destructive action '{action.tool_name}' is blocked by safety policy.",
                metadata={"action_id": action.action_id, "tool_name": action.tool_name},
            )

        if risk_level == ActionRisk.SENSITIVE:
            if is_approved:
                return PolicyDecision(
                    allowed=True,
                    requires_human=False,
                    blocked=False,
                    risk_level=ActionRisk.SENSITIVE,
                    reason=f"Sensitive action '{action.tool_name}' permitted following human approval.",
                    metadata={"action_id": action.action_id, "approved": True},
                )
            return PolicyDecision(
                allowed=False,
                requires_human=True,
                blocked=False,
                risk_level=ActionRisk.SENSITIVE,
                reason=f"Action '{action.tool_name}' is classified as SENSITIVE and requires human approval.",
                metadata={"action_id": action.action_id, "tool_name": action.tool_name},
            )

        if risk_level == ActionRisk.WRITE:
            return PolicyDecision(
                allowed=True,
                requires_human=False,
                blocked=False,
                risk_level=ActionRisk.WRITE,
                reason="Standard data-entry write action permitted in sandbox environment.",
                metadata={"action_id": action.action_id},
            )

        # Default READ
        return PolicyDecision(
            allowed=True,
            requires_human=False,
            blocked=False,
            risk_level=ActionRisk.READ,
            reason="Read-only action permitted.",
            metadata={"action_id": action.action_id},
        )

    def _classify_action_risk(self, action: Action, tool: Tool) -> ActionRisk:
        """Determines the effective risk level of an action given the tool and its arguments."""
        tool_name_lower = action.tool_name.lower()

        # Check explicit destructive tool declaration or destructive keywords
        if (
            action.tool_name in self.destructive_tools
            or getattr(tool, "risk_level", None) == ActionRisk.DESTRUCTIVE
            or any(dk in tool_name_lower for dk in self.destructive_keywords)
        ):
            return ActionRisk.DESTRUCTIVE

        # Check arguments for destructive intent (e.g. target, text, selector)
        args_str = str(action.arguments).lower()
        if any(dk in args_str for dk in self.destructive_keywords):
            return ActionRisk.DESTRUCTIVE

        # Check explicit sensitive tool declaration or sensitive keywords
        if (
            action.tool_name in self.sensitive_tools
            or getattr(tool, "risk_level", None) == ActionRisk.SENSITIVE
            or any(sk in tool_name_lower for sk in self.sensitive_keywords)
        ):
            return ActionRisk.SENSITIVE

        # Check arguments for sensitive operations (e.g. payment transfer or explicit sensitivity flag)
        if action.arguments.get("is_sensitive") is True:
            return ActionRisk.SENSITIVE

        for sk in self.sensitive_keywords:
            if sk in args_str:
                return ActionRisk.SENSITIVE

        # Defer to base tool risk level if defined
        tool_risk = getattr(tool, "risk_level", None)
        if tool_risk in (ActionRisk.READ, ActionRisk.WRITE):
            return tool_risk

        return ActionRisk.READ
