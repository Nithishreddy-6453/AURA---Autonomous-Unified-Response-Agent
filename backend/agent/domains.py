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
    "When requested to inspect the CURRENT or LIVE onboarding status or checklist of an employee (especially read-only tasks), you MUST navigate to the HR Portal at http://localhost:3002/hr and read the live portal table state using browser_read (e.g. selector='#employee-table' or selector=\"#employee-table tr[data-employee-id='<ID>']\") or table search filtering. You may read the entire #employee-table and identify the employee from the returned text; do not invent unsupported selectors. Static company files may help identify an employee, but must NEVER be treated as proof of live status when the user asks for current portal state.",
    "For read-only inspection tasks (e.g. goals mentioning 'read-only', 'inspect only', 'view only', or 'do not modify'), strictly avoid modifying records: do NOT click '+ New Onboarding Request' ('#new-onboarding-link'), do NOT navigate to '/hr/onboarding/new', and do NOT click '#finalize-onboarding-btn'. Report discrepancies between employee status and individual checklist items factually as observed instead of inventing explanations.",
    "For authorized onboarding creation/mutation tasks, inspect company onboarding documents (e.g. data/company/onboarding/...) to extract authoritative candidate details, then fill in form fields using browser_type on input targets ('employee_id', 'name', 'department', 'start_date').",
    "Mark or toggle required onboarding checklist checkboxes before submitting.",
    "For submitting or finalizing an onboarding form, click the submit button (e.g. text='Finalize Onboarding' or selector='#finalize-onboarding-btn').",
    "Submitting or finalizing an employee onboarding record is a SENSITIVE operation that requires human approval before completion.",
    "After submission, verify the onboarding record exists and matches authoritative details in the portal before declaring task completion.",
]

def is_hr_read_only_task(task: Optional[Any]) -> bool:
    """Identifies whether an HR task is strictly a read-only inspection task."""
    if not task:
        return False
    if isinstance(task, dict):
        meta = task.get("metadata", task)
        if not isinstance(meta, dict):
            meta = task
        goal = str(task.get("user_goal") or task.get("goal") or meta.get("user_goal") or meta.get("goal") or "").lower()
    else:
        meta = getattr(task, "metadata", {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        goal = str(getattr(task, "user_goal", "") or "").lower()

    if meta.get("read_only") is True:
        return True
    if meta.get("mutation") is False:
        return True
    if str(meta.get("intent", "")).lower() in ("read_only", "inspect", "view", "inspection"):
        return True
    if str(meta.get("mode", "")).lower() in ("read_only", "inspect", "inspection"):
        return True
    if str(meta.get("action_type", "")).lower() in ("read_only", "inspect"):
        return True

    # Check negative mutation markers first (if goal explicitly asks to finalize/complete, not read-only unless negated)
    has_mutation_goal = any(m in goal for m in ("finalize", "complete onboarding", "submit onboarding", "create onboarding"))
    has_negation = any(neg in goal for neg in ("do not", "don't", "read-only", "read only", "without modifying", "inspect only"))
    if has_mutation_goal and not has_negation:
        return False

    read_only_markers = [
        "read-only",
        "read only",
        "inspect only",
        "view only",
        "do not modify",
        "do not submit",
        "do not change",
        "do not click any completion buttons",
        "without modifying",
        "inspect its current status",
        "inspect current status",
        "check current status",
        "view current status",
        "current onboarding status",
        "live onboarding status",
        "inspect the current",
        "inspect current",
        "live portal state",
    ]
    return any(marker in goal for marker in read_only_markers)


def _is_hr_read_only_mutation(task: Optional[Any], action: Action, tool: Optional[Any]) -> bool:
    """Blocks mutating actions when the task intent is strictly read-only."""
    if not is_hr_read_only_task(task):
        return False
    if action.tool_name in ("finalize_onboarding", "submit_onboarding", "create_onboarding", "update_onboarding"):
        return True
    args = action.arguments or {}
    text = str(args.get("text", "")).lower()
    selector = str(args.get("selector", "")).lower()
    target = str(args.get("target", "")).lower()
    url = str(args.get("url", "")).lower()
    combined = f"{text} {selector} {target} {url}"
    if "finalize-onboarding-btn" in combined:
        return True
    if "finalize" in combined and "onboarding" in combined:
        return True
    if "complete onboarding" in combined or "complete checklist" in combined:
        return True
    if "new-onboarding-link" in combined or "+ new onboarding" in combined:
        return True
    if action.tool_name == "browser_navigate" and "/hr/onboarding/new" in url:
        return True
    form_input_targets = {"employee_id", "name", "department", "start_date", "role", "notes"}
    if action.tool_name == "browser_type":
        if target in form_input_targets or selector in [f"#{t}" for t in form_input_targets]:
            return True
    return False


def _is_hr_finalize_action(task: Optional[Any], action: Action, tool: Optional[Any]) -> bool:
    if action.tool_name in ("finalize_onboarding", "submit_onboarding"):
        return True
    args = action.arguments or {}
    text = str(args.get("text", "")).lower()
    selector = str(args.get("selector", "")).lower()
    target = str(args.get("target", "")).lower()
    combined = f"{text} {selector} {target}"
    return (
        ("finalize" in combined and "onboarding" in combined)
        or "finalize-onboarding-btn" in combined
        or ("complete" in combined and "onboarding" in combined)
        or ("submit" in combined and "onboarding" in combined)
    )


DEFAULT_HR_POLICY_RULES: List[DomainRiskRule] = [
    DomainRiskRule(
        name="hr_read_only_block_mutation",
        risk_level=ActionRisk.DESTRUCTIVE,
        description="Mutating actions are prohibited for read-only HR inspection tasks",
        predicate=_is_hr_read_only_mutation,
    ),
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
