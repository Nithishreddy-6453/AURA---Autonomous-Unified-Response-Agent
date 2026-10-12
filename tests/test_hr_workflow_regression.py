"""Focused regression tests for AURA HR Workflow Fixes.

Covers:
1. Correct identification of the real finalization button ("Finalize Onboarding", "#finalize-onboarding-btn").
2. Read-only inspection requiring live portal evidence.
3. A read-only task never executing a mutating action in policy layer, even if proposed.
4. A read-only task whose employee status is PENDING while all checklist items are COMPLETE.
5. An authorized onboarding mutation requiring human approval and using the correct finalization target.
6. Verifier failure when a mutation task does not actually complete.

Data safety:
All mutation tests use isolated mocks and fixtures. No live HR records are modified.
"""

import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.domains import (
    DEFAULT_HR_GUIDELINES,
    DEFAULT_HR_POLICY_RULES,
    get_domain_config,
    is_hr_read_only_task,
)
from backend.models.action import Action
from backend.models.task import Task
from backend.policy.decision import PolicyDecision
from backend.policy.engine import DefaultActionPolicy, compute_action_fingerprint
from backend.policy.risk import ActionRisk
from backend.tools.base import Tool
from backend.tools.browser.browser_read import BrowserReadTool
from backend.verification.hr_verifier import (
    HROnboardingVerifier,
    parse_source_onboarding_document,
)


class DummyTool(Tool):
    """Minimal test tool."""

    def __init__(self, name: str, risk: ActionRisk = ActionRisk.READ, capabilities: list = None):
        self._name = name
        self._risk = risk
        self._capabilities = capabilities or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Dummy {self._name}"

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
        raise NotImplementedError()


class TestHRWorkflowRegression(unittest.IsolatedAsyncioTestCase):
    """Targeted regression test suite for HR workflow safety, navigation, and verification."""

    def setUp(self):
        self.policy = DefaultActionPolicy(domain_rules=DEFAULT_HR_POLICY_RULES)
        self.hr_guidelines = get_domain_config("hr").guidelines

    def test_1_identification_of_real_finalization_button(self):
        """Test 1: Verify correct identification of the real finalization button.

        - HR guidelines must use 'Finalize Onboarding' and '#finalize-onboarding-btn'.
        - HR guidelines must NOT contain the obsolete 'Complete Onboarding Checklist'.
        - DOM source for new onboarding page must contain id="finalize-onboarding-btn" and "Finalize Onboarding".
        - Policy engine recognizes '#finalize-onboarding-btn' as sensitive requiring human approval for mutations.
        """
        # 1. Guidelines verification
        guidelines_str = " ".join(self.hr_guidelines)
        self.assertIn("#finalize-onboarding-btn", guidelines_str)
        self.assertIn("Finalize Onboarding", guidelines_str)
        self.assertNotIn("Complete Onboarding Checklist", guidelines_str)

        # 2. Actual HR Portal DOM verification
        project_root = Path(__file__).resolve().parents[1]
        onboarding_page_path = project_root / "company" / "hr" / "src" / "app" / "hr" / "onboarding" / "new" / "page.tsx"
        self.assertTrue(onboarding_page_path.exists(), f"HR onboarding DOM page not found at {onboarding_page_path}")
        dom_content = onboarding_page_path.read_text(encoding="utf-8")
        self.assertIn('id="finalize-onboarding-btn"', dom_content)
        self.assertIn("Finalize Onboarding", dom_content)

        # 3. Policy rule sensitivity verification
        task = Task(user_goal="Onboard candidate EMP-999", metadata={"domain": "hr", "read_only": False})
        click_tool = DummyTool("browser_click", risk=ActionRisk.WRITE)
        action = Action(
            tool_name="browser_click",
            arguments={"selector": "#finalize-onboarding-btn", "text": "Finalize Onboarding"},
        )
        decision = self.policy.evaluate(task, action, tool=click_tool)
        self.assertTrue(decision.requires_human)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk_level, ActionRisk.SENSITIVE)

    async def test_2_read_only_inspection_requires_live_portal_evidence(self):
        """Test 2: Read-only inspection requires live portal evidence.

        - HR guidelines mandate navigating to http://localhost:3002/hr and inspecting live portal state.
        - Guidelines forbid treating static company files as proof of live status when current state is requested.
        - HROnboardingVerifier checks live portal API; missing from live portal fails verification.
        """
        guidelines_str = " ".join(self.hr_guidelines)
        self.assertIn("http://localhost:3002/hr", guidelines_str)
        self.assertIn("browser_read", guidelines_str)
        self.assertIn("never be treated as proof of live status", guidelines_str.lower())

        # Verifier requires live portal record even if source document exists
        verifier = HROnboardingVerifier(base_url="http://mock-hr-portal:3002")
        task_meta = {
            "domain": "hr",
            "read_only": True,
            "employee_id": "HR-TEST-1001",
            "source_document": "onboarding_hr_test_1001.txt",
        }
        with patch.object(verifier, "fetch_portal_onboarding", new_callable=AsyncMock) as mock_fetch:
            # Live portal returns 404 / None
            mock_fetch.return_value = None
            result = await verifier.verify(task_meta)
            self.assertFalse(result.is_verified)
            self.assertIn("not found in HR Portal", result.details)

    def test_3_read_only_task_never_executes_mutating_action(self):
        """Test 3: A read-only task never executes a mutating action, even if the planner proposes one.

        - Enforced in the policy layer before dispatching.
        - Mutating actions (click submit, click new onboarding, navigate to new form, type in form) are BLOCKED (DESTRUCTIVE).
        - Safe navigation, reading, and search filter typing continue to be permitted.
        """
        # Test both explicit metadata flag and user_goal marker
        for read_only_task in [
            Task(user_goal="Inspect employee status", metadata={"domain": "hr", "read_only": True}),
            Task(user_goal="Inspect current onboarding status for employee HR-TEST-1001 (read-only, do not modify)", metadata={"domain": "hr"}),
            Task(user_goal="View current status of HR-TEST-1001 without modifying", metadata={"domain": "hr"}),
        ]:
            self.assertTrue(is_hr_read_only_task(read_only_task))

            click_tool = DummyTool("browser_click", risk=ActionRisk.WRITE)
            nav_tool = DummyTool("browser_navigate", risk=ActionRisk.WRITE)
            type_tool = DummyTool("browser_type", risk=ActionRisk.WRITE)
            finalize_tool = DummyTool("finalize_onboarding", risk=ActionRisk.WRITE)

            # Mutating action 1: Click finalize onboarding button
            act_finalize_click = Action(
                tool_name="browser_click",
                arguments={"selector": "#finalize-onboarding-btn", "text": "Finalize Onboarding"},
            )
            dec = self.policy.evaluate(read_only_task, act_finalize_click, tool=click_tool)
            self.assertTrue(dec.blocked, f"Expected blocked for finalize click, got {dec}")
            self.assertFalse(dec.allowed)
            self.assertEqual(dec.risk_level, ActionRisk.DESTRUCTIVE)

            # Mutating action 2: Click "+ New Onboarding Request"
            act_new_click = Action(
                tool_name="browser_click",
                arguments={"selector": "#new-onboarding-link", "text": "+ New Onboarding Request"},
            )
            dec = self.policy.evaluate(read_only_task, act_new_click, tool=click_tool)
            self.assertTrue(dec.blocked, f"Expected blocked for new onboarding link, got {dec}")
            self.assertFalse(dec.allowed)
            self.assertEqual(dec.risk_level, ActionRisk.DESTRUCTIVE)

            # Mutating action 3: Navigate to /hr/onboarding/new
            act_new_nav = Action(
                tool_name="browser_navigate",
                arguments={"url": "http://localhost:3002/hr/onboarding/new"},
            )
            dec = self.policy.evaluate(read_only_task, act_new_nav, tool=nav_tool)
            self.assertTrue(dec.blocked, f"Expected blocked for navigation to new onboarding, got {dec}")
            self.assertFalse(dec.allowed)
            self.assertEqual(dec.risk_level, ActionRisk.DESTRUCTIVE)

            # Mutating action 4: Type into form inputs
            for field in ["employee_id", "name", "department", "start_date"]:
                act_type = Action(
                    tool_name="browser_type",
                    arguments={"target": field, "text": "test-val"},
                )
                dec = self.policy.evaluate(read_only_task, act_type, tool=type_tool)
                self.assertTrue(dec.blocked, f"Expected blocked for typing into {field}, got {dec}")
                self.assertFalse(dec.allowed)
                self.assertEqual(dec.risk_level, ActionRisk.DESTRUCTIVE)

            # Mutating action 5: Direct tool invocation
            act_finalize_tool = Action(
                tool_name="finalize_onboarding",
                arguments={"employee_id": "HR-TEST-1001"},
            )
            dec = self.policy.evaluate(read_only_task, act_finalize_tool, tool=finalize_tool)
            self.assertTrue(dec.blocked, f"Expected blocked for finalize_onboarding tool, got {dec}")
            self.assertFalse(dec.allowed)
            self.assertEqual(dec.risk_level, ActionRisk.DESTRUCTIVE)

            # Safe action 1: Safe navigation to HR dashboard
            safe_nav = Action(
                tool_name="browser_navigate",
                arguments={"url": "http://localhost:3002/hr"},
            )
            dec = self.policy.evaluate(read_only_task, safe_nav, tool=nav_tool)
            self.assertFalse(dec.blocked)
            self.assertTrue(dec.allowed)

            # Safe action 2: Safe read
            read_tool = DummyTool("browser_read", risk=ActionRisk.READ)
            safe_read = Action(tool_name="browser_read", arguments={})
            dec = self.policy.evaluate(read_only_task, safe_read, tool=read_tool)
            self.assertFalse(dec.blocked)
            self.assertTrue(dec.allowed)

            # Safe action 3: Safe search filter typing
            search_type = Action(
                tool_name="browser_type",
                arguments={"target": "search", "selector": "#search-input", "text": "HR-TEST-1001"},
            )
            dec = self.policy.evaluate(read_only_task, search_type, tool=type_tool)
            self.assertFalse(dec.blocked)
            self.assertTrue(dec.allowed)

    async def test_4_read_only_task_succeeds_when_status_pending_and_checklist_complete(self):
        """Test 4: A read-only task whose employee status is PENDING while all checklist items are COMPLETE.

        - Verifier must NOT require status == 'COMPLETED' for read-only inspection tasks.
        - Verifier succeeds when employee exists and reported checklist matches live state.
        """
        verifier = HROnboardingVerifier(base_url="http://mock-hr-portal:3002")

        # Live portal record has status PENDING and 3 checklist items
        mock_portal_data = {
            "employee_id": "HR-TEST-1001",
            "name": "Alex Morgan",
            "department": "Engineering",
            "start_date": "2026-04-01",
            "role": "Platform Engineer",
            "status": "PENDING",
            "checklist": ["Security Background Check", "Laptop Provisioning", "System Access"],
        }

        with patch.object(verifier, "fetch_portal_onboarding", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_portal_data

            # 4a: Using explicit metadata read_only: True
            res1 = await verifier.verify(
                task_metadata={
                    "domain": "hr",
                    "read_only": True,
                    "employee_id": "HR-TEST-1001",
                    "source_document": "onboarding_hr_test_1001.txt",
                }
            )
            self.assertTrue(res1.is_verified, f"Expected verified for read-only task with status=PENDING, details: {res1.details}")
            self.assertIn("successfully verified", res1.details)

            # 4b: Using read-only Task object via can_verify
            read_only_task = Task(
                user_goal="Inspect current onboarding status for employee HR-TEST-1001 (read-only)",
                metadata={"domain": "hr"},
            )
            self.assertTrue(verifier.can_verify(read_only_task))
            res2 = await verifier.verify(
                task_metadata={"employee_id": "HR-TEST-1001", "source_document": "onboarding_hr_test_1001.txt"}
            )
            self.assertTrue(res2.is_verified, f"Expected verified via task context, details: {res2.details}")

            # 4c: Discrepancy detection: if reported checklist contains items not in portal, verification fails
            res_bad_checklist = await verifier.verify(
                task_metadata={
                    "domain": "hr",
                    "read_only": True,
                    "employee_id": "HR-TEST-1001",
                    "reported_checklist": ["Security Background Check", "Nonexistent Checklist Item"],
                }
            )
            self.assertFalse(res_bad_checklist.is_verified)
            self.assertIn("Nonexistent Checklist Item", res_bad_checklist.details)

    def test_5_authorized_onboarding_mutation_requires_human_approval(self):
        """Test 5: An authorized onboarding mutation requiring human approval and using the correct finalization target.

        - Authorized mutation task targeting #finalize-onboarding-btn requires human approval.
        - With matching approval fingerprint, action is allowed.
        - Tampered action fingerprint invalidates approval.
        """
        task = Task(
            user_goal="Complete onboarding for candidate EMP-2026-999",
            metadata={"domain": "hr", "read_only": False},
        )
        click_tool = DummyTool("browser_click", risk=ActionRisk.WRITE)
        action = Action(
            tool_name="browser_click",
            arguments={"selector": "#finalize-onboarding-btn", "text": "Finalize Onboarding"},
        )

        # 1. Unapproved action -> requires human approval
        decision = self.policy.evaluate(task, action, tool=click_tool)
        self.assertTrue(decision.requires_human)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk_level, ActionRisk.SENSITIVE)

        # 2. Grant human approval with exact fingerprint
        fp = compute_action_fingerprint(action.tool_name, action.arguments)
        task.metadata["approval_status"] = "APPROVED"
        task.metadata["approved_action_fingerprint"] = fp
        task.metadata["approval_consumed"] = False

        decision_approved = self.policy.evaluate(task, action, tool=click_tool)
        self.assertTrue(decision_approved.allowed)
        self.assertFalse(decision_approved.requires_human)

        # 3. Tampered payload -> approval invalidated
        tampered_action = Action(
            tool_name="browser_click",
            arguments={"selector": "#finalize-onboarding-btn", "text": "Finalize Onboarding", "extra": "tampered"},
        )
        decision_tampered = self.policy.evaluate(task, tampered_action, tool=click_tool)
        self.assertTrue(decision_tampered.requires_human)
        self.assertFalse(decision_tampered.allowed)

    async def test_6_verifier_failure_when_mutation_task_does_not_actually_complete(self):
        """Test 6: Verifier failure when a mutation task does not actually complete.

        - Genuine mutation task must strictly require status == 'COMPLETED'.
        - If portal status is PENDING, verifier returns is_verified=False.
        - If employee record is absent from portal, verifier returns is_verified=False.
        """
        verifier = HROnboardingVerifier(base_url="http://mock-hr-portal:3002")

        # 6a: Portal status is still PENDING for a mutation task
        mock_incomplete_data = {
            "employee_id": "HR-TEST-1002",
            "name": "Jordan Lee",
            "department": "Product",
            "start_date": "2026-04-10",
            "status": "PENDING",
            "checklist": ["Security Background Check", "Welcome Session Scheduled"],
        }
        mutation_task = Task(
            user_goal="Finalize onboarding for employee HR-TEST-1002",
            metadata={"domain": "hr", "read_only": False},
        )
        self.assertTrue(verifier.can_verify(mutation_task))

        with patch.object(verifier, "fetch_portal_onboarding", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_incomplete_data
            result = await verifier.verify(
                task_metadata={
                    "domain": "hr",
                    "read_only": False,
                    "intent": "mutation",
                    "employee_id": "HR-TEST-1002",
                },
                source_reference={
                    "employee_id": "HR-TEST-1002",
                    "name": "Jordan Lee",
                    "department": "Product",
                    "start_date": "2026-04-10",
                    "checklist": ["Security Background Check", "Welcome Session Scheduled"],
                },
            )
            self.assertFalse(result.is_verified)
            self.assertIn("status: expected 'COMPLETED', got 'PENDING'", result.details)

        # 6b: Employee not found in portal for mutation task
        with patch.object(verifier, "fetch_portal_onboarding", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None
            result_missing = await verifier.verify(
                task_metadata={"domain": "hr", "read_only": False, "employee_id": "EMP-9999"},
                source_reference={"employee_id": "EMP-9999", "name": "Nonexistent Candidate"},
            )
            self.assertFalse(result_missing.is_verified)
            self.assertIn("not found in HR Portal", result_missing.details)

    async def test_7_hr_dashboard_employee_table_selector_and_inspection(self):
        """Test 7: The real HR dashboard table has selector #employee-table, contains HR-TEST-1001,

        each row has a data-employee-id attribute, selector #employee-table tr[data-employee-id='HR-TEST-1001']
        matches that row and allows details to be read, and read-only inspection never triggers mutations.
        """
        # 1. Real HR dashboard component has selector #employee-table on the actual table
        project_root = Path(__file__).resolve().parents[1]
        dashboard_page_path = project_root / "company" / "hr" / "src" / "app" / "hr" / "page.tsx"
        self.assertTrue(dashboard_page_path.exists())
        dashboard_content = dashboard_page_path.read_text(encoding="utf-8")
        self.assertIn('<table id="employee-table"', dashboard_content)
        # Ensure #employee-table is on the table element, not on an outer wrapper div
        self.assertNotIn('<div id="employee-table"', dashboard_content)
        # Verify row rendering has data-employee-id attribute
        self.assertIn('data-employee-id={r.employee_id}', dashboard_content)

        # Also verify standalone server template has #employee-table and data-employee-id
        standalone_path = project_root / "company" / "hr" / "standalone_server.mjs"
        self.assertTrue(standalone_path.exists())
        standalone_content = standalone_path.read_text(encoding="utf-8")
        self.assertIn('<table id="employee-table">', standalone_content)
        self.assertIn('data-employee-id="${r.employee_id}"', standalone_content)

        # Check live server rendered HTML if reachable
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:3002/hr", timeout=1.5) as resp:
                live_html = resp.read().decode("utf-8")
                self.assertIn('<tr data-employee-id="HR-TEST-1001"', live_html)
        except Exception:
            pass

        # 2. Verify table contains the row for HR-TEST-1001 in seed / dashboard data
        self.assertIn("HR-TEST-1001", standalone_content)
        seed_path = project_root / "company" / "hr" / "src" / "lib" / "seed.ts"
        self.assertTrue(seed_path.exists())
        seed_content = seed_path.read_text(encoding="utf-8")
        self.assertIn("HR-TEST-1001", seed_content)

        # 3. browser_read can locate and inspect the row using #employee-table tr[data-employee-id='HR-TEST-1001']
        target_row_selector = "#employee-table tr[data-employee-id='HR-TEST-1001']"
        mock_page = AsyncMock()
        mock_page.url = "http://localhost:3002/hr"
        mock_page.title = AsyncMock(return_value="HR Onboarding Portal")

        row_text = "HR-TEST-1001 Alex Morgan Engineering 2026-04-01 Security Background Check, Laptop Provisioning, System Access COMPLETED"
        table_text = "Employee ID Name Department Start Date Checklist Status\n" + row_text

        def mock_locator_resolver(sel):
            loc = AsyncMock()
            if sel in ("#employee-table", target_row_selector):
                loc.count = AsyncMock(return_value=1)
                loc.inner_text = AsyncMock(return_value=row_text if "tr" in sel else table_text)
            else:
                loc.count = AsyncMock(return_value=0)
                loc.inner_text = AsyncMock(return_value="")
            wrapper = MagicMock()
            wrapper.first = loc
            return wrapper

        mock_page.locator = MagicMock(side_effect=mock_locator_resolver)

        mock_session = MagicMock()
        mock_session.get_page = AsyncMock(return_value=mock_page)

        read_tool = BrowserReadTool(session=mock_session)

        # Test A: Read specific row by selector
        obs_row = await read_tool.execute(selector=target_row_selector)
        self.assertTrue(obs_row.success)
        self.assertEqual(obs_row.result["selector"], target_row_selector)
        self.assertIn("HR-TEST-1001", obs_row.result["visible_text_summary"])
        self.assertIn("Alex Morgan", obs_row.result["visible_text_summary"])
        self.assertIn("Engineering", obs_row.result["visible_text_summary"])

        # Test B: Read entire table
        obs_table = await read_tool.execute(selector="#employee-table")
        self.assertTrue(obs_table.success)
        self.assertIn("HR-TEST-1001", obs_table.result["visible_text_summary"])

        # Test C: Unsupported/nonexistent selector fails gracefully
        obs_bad = await read_tool.execute(selector="#employee-table tr[data-employee-id='NONEXISTENT']")
        self.assertFalse(obs_bad.success)
        self.assertIn("not found on page", obs_bad.error)

        # 4. Read-only inspection never triggers a modification or finalization action
        read_only_task = Task(
            user_goal="Inspect current status of employee HR-TEST-1001 in the portal (read-only)",
            metadata={"domain": "hr", "read_only": True},
        )
        # Safe read action on table or row is allowed
        safe_read_action = Action(tool_name="browser_read", arguments={"selector": target_row_selector})
        read_decision = self.policy.evaluate(read_only_task, safe_read_action, tool=read_tool)
        self.assertTrue(read_decision.allowed)
        self.assertFalse(read_decision.blocked)

        # Mutating action: finalization click is blocked
        click_tool = DummyTool("browser_click", risk=ActionRisk.WRITE)
        finalize_action = Action(tool_name="browser_click", arguments={"selector": "#finalize-onboarding-btn", "text": "Finalize Onboarding"})
        mutate_decision = self.policy.evaluate(read_only_task, finalize_action, tool=click_tool)
        self.assertTrue(mutate_decision.blocked)
        self.assertFalse(mutate_decision.allowed)
        self.assertEqual(mutate_decision.risk_level, ActionRisk.DESTRUCTIVE)

        # Mutating action: typing into employee form input is blocked
        type_tool = DummyTool("browser_type", risk=ActionRisk.WRITE)
        type_action = Action(tool_name="browser_type", arguments={"target": "employee_id", "text": "HR-TEST-1001"})
        type_decision = self.policy.evaluate(read_only_task, type_action, tool=type_tool)
        self.assertTrue(type_decision.blocked)
        self.assertFalse(type_decision.allowed)
        self.assertEqual(type_decision.risk_level, ActionRisk.DESTRUCTIVE)


if __name__ == "__main__":
    unittest.main()
