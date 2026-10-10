"""Domain definitions and configuration management for AURA.

Provides isolated domain guidelines, domain policy rules, and verifier resolution
per task without cross-task contamination or global state mutation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from backend.agent.planner import DEFAULT_FINANCE_GUIDELINES
from backend.models.action import Action
from backend.policy.risk import ActionRisk
from backend.policy.rules import DomainRiskRule


DEFAULT_HR_GUIDELINES: List[str] = [
    "For HR onboarding tasks, navigate to the local HR Onboarding Portal at http://localhost:3002/hr (or http://localhost:3002/hr/onboarding/new).",
    "Synthetic onboarding records have fields: Employee ID ('employee_id'), Name ('name'), Department ('department'), Start Date ('start_date'), and Checklist items.",
    "First inspect or read company onboarding documents (e.g. data/company/onboarding/...) to extract authoritative candidate details.",
    "Fill in the onboarding form fields accurately using browser_type on input targets ('employee_id', 'name', 'department', 'start_date').",
    "Mark or complete required onboarding checklist items before final submission.",
    "Submitting or finalizing an employee onboarding record is a SENSITIVE operation that requires human approval before completion.",
    "After submission, verify the onboarding record exists and matches authoritative details in the portal before declaring task completion.",
]

def _is_hr_finalize_action(task: Optional[Any], action: Action, tool: Optional[Any]) -> bool:
    if action.tool_name in ("finalize_onboarding", "submit_onboarding"):
        return True
    args = action.arguments or {}
    text = str(args.get("text", "")).lower()
    selector = str(args.get("selector", "")).lower()
    target = str(args.get("target", "")).lower()
    combined = f"{text} {selector} {target}"
    return "finalize" in combined and "onboarding" in combined or "finalize-onboarding-btn" in combined


DEFAULT_HR_POLICY_RULES: List[DomainRiskRule] = [
    DomainRiskRule(
        name="hr_finalize_onboarding",
        risk_level=ActionRisk.SENSITIVE,
        description="Finalizing employee onboarding requires human operator approval",
        tool_names={"finalize_onboarding", "submit_onboarding"},
        keywords={
            "finalize_onboarding",
            "approve_onboarding",
            "complete_onboarding",
            "submit_onboarding",
            "finalize & submit onboarding",
            "finalize onboarding",
            "finalize-onboarding-btn",
        },
        predicate=_is_hr_finalize_action,
    ),
    DomainRiskRule(
        name="hr_bulk_purge_destructive",
        risk_level=ActionRisk.DESTRUCTIVE,
        description="Purging employee onboarding records is prohibited by safety policy",
        tool_names={"purge_employee_records", "delete_onboarding"},
        capabilities={"hr_destructive", "purge_records"},
        keywords={"purge_employee", "delete_employee", "wipe_onboarding"},
    ),
]


@dataclass
class DomainConfig:
    """Configuration for a business domain in AURA."""

    name: str
    display_name: str
    guidelines: List[str]
    policy_rules: List[DomainRiskRule] = field(default_factory=list)


DOMAINS: Dict[str, DomainConfig] = {
    "finance": DomainConfig(
        name="finance",
        display_name="Finance",
        guidelines=list(DEFAULT_FINANCE_GUIDELINES),
        policy_rules=[],  # Finance built-ins handled in DefaultActionPolicy
    ),
    "hr": DomainConfig(
        name="hr",
        display_name="HR Onboarding",
        guidelines=list(DEFAULT_HR_GUIDELINES),
        policy_rules=list(DEFAULT_HR_POLICY_RULES),
    ),
}

SUPPORTED_DOMAINS: Set[str] = set(DOMAINS.keys())
DEFAULT_DOMAIN: str = "finance"


def get_domain_config(domain_name: Optional[str]) -> DomainConfig:
    """Resolves and returns the DomainConfig for the given domain name.

    Defaults to 'finance' if domain_name is None or empty.
    Raises ValueError if domain_name is unrecognized.
    """
    if not domain_name:
        return DOMAINS[DEFAULT_DOMAIN]
    normalized = str(domain_name).strip().lower()
    if normalized not in DOMAINS:
        raise ValueError(
            f"Unsupported domain '{domain_name}'. Supported domains: {sorted(list(SUPPORTED_DOMAINS))}"
        )
    return DOMAINS[normalized]


def validate_domain(domain_name: Optional[str]) -> str:
    """Validates and returns normalized domain string. Defaults to 'finance'."""
    return get_domain_config(domain_name).name
