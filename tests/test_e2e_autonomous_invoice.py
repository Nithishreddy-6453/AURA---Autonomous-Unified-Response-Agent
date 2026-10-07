import asyncio
import json
import unittest
from pathlib import Path

from backend.agent.planner import Planner
from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState
from backend.llm.base import LLMProvider
from backend.models.task import Task, TaskStatus
from backend.tools import ToolRegistry, get_default_tool_registry
from backend.tools.browser.browser_session import BrowserSession


class MockAutonomousLLMProvider(LLMProvider):
    """Predictable deterministic test double simulating autonomous reasoning for E2E testing."""

    def __init__(self):
        self.step_index = 0
        self.step_sequence = [
            # Step 1: Read the latest Acme invoice discovered from search
            {
                "is_complete": False,
                "reasoning": "Search matches show acme_invoice_2026_01.txt and acme_invoice_2026_03.txt. 2026-03 is later than 2026-01, so read acme_invoice_2026_03.txt.",
                "action": {
                    "tool_name": "read_company_file",
                    "arguments": {"file_path": "invoices/acme_invoice_2026_03.txt"}
                }
            },
            # Step 2: Extract structured fields from file
            {
                "is_complete": False,
                "reasoning": "Invoice text loaded. Extract structured fields (ID, date, amount, vendor).",
                "action": {
                    "tool_name": "document_extract",
                    "arguments": {"file_path": "invoices/acme_invoice_2026_03.txt"}
                }
            },
            # Step 3: Open Finance Portal new invoice form
            {
                "is_complete": False,
                "reasoning": "Extracted invoice INV-2026-0089 with amount 18036.00. Navigate to Finance Portal new invoice page.",
                "action": {
                    "tool_name": "browser_navigate",
                    "arguments": {"url": "http://localhost:3000/finance/invoices/new"}
                }
            },
            # Step 4: Type invoice_id
            {
                "is_complete": False,
                "reasoning": "Type Invoice ID into form.",
                "action": {
                    "tool_name": "browser_type",
                    "arguments": {"target": "invoice_id", "text": "INV-2026-0089"}
                }
            },
            # Step 5: Type company
            {
                "is_complete": False,
                "reasoning": "Type Company into form.",
                "action": {
                    "tool_name": "browser_type",
                    "arguments": {"target": "company", "text": "Acme Corp"}
                }
            },
            # Step 6: Type invoice_date
            {
                "is_complete": False,
                "reasoning": "Type Invoice Date into form.",
                "action": {
                    "tool_name": "browser_type",
                    "arguments": {"target": "invoice_date", "text": "2026-03-20"}
                }
            },
            # Step 7: Type amount
            {
                "is_complete": False,
                "reasoning": "Type Total Amount into form.",
                "action": {
                    "tool_name": "browser_type",
                    "arguments": {"target": "amount", "text": "18036.00"}
                }
            },
            # Step 8: Type due_date
            {
                "is_complete": False,
                "reasoning": "Type Due Date into form.",
                "action": {
                    "tool_name": "browser_type",
                    "arguments": {"target": "due_date", "text": "2026-04-20"}
                }
            },
            # Step 8: Click Save Invoice
            {
                "is_complete": False,
                "reasoning": "All required fields filled. Click Save Invoice.",
                "action": {
                    "tool_name": "browser_click",
                    "arguments": {"text": "Save Invoice"}
                }
            },
            # Step 9: Capture Evidence Screenshot
            {
                "is_complete": False,
                "reasoning": "Form submitted. Capture evidence screenshot of invoice in portal.",
                "action": {
                    "tool_name": "browser_screenshot",
                    "arguments": {"name": "acme_invoice_submitted_evidence"}
                }
            },
            # Final: Complete
            {
                "is_complete": True,
                "completion_summary": "Discovered latest invoice acme_invoice_2026_03.txt (INV-2026-0089, amount $18,036.00), entered all fields into the Finance Portal, submitted the invoice, and recorded screenshot evidence.",
                "reasoning": "Task accomplished.",
                "action": None
            }
        ]

    async def generate(self, prompt: str, system_instruction: str = None, temperature: float = 0.0, **kwargs):
        # Initial Plan formulation
        if "Available Tools:" in prompt and "Execution History & Observations:" not in prompt:
            return json.dumps({
                "goal": "Find the latest Acme invoice and enter it into the Finance Portal.",
                "is_feasible": True,
                "unsupported_reason": None,
                "actions": [
                    {
                        "tool_name": "search_company_files",
                        "arguments": {"query": "Acme invoice", "category": "invoices"}
                    }
                ]
            })

        # Dynamic reasoning steps
        if self.step_index < len(self.step_sequence):
            step = self.step_sequence[self.step_index]
            self.step_index += 1
            return json.dumps(step)

        return json.dumps({
            "is_complete": True,
            "completion_summary": "Task complete.",
            "action": None
        })

    async def chat(self, messages, temperature: float = 0.0, **kwargs):
        return ""


class TestEndToEndAutonomousInvoice(unittest.TestCase):
    """End-to-End integration test for autonomous invoice processing workflow."""

    def test_e2e_autonomous_invoice_workflow(self):
        async def run_e2e():
            session = BrowserSession(headless=True)
            tool_registry = get_default_tool_registry(browser_session=session)
            mock_llm = MockAutonomousLLMProvider()
            planner = Planner(llm_provider=mock_llm, tool_registry=tool_registry)

            action_log = []
            obs_log = []

            runtime = AgentRuntime(
                llm_provider=mock_llm,
                tool_registry=tool_registry,
                planner=planner,
                on_action=lambda a: action_log.append(a),
                on_observation=lambda a, o: obs_log.append(o),
            )

            task = Task(user_goal="Find the latest Acme invoice and enter it into the Finance Portal.")
            result_task = await runtime.execute_task(task, use_dynamic_adaptation=True)

            try:
                # 1. State and task status checks
                self.assertEqual(result_task.status, TaskStatus.COMPLETED)
                self.assertEqual(runtime.state, AgentState.COMPLETED)

                # 2. File discovery check: latest Acme invoice identified
                action_tools = [a.tool_name for a in runtime.executed_actions]
                self.assertIn("search_company_files", action_tools)
                self.assertIn("read_company_file", action_tools)
                self.assertIn("document_extract", action_tools)

                # 3. Browser actions check
                self.assertIn("browser_navigate", action_tools)
                self.assertIn("browser_type", action_tools)
                self.assertIn("browser_click", action_tools)
                self.assertIn("browser_screenshot", action_tools)

                # 4. Check screenshot file was created
                screenshot_obs = [o for o in runtime.observations if o.result and "evidence_path" in o.result]
                self.assertGreater(len(screenshot_obs), 0)
                evidence_path = screenshot_obs[0].result["evidence_path"]
                self.assertTrue(Path(evidence_path).exists())

                # 5. Check completion summary exists
                self.assertIn("completion_summary", result_task.metadata)
                self.assertIn("INV-2026-0089", result_task.metadata["completion_summary"])
            finally:
                await session.close()

        asyncio.run(run_e2e())


if __name__ == "__main__":
    unittest.main()
