"""Regression tests for AURA Phase 6D — Stage 3: Extensible Domain Policy Rules."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from backend.agent.runtime import AgentRuntime
from backend.llm.base import LLMProvider
from backend.memory.sqlite_store import SQLiteMemoryStore
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.policy.decision import PolicyDecision
from backend.policy.engine import (
    ActionPolicy,
    DefaultActionPolicy,
    compute_action_fingerprint,
)
from backend.policy.risk import ActionRisk
from backend.policy.rules import DomainRiskRule, RISK_SEVERITY
from backend.tools.base import Tool
from backend.tools.browser.browser_navigate import is_url_allowed
from backend.tools.registry import ToolRegistry


class DummyMockLLM(LLMProvider):
    """Deterministic mock LLM for policy integration testing."""

    def __init__(self, initial_plan: dict, step_responses: Optional[List[dict]] = None):
        self.initial_plan = initial_plan
        self.step_responses = step_responses or []
        self.step_index = 0

    async def generate(self, prompt: str, system_instruction: Optional[str] = None, **kwargs: Any) -> str:
        import json
        if "Available Tools:" in prompt and "Execution History & Observations:" not in prompt:
            return json.dumps(self.initial_plan)
        if self.step_index < len(self.step_responses):
            resp = self.step_responses[self.step_index]
            self.step_index += 1
            return json.dumps(resp)
        return json.dumps({"is_complete": True, "completion_summary": "Done.", "action": None})

    async def chat(self, messages: list, **kwargs: Any) -> str:
        return await self.generate(messages[-1]["content"])


class MockTestTool(Tool):
    """Configurable mock tool for testing domain policy evaluation."""

    def __init__(
        self,
        name: str,
        risk: ActionRisk = ActionRisk.READ,
        capabilities: Optional[List[str]] = None,
    ):
        self._name = name
        self._risk = risk
        self._capabilities = capabilities or []
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Mock tool {self._name}"

    @property
    def risk_level(self) -> ActionRisk:
        return self._risk

    @property
    def capabilities(self) -> List[str]:
        return self._capabilities

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"target": {"type": "string"}}}

    async def execute(self, **kwargs: Any) -> Observation:
        self.call_count += 1
        return Observation(
            action_id=str(uuid4()),
            success=True,
            result={"output": "ok", "call_count": self.call_count},
        )


class TestDomainPolicyRules(unittest.TestCase):
    """Unit and regression tests for extensible domain policy rules."""

    def setUp(self):
        self.task = Task(user_goal="Test domain policy rules")
        self.default_policy = DefaultActionPolicy()

    def test_default_policy_builtins_unchanged(self):
        """1. Built-in risk classifications remain unchanged when no domain rules are supplied."""
        read_tool = MockTestTool("file_read", risk=ActionRisk.READ)
        write_tool = MockTestTool("file_write", risk=ActionRisk.WRITE)
        sensitive_tool = MockTestTool("authorize_payment", risk=ActionRisk.SENSITIVE)
        destructive_tool = MockTestTool("purge_database", risk=ActionRisk.DESTRUCTIVE)

        # READ allowed
        dec_read = self.default_policy.evaluate(self.task, Action(tool_name="file_read", arguments={}), read_tool)
        self.assertTrue(dec_read.allowed)
        self.assertFalse(dec_read.requires_human)
        self.assertFalse(dec_read.blocked)
        self.assertEqual(dec_read.risk_level, ActionRisk.READ)

        # WRITE allowed
        dec_write = self.default_policy.evaluate(self.task, Action(tool_name="file_write", arguments={}), write_tool)
        self.assertTrue(dec_write.allowed)
        self.assertFalse(dec_write.requires_human)
        self.assertFalse(dec_write.blocked)
        self.assertEqual(dec_write.risk_level, ActionRisk.WRITE)

        # SENSITIVE requires human approval
        dec_sens = self.default_policy.evaluate(self.task, Action(tool_name="authorize_payment", arguments={}), sensitive_tool)
        self.assertFalse(dec_sens.allowed)
        self.assertTrue(dec_sens.requires_human)
        self.assertFalse(dec_sens.blocked)
        self.assertEqual(dec_sens.risk_level, ActionRisk.SENSITIVE)

        # DESTRUCTIVE blocked
        dec_dest = self.default_policy.evaluate(self.task, Action(tool_name="purge_database", arguments={}), destructive_tool)
        self.assertFalse(dec_dest.allowed)
        self.assertFalse(dec_dest.requires_human)
        self.assertTrue(dec_dest.blocked)
        self.assertEqual(dec_dest.risk_level, ActionRisk.DESTRUCTIVE)

        # Unregistered tool blocked
        dec_unreg = self.default_policy.evaluate(self.task, Action(tool_name="unknown_tool", arguments={}), None)
        self.assertFalse(dec_unreg.allowed)
        self.assertTrue(dec_unreg.blocked)

    def test_financial_risk_rules_continue_working(self):
        """2. Existing financial risk rules and keywords continue functioning."""
        tool = MockTestTool("bank_tool", risk=ActionRisk.READ)

        # Sensitive keyword in tool name
        dec1 = self.default_policy.evaluate(
            self.task,
            Action(tool_name="wire_transfer_funds", arguments={}),
            tool,
        )
        self.assertEqual(dec1.risk_level, ActionRisk.SENSITIVE)
        self.assertTrue(dec1.requires_human)

        # Sensitive keyword in arguments
        dec2 = self.default_policy.evaluate(
            self.task,
            Action(tool_name="bank_tool", arguments={"method": "payment"}),
            tool,
        )
        self.assertEqual(dec2.risk_level, ActionRisk.SENSITIVE)
        self.assertTrue(dec2.requires_human)

        # Explicit is_sensitive flag
        dec3 = self.default_policy.evaluate(
            self.task,
            Action(tool_name="bank_tool", arguments={"is_sensitive": True}),
            tool,
        )
        self.assertEqual(dec3.risk_level, ActionRisk.SENSITIVE)
        self.assertTrue(dec3.requires_human)

    def test_custom_domain_rule_by_tool_name(self):
        """3. A custom domain rule can identify a configured high-risk action by explicit tool name."""
        rule = DomainRiskRule(
            name="payroll_export_sensitive",
            risk_level=ActionRisk.SENSITIVE,
            description="Payroll export requires human confirmation",
            tool_names={"export_payroll_summary"},
        )
        policy = DefaultActionPolicy(domain_rules=[rule])
        tool = MockTestTool("export_payroll_summary", risk=ActionRisk.READ)
        action = Action(tool_name="export_payroll_summary", arguments={"department": "Engineering"})

        decision = policy.evaluate(self.task, action, tool)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_human)
        self.assertEqual(decision.risk_level, ActionRisk.SENSITIVE)
        self.assertIn("Payroll export requires human confirmation", decision.reason)

    def test_custom_domain_rule_by_tool_capability(self):
        """4. A custom domain rule can identify actions matching declared tool capabilities."""
        rule = DomainRiskRule(
            name="crm_bulk_delete_destructive",
            risk_level=ActionRisk.DESTRUCTIVE,
            description="CRM bulk deletions are prohibited",
            capabilities={"crm_bulk_remove"},
        )
        policy = DefaultActionPolicy(domain_rules=[rule])
        tool = MockTestTool(
            "crm_tool",
            risk=ActionRisk.WRITE,
            capabilities=["crm_bulk_remove", "reporting"],
        )
        action = Action(tool_name="crm_tool", arguments={"ids": [1, 2, 3]})

        decision = policy.evaluate(self.task, action, tool)
        self.assertTrue(decision.blocked)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk_level, ActionRisk.DESTRUCTIVE)
        self.assertIn("CRM bulk deletions are prohibited", decision.reason)

    def test_custom_domain_rule_by_keyword(self):
        """5. A custom domain rule can identify actions matching keyword patterns."""
        rule = DomainRiskRule(
            name="offboarding_sensitive",
            risk_level=ActionRisk.SENSITIVE,
            description="Employee offboarding requires approval",
            keywords={"offboard", "deprovision"},
        )
        policy = DefaultActionPolicy(domain_rules=[rule])
        tool = MockTestTool("user_management", risk=ActionRisk.WRITE)
        action = Action(tool_name="user_management", arguments={"intent": "offboard_employee", "user_id": 42})

        decision = policy.evaluate(self.task, action, tool)
        self.assertTrue(decision.requires_human)
        self.assertEqual(decision.risk_level, ActionRisk.SENSITIVE)
        self.assertIn("Employee offboarding requires approval", decision.reason)

    def test_deterministic_matching_and_case_insensitivity(self):
        """6. Rule matching is deterministic and case-insensitive across names, capabilities, and keywords."""
        rule = DomainRiskRule(
            name="mixed_case_rule",
            risk_level=ActionRisk.SENSITIVE,
            tool_names={"Custom_Action_Tool"},
            capabilities={"CRM_CAPABILITY"},
            keywords={"Sensitive_Token"},
        )
        self.assertIn("custom_action_tool", rule.tool_names)
        self.assertIn("crm_capability", rule.capabilities)
        self.assertIn("sensitive_token", rule.keywords)

        # Matches tool name in different case
        tool1 = MockTestTool("custom_action_tool", risk=ActionRisk.READ)
        self.assertTrue(rule.matches(self.task, Action(tool_name="CUSTOM_ACTION_TOOL", arguments={}), tool1))

        # Matches capability in different case
        tool2 = MockTestTool("other_tool", risk=ActionRisk.READ, capabilities=["crm_capability"])
        self.assertTrue(rule.matches(self.task, Action(tool_name="other_tool", arguments={}), tool2))

        # Matches keyword in arguments in different case
        tool3 = MockTestTool("third_tool", risk=ActionRisk.READ)
        self.assertTrue(rule.matches(self.task, Action(tool_name="third_tool", arguments={"val": "SENSITIVE_TOKEN"}), tool3))

    def test_additional_rules_cannot_downgrade_existing_risk(self):
        """7. Additional domain rules can never downgrade an existing risk classification."""
        # Rule that tries to classify everything as READ
        attempted_downgrade_rule = DomainRiskRule(
            name="attempt_downgrade",
            risk_level=ActionRisk.READ,
            tool_names={"delete_all_records", "authorize_invoice_payment"},
            keywords={"delete", "payment"},
        )
        policy = DefaultActionPolicy(
            destructive_tools={"delete_all_records"},
            sensitive_tools={"authorize_invoice_payment"},
            domain_rules=[attempted_downgrade_rule],
        )

        dest_tool = MockTestTool("delete_all_records", risk=ActionRisk.DESTRUCTIVE)
        sens_tool = MockTestTool("authorize_invoice_payment", risk=ActionRisk.SENSITIVE)

        # Destructive action MUST NOT be downgraded to READ or WRITE
        dec_dest = policy.evaluate(self.task, Action(tool_name="delete_all_records", arguments={}), dest_tool)
        self.assertTrue(dec_dest.blocked)
        self.assertEqual(dec_dest.risk_level, ActionRisk.DESTRUCTIVE)

        # Sensitive action MUST NOT be downgraded to READ or WRITE
        dec_sens = policy.evaluate(self.task, Action(tool_name="authorize_invoice_payment", arguments={}), sens_tool)
        self.assertTrue(dec_sens.requires_human)
        self.assertFalse(dec_sens.allowed)
        self.assertEqual(dec_sens.risk_level, ActionRisk.SENSITIVE)

    def test_destructive_action_cannot_become_permitted(self):
        """8. Destructive action cannot become permitted under any custom rule configuration."""
        destructive_rule = DomainRiskRule(
            name="destructive_rule",
            risk_level=ActionRisk.DESTRUCTIVE,
            tool_names={"wipe_all_data"},
        )
        policy = DefaultActionPolicy(domain_rules=[destructive_rule])
        tool = MockTestTool("wipe_all_data", risk=ActionRisk.WRITE)
        action = Action(tool_name="wipe_all_data", arguments={})

        decision = policy.evaluate(self.task, action, tool)
        self.assertTrue(decision.blocked)
        self.assertFalse(decision.allowed)
        self.assertFalse(decision.requires_human)

    def test_approval_fingerprint_mismatch_handling_remains_unchanged(self):
        """9. Approval fingerprint mismatch handling continues to invalidate authorization."""
        rule = DomainRiskRule(
            name="sensitive_rule",
            risk_level=ActionRisk.SENSITIVE,
            tool_names={"execute_payout"},
        )
        policy = DefaultActionPolicy(domain_rules=[rule])
        tool = MockTestTool("execute_payout", risk=ActionRisk.READ)

        # Approved with different arguments
        fp_original = compute_action_fingerprint("execute_payout", {"amount": 500})
        task_with_approval = Task(
            user_goal="Payout task",
            metadata={
                "approval_status": "APPROVED",
                "approved_action_fingerprint": fp_original,
                "approval_consumed": False,
            },
        )

        # Tampered action arguments
        tampered_action = Action(tool_name="execute_payout", arguments={"amount": 50000})
        decision = policy.evaluate(task_with_approval, tampered_action, tool)

        # Authorization invalidated due to fingerprint mismatch -> remains SENSITIVE requiring human
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_human)

    def test_browser_origin_and_port_restrictions_preserved(self):
        """10. Browser security restrictions on URLs and ports remain intact."""
        self.assertTrue(is_url_allowed("http://localhost:3000/finance"))
        self.assertTrue(is_url_allowed("http://127.0.0.1:3000/finance/invoices"))
        self.assertFalse(is_url_allowed("http://malicious.external.com/evil"))
        self.assertFalse(is_url_allowed("http://localhost:9999/unauthorized"))
        self.assertFalse(is_url_allowed("javascript:alert(1)"))

    def test_empty_custom_rule_preserves_default_behavior(self):
        """11. Explicitly providing domain_rules=[] preserves exact default policy behavior."""
        empty_policy = DefaultActionPolicy(domain_rules=[])
        read_tool = MockTestTool("read_tool", risk=ActionRisk.READ)
        action = Action(tool_name="read_tool", arguments={})

        decision = empty_policy.evaluate(self.task, action, read_tool)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.risk_level, ActionRisk.READ)
        self.assertEqual(len(empty_policy.domain_rules), 0)

    def test_register_rule_methods(self):
        """12. register_rule and register_rules dynamically add domain rules."""
        policy = DefaultActionPolicy()
        self.assertEqual(len(policy.domain_rules), 0)

        r1 = DomainRiskRule(name="r1", risk_level=ActionRisk.SENSITIVE, tool_names={"t1"})
        r2 = DomainRiskRule(name="r2", risk_level=ActionRisk.DESTRUCTIVE, tool_names={"t2"})

        policy.register_rule(r1)
        self.assertEqual(len(policy.domain_rules), 1)

        policy.register_rules([r2])
        self.assertEqual(len(policy.domain_rules), 2)

        with self.assertRaises(TypeError):
            policy.register_rule("not_a_rule")  # type: ignore


class TestRuntimeDomainPolicyIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests verifying domain policy rule propagation into AgentRuntime."""

    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_memory.db"
        self.memory = SQLiteMemoryStore(db_path=self.db_path)
        self.registry = ToolRegistry()

        self.custom_tool = MockTestTool("custom_crm_export", risk=ActionRisk.READ)
        self.registry.register(self.custom_tool)

    async def asyncTearDown(self):
        self.memory.close()
        self.tmp_dir.cleanup()

    async def test_domain_rules_propagated_to_runtime_and_enforced(self):
        """Domain rules passed to AgentRuntime are enforced during execution lifecycle."""
        domain_rule = DomainRiskRule(
            name="crm_export_requires_approval",
            risk_level=ActionRisk.SENSITIVE,
            description="CRM export requires human approval",
            tool_names={"custom_crm_export"},
        )

        llm = DummyMockLLM(
            initial_plan={
                "goal": "Export CRM contacts",
                "actions": [{"tool_name": "custom_crm_export", "arguments": {"format": "csv"}}],
            }
        )

        runtime = AgentRuntime(
            llm_provider=llm,
            tool_registry=self.registry,
            memory_store=self.memory,
            domain_rules=[domain_rule],
        )

        task = Task(user_goal="Export customer contacts")
        completed_task = await runtime.execute_task(task)

        # Runtime should halt in WAITING_FOR_HUMAN because domain rule elevated READ tool to SENSITIVE
        self.assertEqual(completed_task.status, TaskStatus.WAITING_FOR_HUMAN)
        self.assertEqual(runtime.state, runtime.state.WAITING_FOR_HUMAN)
        self.assertEqual(self.custom_tool.call_count, 0)
        self.assertIn("CRM export requires human approval", completed_task.metadata.get("human_intervention_reason", ""))


if __name__ == "__main__":
    unittest.main()
