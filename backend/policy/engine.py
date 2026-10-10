import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from backend.models.action import Action
from backend.models.task import Task
from backend.policy.decision import PolicyDecision
from backend.policy.risk import ActionRisk
from backend.policy.rules import DomainRiskRule, RISK_SEVERITY
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

    Supports extensible domain risk rules that can elevate action risk levels,
    while strictly preventing any downgrading of existing built-in safety rules.
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
        domain_rules: Optional[Sequence[DomainRiskRule]] = None,
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
        self.domain_rules: List[DomainRiskRule] = list(domain_rules) if domain_rules is not None else []

    def register_rule(self, rule: DomainRiskRule) -> None:
        """Registers an additional domain-specific risk rule."""
        if not isinstance(rule, DomainRiskRule):
            raise TypeError(f"Expected DomainRiskRule instance, got {type(rule).__name__}")
        self.domain_rules.append(rule)

    def register_rules(self, rules: Sequence[DomainRiskRule]) -> None:
        """Registers multiple domain-specific risk rules."""
        for r in rules:
            self.register_rule(r)

    def evaluate(
        self,
        task: Task,
        action: Action,
        tool: Optional[Tool] = None,
    ) -> PolicyDecision:
        """Evaluates an action against safety rules prior to tool execution."""
        # 1. Block unknown or unregistered tools first (conservative security)
        if tool is None:
            return PolicyDecision(
                allowed=False,
                requires_human=False,
                blocked=True,
                risk_level=ActionRisk.DESTRUCTIVE,
                reason=f"Tool '{action.tool_name}' is not registered or permitted in this environment.",
                metadata={"action_id": action.action_id, "tool_name": action.tool_name},
            )

        # 2. Classify risk level based on tool metadata, action context, and domain rules
        risk_level, rule_reason = self._classify_action_risk_with_details(action, tool, task)

        # 3. Check if human approval was already granted and binds to exact action identity
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

        # 4. Optional custom matcher hook (with strict non-downgrade enforcement)
        if self.custom_matcher:
            custom_decision = self.custom_matcher(task, action, tool)
            if custom_decision is not None:
                custom_sev = RISK_SEVERITY.get(custom_decision.risk_level, 0)
                effective_sev = RISK_SEVERITY.get(risk_level, 0)
                if custom_sev < effective_sev:
                    logger.warning(
                        f"[POLICY] Custom matcher attempted to downgrade risk from {risk_level.value} "
                        f"to {custom_decision.risk_level.value}. Downgrade rejected."
                    )
                elif risk_level == ActionRisk.DESTRUCTIVE and not custom_decision.blocked:
                    logger.warning(
                        f"[POLICY] Custom matcher attempted to permit DESTRUCTIVE action '{action.tool_name}'. "
                        "Permit rejected."
                    )
                elif risk_level == ActionRisk.SENSITIVE and custom_decision.allowed and not is_approved:
                    logger.warning(
                        f"[POLICY] Custom matcher attempted to bypass human approval for SENSITIVE action '{action.tool_name}'. "
                        "Bypass rejected."
                    )
                else:
                    return custom_decision

        # 5. Apply risk-level policy rules
        if risk_level == ActionRisk.DESTRUCTIVE:
            reason = (
                f"Destructive action '{action.tool_name}' is blocked by safety policy ({rule_reason})."
                if rule_reason
                else f"Destructive action '{action.tool_name}' is blocked by safety policy."
            )
            return PolicyDecision(
                allowed=False,
                requires_human=False,
                blocked=True,
                risk_level=ActionRisk.DESTRUCTIVE,
                reason=reason,
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
            reason = (
                f"Action '{action.tool_name}' is classified as SENSITIVE ({rule_reason}) and requires human approval."
                if rule_reason
                else f"Action '{action.tool_name}' is classified as SENSITIVE and requires human approval."
            )
            return PolicyDecision(
                allowed=False,
                requires_human=True,
                blocked=False,
                risk_level=ActionRisk.SENSITIVE,
                reason=reason,
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

    def _classify_builtin_risk(self, action: Action, tool: Tool) -> ActionRisk:
        """Determines the baseline risk level of an action using core built-in rules."""
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

    def _classify_action_risk_with_details(
        self,
        action: Action,
        tool: Tool,
        task: Optional[Task] = None,
    ) -> Tuple[ActionRisk, Optional[str]]:
        """Determines effective risk level and matching rule details.

        Evaluates built-in rules followed by domain rules. Additional domain
        rules may elevate risk, but can never downgrade risk.
        """
        builtin_risk = self._classify_builtin_risk(action, tool)
        effective_risk = builtin_risk
        matched_rule_detail: Optional[str] = None
        highest_severity = RISK_SEVERITY[builtin_risk]

        for rule in self.domain_rules:
            if rule.matches(task, action, tool):
                rule_sev = RISK_SEVERITY.get(rule.risk_level, 0)
                if rule_sev > highest_severity:
                    highest_severity = rule_sev
                    effective_risk = rule.risk_level
                    matched_rule_detail = rule.description or f"Rule '{rule.name}'"

        return effective_risk, matched_rule_detail

    def _classify_action_risk(
        self,
        action: Action,
        tool: Tool,
        task: Optional[Task] = None,
    ) -> ActionRisk:
        """Determines the effective risk level of an action given the tool, arguments, and domain rules."""
        risk_level, _ = self._classify_action_risk_with_details(action, tool, task)
        return risk_level
