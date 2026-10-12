import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from backend.agent.planner import Planner
from backend.agent.runtime import AgentRuntime
from backend.agent.schemas import PlanningResult
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.models.action import Action
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.recovery.classifier import FailureType, classify_failure
from backend.recovery.policies import get_recovery_policy
from backend.tools import ToolRegistry, get_default_tool_registry
from backend.tools.browser.browser_click import BrowserClickTool
from backend.tools.browser.browser_navigate import BrowserNavigateTool
from backend.tools.browser.browser_session import BrowserSession
from backend.tools.browser.browser_type import BrowserTypeTool
from backend.verification.finance_verifier import FinanceInvoiceVerifier


class SingleStepCompletionLLM(LLMProvider):
    """LLM mock that immediately proposes completion with a specified summary."""

    def __init__(self, completion_summary: str = "The invoice has been entered and saved.", source_file: str = "test.txt"):
        self.completion_summary = completion_summary
        self.source_file = source_file

    async def generate(self, prompt: str, system_instruction: str = None, temperature: float = 0.0, **kwargs):
        if "Available Tools:" in prompt and "Execution History & Observations:" not in prompt:
            return json.dumps({
                "goal": "Verify invoice persistence",
                "is_feasible": True,
                "unsupported_reason": None,
                "actions": [
                    {
                        "tool_name": "read_company_file",
                        "arguments": {"file_path": self.source_file},
                    }
                ],
            })
        return json.dumps({
            "is_complete": True,
            "completion_summary": self.completion_summary,
            "reasoning": "Task completed.",
            "action": None,
        })

    async def chat(self, messages, temperature: float = 0.0, **kwargs):
        return ""


class TestFinancePersistenceRegression(unittest.TestCase):
    """Regression test suite for Finance invoice form persistence, error detection,

    and verified completion metadata consistency.
    """

    def test_failed_persistence_detects_form_validation_errors(self):
        """When form is submitted with missing required fields (e.g. only amount entered),

        browser_click must detect #form-error-alert and return success=False with errors.
        """
        async def run_test():
            session = BrowserSession(headless=True)
            navigate_tool = BrowserNavigateTool(session=session)
            type_tool = BrowserTypeTool(session=session)
            click_tool = BrowserClickTool(session=session)

            try:
                # 1. Navigate to Finance Portal new invoice form
                nav_obs = await navigate_tool.execute(url="http://localhost:3000/finance/invoices/new")
                self.assertTrue(nav_obs.success)

                # 2. Enter ONLY amount (reproducing the failed live task condition)
                type_obs = await type_tool.execute(target="amount", text="18036.00")
                self.assertTrue(type_obs.success)

                # 3. Click Save Invoice without other mandatory fields
                click_obs = await click_tool.execute(
                    target="Save Invoice",
                    text="Save Invoice",
                    role="button",
                    selector="#submit-invoice-button",
                )

                # 4. Form submission must NOT be reported as successful!
                self.assertFalse(click_obs.success)
                self.assertIn("Form submission failed", click_obs.error)
                self.assertIn("Invoice ID is required", click_obs.error)

                # 5. Classifier must classify this as VALIDATION -> CORRECT_DATA
                failure_type = classify_failure(click_obs.error, click_tool.name)
                self.assertEqual(failure_type, FailureType.VALIDATION)
                policy = get_recovery_policy(failure_type, retry_count=0)
                self.assertEqual(policy, "CORRECT_DATA")
            finally:
                await session.close()

        asyncio.run(run_test())

    def test_missing_invoice_verification_fails_and_clears_completion_summary(self):
        """When an invoice is missing from the Finance Portal during verification,

        runtime must set task status FAILED and never leave a misleading completion_summary.
        """
        async def run_test():
            non_existent_id = f"INV-NONEXISTENT-{uuid.uuid4().hex[:6].upper()}"

            # Direct verification check
            verifier = FinanceInvoiceVerifier(base_url="http://localhost:3000")
            direct_result = await verifier.verify(
                task_metadata={"domain": "finance"},
                source_reference={
                    "invoice_id": non_existent_id,
                    "company": "Nonexistent Corp",
                    "invoice_date": "2026-03-20",
                    "due_date": "2026-04-20",
                    "amount": "9999.00",
                },
            )
            self.assertFalse(direct_result.is_verified)
            self.assertIn(f"Invoice {non_existent_id} not found in Finance Portal.", direct_result.details)

            # Runtime task execution check: verifier failure must NOT retain optimistic completion_summary
            inv_dir = Path(__file__).resolve().parents[1] / "data" / "company" / "invoices"
            temp_file = inv_dir / f"temp_{non_existent_id.lower()}.txt"
            temp_file.write_text(
                f"INVOICE_NUMBER: {non_existent_id}\n"
                f"VENDOR: Nonexistent Corp\n"
                f"DATE: 2026-03-20\n"
                f"DUE_DATE: 2026-04-20\n"
                f"TOTAL_AMOUNT: 9999.00\n",
                encoding="utf-8",
            )
            rel_path = f"invoices/{temp_file.name}"

            mock_llm = SingleStepCompletionLLM(
                completion_summary=f"Invoice {non_existent_id} successfully entered into Finance Portal.",
                source_file=rel_path,
            )
            tool_reg = get_default_tool_registry()
            planner = Planner(llm_provider=mock_llm, tool_registry=tool_reg)

            runtime = AgentRuntime(
                llm_provider=mock_llm,
                tool_registry=tool_reg,
                planner=planner,
                max_dynamic_steps=3,
            )

            try:
                task = Task(
                    user_goal=f"Enter {non_existent_id} into Finance Portal.",
                    metadata={"domain": "finance", "source_document": rel_path},
                )
                result_task = await runtime.execute_task(task, use_dynamic_adaptation=True)

                self.assertEqual(result_task.status, TaskStatus.FAILED)
                self.assertEqual(runtime.state, AgentState.FAILED)
                self.assertIn(f"Invoice {non_existent_id} not found", result_task.metadata.get("error", ""))
                # Completion summary must be removed/absent, not claiming success
                self.assertNotIn("completion_summary", result_task.metadata)
            finally:
                temp_file.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_successful_invoice_creation_persisted_and_verified(self):
        """When all 5 required fields are filled and submitted, the invoice is actually

        persisted in the Finance Portal, verified independently, and completion metadata is consistent.
        """
        async def run_test():
            session = BrowserSession(headless=True)
            tool_reg = get_default_tool_registry(browser_session=session)
            unique_id = f"INV-TEST-{uuid.uuid4().hex[:6].upper()}"

            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                f.write(
                    f"INVOICE_NUMBER: {unique_id}\n"
                    f"VENDOR: Acme Corp\n"
                    f"DATE: 2026-03-20\n"
                    f"DUE_DATE: 2026-04-20\n"
                    f"TOTAL_AMOUNT: 18036.00\n"
                )
                doc_path = f.name

            try:
                navigate_tool = tool_reg.get("browser_navigate")
                type_tool = tool_reg.get("browser_type")
                click_tool = tool_reg.get("browser_click")

                # 1. Navigate to new invoice form
                nav_obs = await navigate_tool.execute(url="http://localhost:3000/finance/invoices/new")
                self.assertTrue(nav_obs.success)

                # 2. Enter ALL 5 required fields
                t1 = await type_tool.execute(target="invoice_id", text=unique_id)
                self.assertTrue(t1.success)

                t2 = await type_tool.execute(target="company", text="Acme Corp")
                self.assertTrue(t2.success)

                t3 = await type_tool.execute(target="invoice_date", text="2026-03-20")
                self.assertTrue(t3.success)

                t4 = await type_tool.execute(target="amount", text="18036.00")
                self.assertTrue(t4.success)

                t5 = await type_tool.execute(target="due_date", text="2026-04-20")
                self.assertTrue(t5.success)

                # 3. Submit and wait for save
                click_obs = await click_tool.execute(
                    target="Save Invoice",
                    text="Save Invoice",
                    role="button",
                    selector="#submit-invoice-button",
                )
                self.assertTrue(click_obs.success)

                # 4. Verify against real Finance Portal API independently
                verifier = FinanceInvoiceVerifier(base_url="http://localhost:3000")
                portal_data = await verifier.fetch_portal_invoice(unique_id)
                self.assertIsNotNone(portal_data)
                self.assertEqual(portal_data.get("invoice_id"), unique_id)
                self.assertEqual(float(portal_data.get("amount")), 18036.00)

                # 5. Independent ground truth verification
                v_res = await verifier.verify(
                    task_metadata={"domain": "finance", "source_document": doc_path},
                )
                self.assertTrue(v_res.is_verified)
                self.assertIn("successfully verified", v_res.details)
            finally:
                Path(doc_path).unlink(missing_ok=True)
                await session.close()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
