"""Comprehensive regression tests for AURA Phase 6E — Stage 4: Second-Domain Pilot (HR Onboarding)."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.agent.domains import (
    DEFAULT_DOMAIN,
    DEFAULT_HR_GUIDELINES,
    DEFAULT_HR_POLICY_RULES,
    DOMAINS,
    SUPPORTED_DOMAINS,
    get_domain_config,
    validate_domain,
)
from backend.agent.planner import (
    DEFAULT_FINANCE_GUIDELINES,
    GENERIC_PLANNER_SYSTEM_PROMPT,
    Planner,
)
from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState
from backend.api.main import app, runtime_manager
from backend.api.models import CreateTaskRequest
from backend.llm.base import LLMProvider
from backend.memory.sqlite_store import SQLiteMemoryStore
from backend.models.action import Action, ActionStatus
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.policy.decision import PolicyDecision
from backend.policy.engine import DefaultActionPolicy, compute_action_fingerprint
from backend.policy.risk import ActionRisk
from backend.tools import ToolRegistry, get_default_tool_registry
from backend.tools.base import Tool
from backend.tools.browser.browser_session import BrowserSession
from backend.verification.finance_verifier import FinanceInvoiceVerifier
from backend.verification.hr_verifier import (
    HROnboardingVerifier,
    parse_source_onboarding_document,
)
from backend.verification.registry import VerifierRegistry, get_default_verifier_registry
from backend.verification.verifier import BaseVerifier, VerificationResult


class MockDeterministicLLM(LLMProvider):
    """Predictable deterministic test double simulating autonomous reasoning for tests."""

    def __init__(self, initial_plan: dict, step_responses: list = None):
        self.initial_plan = initial_plan
        self.step_responses = step_responses or []
        self.step_index = 0

    async def generate(self, prompt: str, system_instruction: str = None, temperature: float = 0.0, **kwargs):
        if "Available Tools:" in prompt and "Execution History & Observations:" not in prompt:
            return json.dumps(self.initial_plan)

        if self.step_index < len(self.step_responses):
            step = self.step_responses[self.step_index]
            self.step_index += 1
            return json.dumps(step)

        return json.dumps({
            "is_complete": True,
            "completion_summary": "Task complete.",
            "action": None
        })

    async def chat(self, messages, temperature: float = 0.0, **kwargs):
        return ""


class TestDomainSelectionAndValidation(unittest.TestCase):
    """Tests domain validation, defaulting, and configuration isolation."""

    def setUp(self):
        self.mem_store = SQLiteMemoryStore(":memory:")
        runtime_manager.memory_store = self.mem_store
        runtime_manager.runtimes.clear()
        runtime_manager.background_tasks.clear()
        self.client = TestClient(app)

    def tearDown(self):
        self.mem_store.close()
        runtime_manager.memory_store = SQLiteMemoryStore()
        runtime_manager.runtimes.clear()
        runtime_manager.background_tasks.clear()

    def test_domain_constants_and_registration(self):
        self.assertIn("finance", SUPPORTED_DOMAINS)
        self.assertIn("hr", SUPPORTED_DOMAINS)
        self.assertEqual(DEFAULT_DOMAIN, "finance")

        fin_cfg = get_domain_config("finance")
        self.assertEqual(fin_cfg.name, "finance")
        self.assertEqual(fin_cfg.guidelines, DEFAULT_FINANCE_GUIDELINES)

        hr_cfg = get_domain_config("hr")
        self.assertEqual(hr_cfg.name, "hr")
        self.assertEqual(hr_cfg.guidelines, DEFAULT_HR_GUIDELINES)

    def test_unknown_domain_rejected_by_helper(self):
        with self.assertRaises(ValueError) as ctx:
            validate_domain("marketing")
        self.assertIn("Unsupported domain 'marketing'", str(ctx.exception))

    def test_unknown_domain_rejected_by_api(self):
        response = self.client.post(
            "/api/tasks",
            json={"user_goal": "Process candidate", "domain": "marketing"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("marketing", response.json()["detail"])

    def test_omitted_domain_defaults_to_finance_in_api(self):
        response = self.client.post(
            "/api/tasks",
            json={"user_goal": "Process invoice INV-2026-001"},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        task_id = data["task_id"]
        # Verify persisted task metadata contains domain == 'finance'
        task_resp = self.client.get(f"/api/tasks/{task_id}")
        self.assertEqual(task_resp.status_code, 200)
        self.assertEqual(task_resp.json()["metadata"].get("domain"), "finance")

    def test_explicit_hr_domain_in_api(self):
        response = self.client.post(
            "/api/tasks",
            json={"user_goal": "Onboard HR-TEST-1001", "domain": "hr"},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        task_id = data["task_id"]
        task_resp = self.client.get(f"/api/tasks/{task_id}")
        self.assertEqual(task_resp.status_code, 200)
        self.assertEqual(task_resp.json()["metadata"].get("domain"), "hr")

    def test_persisted_domain_metadata_survives_sqlite_store(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store = SQLiteMemoryStore(db_path=db_path)
            task = Task(user_goal="Process HR record", metadata={"domain": "hr", "custom_key": "val123"})
            store.create_task(task, initial_state=AgentState.RECEIVED)

            reloaded = store.get_task(task.task_id)
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.task.metadata.get("domain"), "hr")
            self.assertEqual(reloaded.task.metadata.get("custom_key"), "val123")
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestPlannerGuidelinesIsolation(unittest.TestCase):
    """Tests that domain guidelines are strictly isolated without cross-contamination."""

    def test_hr_guidelines_contain_hr_not_finance(self):
        hr_cfg = get_domain_config("hr")
        guidelines_text = "\n".join(hr_cfg.guidelines)

        self.assertIn("HR Onboarding Portal", guidelines_text)
        self.assertIn("3002", guidelines_text)
        self.assertIn("employee_id", guidelines_text)

        # Ensure no finance-specific guidelines leaked into HR
        self.assertNotIn("3000/finance/invoices", guidelines_text)
        self.assertNotIn("due_date", guidelines_text)
        self.assertNotIn("Save Invoice", guidelines_text)

    def test_finance_guidelines_contain_finance_not_hr(self):
        fin_cfg = get_domain_config("finance")
        guidelines_text = "\n".join(fin_cfg.guidelines)

        self.assertIn("invoice", guidelines_text.lower())
        self.assertIn("3000/finance", guidelines_text)

        # Ensure no HR-specific guidelines leaked into Finance
        self.assertNotIn("3002", guidelines_text)
        self.assertNotIn("employee_id", guidelines_text)
        self.assertNotIn("checklist", guidelines_text.lower())

    def test_concurrent_or_distinct_planners_maintain_guidelines_isolation(self):
        tool_reg = ToolRegistry()
        mock_llm = MockDeterministicLLM({"goal": "g", "is_feasible": True, "actions": []})

        finance_planner = Planner(mock_llm, tool_reg, domain_guidelines=DEFAULT_FINANCE_GUIDELINES)
        hr_planner = Planner(mock_llm, tool_reg, domain_guidelines=DEFAULT_HR_GUIDELINES)

        fin_prompt = finance_planner.get_effective_planner_system_prompt()
        hr_prompt = hr_planner.get_effective_planner_system_prompt()

        self.assertIn("3000/finance", fin_prompt)
        self.assertNotIn("3002/hr", fin_prompt)

        self.assertIn("3002/hr", hr_prompt)
        self.assertNotIn("3000/finance", hr_prompt)

        # Verify dynamic prompts also strictly isolated
        fin_dyn = finance_planner.get_effective_next_action_system_prompt()
        hr_dyn = hr_planner.get_effective_next_action_system_prompt()
        self.assertIn("Save Invoice", fin_dyn)
        self.assertNotIn("Save Invoice", hr_dyn)
        self.assertIn("employee_id", hr_dyn)
        self.assertNotIn("employee_id", fin_dyn)


class TestVerifierRegistryAndDomainSelection(unittest.TestCase):
    """Tests verifier dispatching and domain isolation."""

    def setUp(self):
        self.registry = get_default_verifier_registry(domain="all")

    def test_registry_has_both_domain_verifiers(self):
        verifier_types = [type(v) for v in self.registry.verifiers]
        self.assertIn(FinanceInvoiceVerifier, verifier_types)
        self.assertIn(HROnboardingVerifier, verifier_types)

    def test_hr_verifier_selected_for_explicit_hr_task(self):
        task = Task(user_goal="Onboard candidate", metadata={"domain": "hr"})
        selected = self.registry.get_verifier(task)
        self.assertIsNotNone(selected)
        self.assertIsInstance(selected, HROnboardingVerifier)

    def test_finance_verifier_selected_for_finance_task(self):
        task = Task(user_goal="Process invoice in finance portal", metadata={"domain": "finance"})
        selected = self.registry.get_verifier(task)
        self.assertIsNotNone(selected)
        self.assertIsInstance(selected, FinanceInvoiceVerifier)

    def test_hr_task_never_claimed_by_finance_verifier_even_with_source_document(self):
        # A task marked domain="hr" that has generic metadata like "source_document"
        task = Task(
            user_goal="Process employee record",
            metadata={"domain": "hr", "source_document": "onboarding_alex_chen.txt"},
        )
        fin_verifier = FinanceInvoiceVerifier()
        self.assertFalse(fin_verifier.can_verify(task))

        # And HR verifier DOES claim it
        hr_verifier = HROnboardingVerifier()
        self.assertTrue(hr_verifier.can_verify(task))

    def test_legacy_task_without_domain_defaults_to_finance(self):
        task = Task(
            user_goal="Process invoice from file",
            metadata={"source_document": "invoices/acme_invoice_2026_01.txt"},
        )
        selected = self.registry.get_verifier(task)
        self.assertIsNotNone(selected)
        self.assertIsInstance(selected, FinanceInvoiceVerifier)


class DummyTool(Tool):
    def __init__(self, name: str, risk: ActionRisk = ActionRisk.READ, capabilities=None):
        self._name = name
        self._risk = risk
        self._capabilities = capabilities or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "mock"

    @property
    def risk_level(self) -> ActionRisk:
        return self._risk

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def input_schema(self):
        return {"type": "object"}

    async def execute(self, **kwargs):
        return Observation(action_id="1", success=True)


class TestHROnboardingPolicyAndApproval(unittest.TestCase):
    """Tests HR domain risk rules, human approval flow, and payload validation."""

    def setUp(self):
        self.policy = DefaultActionPolicy(domain_rules=DEFAULT_HR_POLICY_RULES)
        self.task = Task(user_goal="Onboard employee HR-TEST-1001", metadata={"domain": "hr"})

    def test_sensitive_hr_mutation_requires_human_approval(self):
        finalize_tool = DummyTool("finalize_onboarding", risk=ActionRisk.WRITE)
        action = Action(tool_name="finalize_onboarding", arguments={"employee_id": "HR-TEST-1001"})
        decision = self.policy.evaluate(self.task, action, tool=finalize_tool)
        self.assertTrue(decision.requires_human)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk_level, ActionRisk.SENSITIVE)

        # browser_click with finalize onboarding text
        click_tool = DummyTool("browser_click", risk=ActionRisk.WRITE)
        click_action = Action(
            tool_name="browser_click",
            arguments={"text": "Finalize & Submit Onboarding", "target": "#finalize-onboarding-btn"},
        )
        decision2 = self.policy.evaluate(self.task, click_action, tool=click_tool)
        self.assertTrue(decision2.requires_human)
        self.assertFalse(decision2.allowed)
        self.assertEqual(decision2.risk_level, ActionRisk.SENSITIVE)

    def test_destructive_hr_operation_denied(self):
        purge_tool = DummyTool("purge_employee_records", risk=ActionRisk.DESTRUCTIVE, capabilities=["hr_destructive"])
        action = Action(tool_name="purge_employee_records", arguments={"all": True})
        decision = self.policy.evaluate(self.task, action, tool=purge_tool)
        self.assertTrue(decision.blocked)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk_level, ActionRisk.DESTRUCTIVE)

    def test_approval_fingerprint_and_tamper_detection(self):
        finalize_tool = DummyTool("finalize_onboarding", risk=ActionRisk.WRITE)
        action = Action(
            tool_name="finalize_onboarding",
            arguments={"employee_id": "HR-TEST-1001", "status": "COMPLETED"},
        )
        fingerprint = compute_action_fingerprint(action.tool_name, action.arguments)
        self.assertIsNotNone(fingerprint)

        # Register human approval in task metadata
        self.task.metadata["approval_status"] = "APPROVED"
        self.task.metadata["approved_action_fingerprint"] = fingerprint
        self.task.metadata["approval_consumed"] = False

        # Evaluates to ALLOW with exact payload
        decision = self.policy.evaluate(self.task, action, tool=finalize_tool)
        self.assertTrue(decision.allowed)

        # One-time consumption: mark consumed
        self.task.metadata["approval_consumed"] = True
        decision_after = self.policy.evaluate(self.task, action, tool=finalize_tool)
        self.assertTrue(decision_after.requires_human)
        self.assertFalse(decision_after.allowed)

    def test_altered_action_parameters_invalidate_approval(self):
        finalize_tool = DummyTool("finalize_onboarding", risk=ActionRisk.WRITE)
        action = Action(
            tool_name="finalize_onboarding",
            arguments={"employee_id": "HR-TEST-1001", "role": "Platform Engineer"},
        )
        original_fp = compute_action_fingerprint(action.tool_name, action.arguments)
        self.task.metadata["approval_status"] = "APPROVED"
        self.task.metadata["approved_action_fingerprint"] = original_fp
        self.task.metadata["approval_consumed"] = False

        # Alter arguments (tampering)
        tampered_action = Action(
            tool_name="finalize_onboarding",
            arguments={"employee_id": "HR-TEST-1001", "role": "Senior Exec"},
        )
        tampered_decision = self.policy.evaluate(self.task, tampered_action, tool=finalize_tool)
        self.assertTrue(tampered_decision.requires_human)
        self.assertFalse(tampered_decision.allowed)


class TestHROnboardingVerifierDirect(unittest.IsolatedAsyncioTestCase):
    """Direct unit tests for HROnboardingVerifier logic and negative verification."""

    async def test_document_parser_extracts_correct_fields(self):
        doc_path = Path(__file__).resolve().parents[1] / "data" / "company" / "onboarding" / "onboarding_hr_test_1001.txt"
        parsed = parse_source_onboarding_document(doc_path)
        self.assertEqual(parsed["employee_id"], "HR-TEST-1001")
        self.assertEqual(parsed["name"], "Alex Morgan")
        self.assertEqual(parsed["department"], "Engineering")
        self.assertEqual(parsed["start_date"], "2026-04-01")
        self.assertIn("Security Background Check", parsed["checklist"])
        self.assertIn("Laptop Provisioning", parsed["checklist"])
        self.assertIn("System Access", parsed["checklist"])

    async def test_successful_verification_against_authoritative_state(self):
        verifier = HROnboardingVerifier(base_url="http://mock-hr-portal:3002")

        # Mock portal return matching source document
        mock_data = {
            "employee_id": "HR-TEST-1001",
            "name": "Alex Morgan",
            "department": "Engineering",
            "start_date": "2026-04-01",
            "status": "COMPLETED",
            "checklist": ["Security Background Check", "Laptop Provisioning", "System Access"],
        }

        with patch.object(verifier, "fetch_portal_onboarding", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_data
            result = await verifier.verify(
                task_metadata={"source_document": "onboarding_hr_test_1001.txt"}
            )
            self.assertTrue(result.is_verified)
            self.assertIn("successfully verified", result.details)

    async def test_negative_verification_incomplete_status(self):
        verifier = HROnboardingVerifier(base_url="http://mock-hr-portal:3002")

        # Status still PENDING
        mock_data = {
            "employee_id": "HR-TEST-1001",
            "name": "Alex Morgan",
            "department": "Engineering",
            "start_date": "2026-04-01",
            "status": "PENDING",
            "checklist": ["Security Background Check", "Laptop Provisioning", "System Access"],
        }

        with patch.object(verifier, "fetch_portal_onboarding", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_data
            result = await verifier.verify(
                task_metadata={"source_document": "onboarding_hr_test_1001.txt"}
            )
            self.assertFalse(result.is_verified)
            self.assertIn("status: expected 'COMPLETED', got 'PENDING'", result.details)

    async def test_negative_verification_missing_checklist_item(self):
        verifier = HROnboardingVerifier(base_url="http://mock-hr-portal:3002")

        # Missing "System Access"
        mock_data = {
            "employee_id": "HR-TEST-1001",
            "name": "Alex Morgan",
            "department": "Engineering",
            "start_date": "2026-04-01",
            "status": "COMPLETED",
            "checklist": ["Security Background Check", "Laptop Provisioning"],
        }

        with patch.object(verifier, "fetch_portal_onboarding", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_data
            result = await verifier.verify(
                task_metadata={"source_document": "onboarding_hr_test_1001.txt"}
            )
            self.assertFalse(result.is_verified)
            self.assertIn("checklist missing item: 'System Access'", result.details)

    async def test_negative_verification_wrong_department(self):
        verifier = HROnboardingVerifier(base_url="http://mock-hr-portal:3002")

        mock_data = {
            "employee_id": "HR-TEST-1001",
            "name": "Alex Morgan",
            "department": "Marketing",  # mismatch
            "start_date": "2026-04-01",
            "status": "COMPLETED",
            "checklist": ["Security Background Check", "Laptop Provisioning", "System Access"],
        }

        with patch.object(verifier, "fetch_portal_onboarding", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_data
            result = await verifier.verify(
                task_metadata={"source_document": "onboarding_hr_test_1001.txt"}
            )
            self.assertFalse(result.is_verified)
            self.assertIn("department: expected 'Engineering', got 'Marketing'", result.details)


class TestEndToEndHRWorkflowExecution(unittest.TestCase):
    """End-to-end integration scenario testing full AURA runtime with HR domain."""

    def test_e2e_hr_onboarding_deterministic_execution(self):
        async def run_scenario():
            # Setup deterministic LLM sequence
            initial_plan = {
                "goal": "Complete onboarding for HR-TEST-1001",
                "is_feasible": True,
                "actions": [
                    {
                        "tool_name": "read_company_file",
                        "arguments": {"file_path": "onboarding/onboarding_hr_test_1001.txt"},
                    }
                ],
            }

            steps = [
                # Step 1: Read source document
                {
                    "is_complete": False,
                    "reasoning": "Read source document for HR-TEST-1001 to extract authoritative details.",
                    "action": {
                        "tool_name": "read_company_file",
                        "arguments": {"file_path": "onboarding/onboarding_hr_test_1001.txt"},
                    },
                },
                # Step 2: Navigate to HR Portal
                {
                    "is_complete": False,
                    "reasoning": "Navigate to HR Onboarding Portal new onboarding page.",
                    "action": {
                        "tool_name": "browser_navigate",
                        "arguments": {"url": "http://localhost:3002/hr/onboarding/new"},
                    },
                },
                # Step 3: Type employee ID
                {
                    "is_complete": False,
                    "reasoning": "Enter employee ID HR-TEST-1001.",
                    "action": {
                        "tool_name": "browser_type",
                        "arguments": {"target": "employee_id", "text": "HR-TEST-1001"},
                    },
                },
                # Step 4: Type name
                {
                    "is_complete": False,
                    "reasoning": "Enter candidate name Alex Morgan.",
                    "action": {
                        "tool_name": "browser_type",
                        "arguments": {"target": "name", "text": "Alex Morgan"},
                    },
                },
                # Step 5: Type department
                {
                    "is_complete": False,
                    "reasoning": "Enter department Engineering.",
                    "action": {
                        "tool_name": "browser_type",
                        "arguments": {"target": "department", "text": "Engineering"},
                    },
                },
                # Step 6: Finalize onboarding (SENSITIVE write requiring human approval)
                {
                    "is_complete": False,
                    "reasoning": "Click Finalize Onboarding button.",
                    "action": {
                        "tool_name": "browser_click",
                        "arguments": {"text": "Finalize Onboarding"},
                    },
                },
                # Step 7: Complete
                {
                    "is_complete": True,
                    "completion_summary": "Completed onboarding for HR-TEST-1001 in HR portal.",
                    "action": None,
                },
            ]

            mock_llm = MockDeterministicLLM(initial_plan, steps)
            session = BrowserSession(headless=True)
            tool_reg = get_default_tool_registry(browser_session=session)

            runtime = AgentRuntime(
                llm_provider=mock_llm,
                tool_registry=tool_reg,
                domain="hr",
            )

            # Mock verifier to simulate authoritative backend match
            class MockHRVerifier(BaseVerifier):
                source_name = "mock_hr_verifier"

                def can_verify(self, task: Task) -> bool:
                    return task.metadata.get("domain") == "hr"

                async def verify(self, task_metadata, source_reference=None):
                    return VerificationResult(
                        True,
                        "Mock HR verification succeeded against authoritative store.",
                        expected={"employee_id": "HR-TEST-1001", "status": "COMPLETED"},
                        actual={"employee_id": "HR-TEST-1001", "status": "COMPLETED"},
                    )

            runtime.verifier_registry.register(MockHRVerifier())

            task = Task(
                user_goal="Complete the onboarding checklist for synthetic employee HR-TEST-1001",
                metadata={"domain": "hr", "source_document": "onboarding_hr_test_1001.txt"},
            )

            try:
                # 1. Execute task up to sensitive mutation -> should pause for human approval
                res = await runtime.execute_task(task, use_dynamic_adaptation=True)
                self.assertEqual(res.status, TaskStatus.WAITING_FOR_HUMAN)
                self.assertEqual(runtime.state, AgentState.WAITING_FOR_HUMAN)

                # 2. Check pending action and SHA-256 fingerprint
                self.assertIn("pending_action", res.metadata)
                expected_fp = compute_action_fingerprint(
                    "browser_click",
                    {"text": "Finalize Onboarding"},
                )
                self.assertEqual(res.metadata.get("pending_action_fingerprint"), expected_fp)

                # 3. Operator grants human approval
                runtime.approve_task(task.task_id, feedback="Approved by HR administrator")

                # 4. Resume execution
                completed_task = await runtime.resume_task(task.task_id)
                self.assertEqual(completed_task.status, TaskStatus.COMPLETED)
                self.assertEqual(runtime.state, AgentState.COMPLETED)

                # Check action sequence executed
                tool_names = [a.tool_name for a in runtime.executed_actions]
                self.assertIn("read_company_file", tool_names)
                self.assertIn("browser_navigate", tool_names)
                self.assertIn("browser_type", tool_names)
                self.assertIn("browser_click", tool_names)

                # Check task metadata retains domain
                self.assertEqual(completed_task.metadata.get("domain"), "hr")
                self.assertIn("completion_summary", completed_task.metadata)
            finally:
                await session.close()

        asyncio.run(run_scenario())


class TestResumeDomainSynchronization(unittest.TestCase):
    """Regression tests verifying domain synchronization during direct task resume."""

    def setUp(self):
        self.mem_store = SQLiteMemoryStore(":memory:")
        runtime_manager.memory_store = self.mem_store
        runtime_manager.runtimes.clear()
        runtime_manager.background_tasks.clear()
        self.mock_llm = MockDeterministicLLM(
            initial_plan={"is_feasible": True, "actions": []},
            step_responses=[
                {"is_complete": True, "completion_summary": "Task complete.", "action": None}
            ],
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.mem_store.close()
        runtime_manager.memory_store = SQLiteMemoryStore()
        runtime_manager.runtimes.clear()
        runtime_manager.background_tasks.clear()

    def test_direct_resume_hr_task_restores_domain_and_guidelines_and_verifier(self):
        """Directly resuming an HR task restores HR domain, planner guidelines, and HR verifier."""
        task = Task(
            task_id="task-resume-hr-001",
            user_goal="Process employee onboarding for HR-TEST-1001",
            metadata={"domain": "hr", "source_document": "onboarding_hr_test_1001.txt"},
        )
        self.mem_store.create_task(task, initial_state=AgentState.ADAPTING)

        # Create an unconfigured runtime without domain
        runtime = AgentRuntime(memory_store=self.mem_store, llm_provider=self.mock_llm)
        self.assertIsNone(runtime.domain)
        # Default planner starts with finance guidelines
        self.assertEqual(runtime.planner.domain_guidelines, DEFAULT_FINANCE_GUIDELINES)

        # Directly resume task
        resumed = asyncio.run(runtime.resume_task(task.task_id))

        # Domain must now be synchronized
        self.assertEqual(runtime.domain, "hr")
        self.assertEqual(resumed.metadata.get("domain"), "hr")
        self.assertEqual(runtime.planner.domain_guidelines, DEFAULT_HR_GUIDELINES)
        self.assertTrue(
            any(isinstance(v, HROnboardingVerifier) for v in runtime.verifier_registry.verifiers)
        )
        # HR guidelines are used without finance cross-contamination
        for rule in DEFAULT_HR_GUIDELINES:
            self.assertIn(rule, runtime.planner.domain_guidelines)
        for rule in DEFAULT_FINANCE_GUIDELINES:
            self.assertNotIn(rule, runtime.planner.domain_guidelines)

    def test_direct_resume_finance_task_restores_finance_behavior(self):
        """Directly resuming a Finance task retains Finance domain, guidelines, and verifier."""
        task = Task(
            task_id="task-resume-fin-002",
            user_goal="Process invoice INV-2026-0001",
            metadata={"domain": "finance", "source_document": "invoice_acme_1001.txt"},
        )
        self.mem_store.create_task(task, initial_state=AgentState.ADAPTING)

        runtime = AgentRuntime(memory_store=self.mem_store, llm_provider=self.mock_llm)
        resumed = asyncio.run(runtime.resume_task(task.task_id))

        self.assertEqual(runtime.domain, "finance")
        self.assertEqual(resumed.metadata.get("domain"), "finance")
        self.assertEqual(runtime.planner.domain_guidelines, DEFAULT_FINANCE_GUIDELINES)
        self.assertIsNotNone(runtime.finance_verifier)

    def test_direct_resume_missing_domain_metadata_defaults_to_finance(self):
        """Missing domain metadata in persisted task preserves the backward-compatible Finance default."""
        task = Task(
            task_id="task-resume-legacy-003",
            user_goal="Legacy task without domain metadata",
            metadata={},
        )
        self.mem_store.create_task(task, initial_state=AgentState.ADAPTING)

        runtime = AgentRuntime(memory_store=self.mem_store, llm_provider=self.mock_llm)
        resumed = asyncio.run(runtime.resume_task(task.task_id))

        self.assertEqual(runtime.domain, "finance")
        self.assertEqual(resumed.metadata.get("domain"), "finance")
        self.assertEqual(runtime.planner.domain_guidelines, DEFAULT_FINANCE_GUIDELINES)

    def test_direct_resume_invalid_persisted_domain_fails_safely(self):
        """Invalid or unknown persisted domain metadata causes resume to fail safely."""
        task = Task(
            task_id="task-resume-invalid-004",
            user_goal="Task with invalid domain",
            metadata={"domain": "unsupported_domain_xyz"},
        )
        self.mem_store.create_task(task, initial_state=AgentState.ADAPTING)

        runtime = AgentRuntime(memory_store=self.mem_store, llm_provider=self.mock_llm)
        resumed = asyncio.run(runtime.resume_task(task.task_id))

        self.assertEqual(resumed.status, TaskStatus.FAILED)
        self.assertEqual(runtime.state, AgentState.FAILED)
        self.assertIn("Unsupported domain 'unsupported_domain_xyz'", resumed.metadata.get("error", ""))

        # Verify persistent store state was updated to FAILED
        persisted = self.mem_store.get_task(task.task_id)
        self.assertEqual(persisted.task.status, TaskStatus.FAILED)
        self.assertEqual(persisted.state, AgentState.FAILED)

    def test_direct_resume_preserves_task_history_and_approval_state(self):
        """Direct resume preserves action history, observation history, and approval status."""
        task = Task(
            task_id="task-resume-preserve-005",
            user_goal="Verify state preservation during resume",
            metadata={
                "domain": "hr",
                "approval_status": "APPROVED",
                "approved_action_fingerprint": "mock-fp-123",
            },
        )
        self.mem_store.create_task(task, initial_state=AgentState.WAITING_FOR_HUMAN)
        act1 = Action(tool_name="read_company_file", arguments={"file_path": "test.txt"})
        obs1 = Observation(action_id=act1.action_id, success=True, result="file content")
        self.mem_store.append_action(task.task_id, act1)
        self.mem_store.append_observation(task.task_id, obs1)

        runtime = AgentRuntime(memory_store=self.mem_store, llm_provider=self.mock_llm)
        resumed = asyncio.run(runtime.resume_task(task.task_id))

        self.assertEqual(resumed.task_id, task.task_id)
        self.assertEqual(resumed.metadata.get("domain"), "hr")
        self.assertEqual(resumed.metadata.get("approval_status"), "APPROVED")
        self.assertEqual(len(runtime.executed_actions), 1)
        self.assertEqual(runtime.executed_actions[0].tool_name, "read_company_file")
        self.assertEqual(len(runtime.observations), 1)

    def test_existing_api_resume_endpoint_retains_behavior(self):
        """FastAPI POST /api/tasks/{task_id}/resume retains full functionality."""
        t = Task(
            task_id="api-resume-task-006",
            user_goal="API resume test",
            metadata={"domain": "hr"},
        )
        self.mem_store.create_task(t, initial_state=AgentState.ADAPTING)

        response = self.client.post(f"/api/tasks/{t.task_id}/resume")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["task_id"], t.task_id)

    def test_repeated_synchronization_does_not_duplicate_policy_rules_or_verifiers(self):
        """Repeated synchronization of the same task does not duplicate policy rules or verifiers."""
        task = Task(
            task_id="task-resume-dup-007",
            user_goal="Repeated sync test",
            metadata={"domain": "hr"},
        )
        self.mem_store.create_task(task, initial_state=AgentState.ADAPTING)

        runtime = AgentRuntime(memory_store=self.mem_store, llm_provider=self.mock_llm)
        asyncio.run(runtime.resume_task(task.task_id))

        rule_count_first = len(runtime.policy.domain_rules)
        verifier_count_first = len(runtime.verifier_registry.verifiers)

        # Call synchronization again
        runtime._sync_domain_configuration(task)
        runtime._sync_domain_configuration(task)

        self.assertEqual(len(runtime.policy.domain_rules), rule_count_first)
        self.assertEqual(len(runtime.verifier_registry.verifiers), verifier_count_first)

    def test_runtime_reuse_across_domains_is_isolated_and_consistent(self):
        """Reusing the same AgentRuntime across HR and Finance switches domain rules and guidelines consistently."""
        from backend.policy.rules import DomainRiskRule
        from backend.policy.risk import ActionRisk

        custom_rule = DomainRiskRule(
            name="custom_audit_preserve",
            risk_level=ActionRisk.SENSITIVE,
            tool_names={"audit_log"},
        )
        policy = DefaultActionPolicy(domain_rules=[custom_rule])

        runtime = AgentRuntime(
            memory_store=self.mem_store,
            llm_provider=self.mock_llm,
            policy=policy,
        )

        hr_task = Task(
            task_id="hr-reuse-task",
            user_goal="Process HR onboarding",
            metadata={"domain": "hr"},
        )
        fin_task = Task(
            task_id="fin-reuse-task",
            user_goal="Process Finance invoice",
            metadata={"domain": "finance"},
        )
        self.mem_store.create_task(hr_task, initial_state=AgentState.ADAPTING)
        self.mem_store.create_task(fin_task, initial_state=AgentState.ADAPTING)

        # 1. Run / resume HR task
        asyncio.run(runtime.resume_task(hr_task.task_id))
        self.assertEqual(runtime.domain, "hr")
        self.assertEqual(runtime.planner.domain_guidelines, DEFAULT_HR_GUIDELINES)
        hr_rule_names = {r.name for r in runtime.policy.domain_rules}
        self.assertIn("hr_finalize_onboarding", hr_rule_names)
        self.assertIn("custom_audit_preserve", hr_rule_names)
        hr_verifier = runtime.verifier_registry.get_verifier(hr_task)
        self.assertIsInstance(hr_verifier, HROnboardingVerifier)

        # 2. Reuse same runtime for Finance task
        asyncio.run(runtime.resume_task(fin_task.task_id))
        self.assertEqual(runtime.domain, "finance")
        self.assertEqual(runtime.planner.domain_guidelines, DEFAULT_FINANCE_GUIDELINES)
        fin_rule_names = {r.name for r in runtime.policy.domain_rules}
        # HR rules must not linger on Finance task
        self.assertNotIn("hr_finalize_onboarding", fin_rule_names)
        self.assertNotIn("hr_bulk_purge_destructive", fin_rule_names)
        # Custom rule must still be preserved
        self.assertIn("custom_audit_preserve", fin_rule_names)
        fin_verifier = runtime.verifier_registry.get_verifier(fin_task)
        self.assertIsInstance(fin_verifier, FinanceInvoiceVerifier)

        # 3. Switch back to HR
        asyncio.run(runtime.resume_task(hr_task.task_id))
        self.assertEqual(runtime.domain, "hr")
        self.assertEqual(runtime.planner.domain_guidelines, DEFAULT_HR_GUIDELINES)
        hr_rule_names_again = {r.name for r in runtime.policy.domain_rules}
        self.assertIn("hr_finalize_onboarding", hr_rule_names_again)
        self.assertIn("custom_audit_preserve", hr_rule_names_again)


if __name__ == "__main__":
    unittest.main()
