import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from backend.agent.planner import Planner
from backend.agent.schemas import NextActionResponseSchema
from backend.llm.base import LLMProvider
from backend.models.action import Action
from backend.models.observation import Observation
from backend.models.task import Task, TaskStatus
from backend.tools import ToolRegistry
from backend.tools.browser.browser_navigate import BrowserNavigateTool, is_url_allowed
from backend.tools.browser.browser_session import BrowserSession


class MockDecisionLLM(LLMProvider):
    """Mock LLM to verify Planner next-action decisions."""

    def __init__(self, response_json: str):
        self.response_json = response_json

    async def generate(self, prompt: str, system_instruction: str = None, temperature: float = 0.0, **kwargs):
        # Verify guidelines are included in prompt
        return self.response_json

    async def chat(self, messages, temperature: float = 0.0, **kwargs):
        return ""


class TestBrowserNavigationValidation(unittest.TestCase):
    """Regression test suite for browser navigation content extraction, default title

    handling, error page detection, and security constraints.
    """

    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures" / "temp_nav_test"
        self.fixtures_dir.mkdir(parents=True, exist_ok=True)
        self.created_files = []

    def tearDown(self):
        for f in self.created_files:
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass
        try:
            if self.fixtures_dir.exists():
                self.fixtures_dir.rmdir()
        except Exception:
            pass

    def _create_html_fixture(self, title: str, body_html: str) -> str:
        file_path = self.fixtures_dir / f"fixture_{len(self.created_files)}.html"
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
</head>
<body>
    {body_html}
</body>
</html>"""
        file_path.write_text(html_content, encoding="utf-8")
        self.created_files.append(file_path)
        return file_path.resolve().as_uri()

    def test_navigation_security_rejects_disallowed_urls(self):
        """Verify that external origins and unauthorized ports are rejected."""
        self.assertFalse(is_url_allowed("https://external-banking.com/finance"))
        self.assertFalse(is_url_allowed("http://localhost:8080/finance"))
        self.assertFalse(is_url_allowed("ftp://localhost:3000/finance"))

        async def run_disallowed():
            session = BrowserSession(headless=True)
            try:
                tool = BrowserNavigateTool(session=session)
                obs = await tool.execute(url="https://external-banking.com/finance")
                self.assertFalse(obs.success)
                self.assertIn("Navigation rejected", obs.error)
            finally:
                await session.close()

        asyncio.run(run_disallowed())

    def test_navigation_extracts_heading_and_content_with_default_title(self):
        """Verify that a page with default title 'Create Next App' extracts genuine visible

        heading and content snippet without treating the default title as a failure.
        """
        fixture_url = self._create_html_fixture(
            title="Create Next App",
            body_html="""<main>
                <h1>Invoice INV-2026-0095</h1>
                <p>Acme Corp</p>
                <p>Date: 2026-04-15</p>
                <p>Total: $19,116.00</p>
            </main>""",
        )

        async def run_nav():
            session = BrowserSession(headless=True)
            try:
                tool = BrowserNavigateTool(session=session)
                obs = await tool.execute(url=fixture_url)

                self.assertTrue(obs.success)
                self.assertEqual(obs.result["title"], "Create Next App")
                self.assertEqual(obs.result["heading"], "Invoice INV-2026-0095")
                self.assertIsNotNone(obs.result["content_snippet"])
                self.assertIn("Acme Corp", obs.result["content_snippet"])
                self.assertIn("19,116.00", obs.result["content_snippet"])

                # Test planner with this observation
                mock_llm = MockDecisionLLM(
                    json.dumps({
                        "is_complete": True,
                        "needs_human": False,
                        "completion_summary": "Invoice INV-2026-0095 verified in Finance Portal with amount $19,116.00.",
                        "reasoning": "Navigation succeeded, and invoice heading and content confirm the record is visible.",
                        "action": None,
                    })
                )
                tool_reg = ToolRegistry()
                tool_reg.register(tool)
                planner = Planner(llm_provider=mock_llm, tool_registry=tool_reg)

                task = Task(user_goal="Inspect invoice INV-2026-0095")
                decision = await planner.decide_next_action(
                    task=task,
                    action_history=[Action(tool_name="browser_navigate", arguments={"url": fixture_url})],
                    observations=[obs],
                )

                self.assertFalse(decision.needs_human)
                self.assertTrue(decision.is_complete)
                self.assertIn("INV-2026-0095", decision.completion_summary)
            finally:
                await session.close()

        asyncio.run(run_nav())

    def test_navigation_handles_missing_heading_and_empty_content_safely(self):
        """Verify that pages without headings or body text are safely handled without crashing."""
        fixture_url = self._create_html_fixture(
            title="Blank Page",
            body_html="",
        )

        async def run_blank():
            session = BrowserSession(headless=True)
            try:
                tool = BrowserNavigateTool(session=session)
                obs = await tool.execute(url=fixture_url)

                self.assertTrue(obs.success)
                self.assertEqual(obs.result["title"], "Blank Page")
                self.assertIsNone(obs.result["heading"])
                self.assertIsNone(obs.result["content_snippet"])
            finally:
                await session.close()

        asyncio.run(run_blank())

    def test_navigation_genuinely_missing_page_detected(self):
        """Verify that a page indicating 'Invoice Not Found' reflects the error in heading

        and content snippet rather than falsely declaring success.
        """
        fixture_url = self._create_html_fixture(
            title="Create Next App",
            body_html="""<main>
                <div id="invoice-not-found">
                    <h1>Invoice Not Found</h1>
                    <p>No invoice with ID INV-9999-0000 was found in the system.</p>
                </div>
            </main>""",
        )

        async def run_missing():
            session = BrowserSession(headless=True)
            try:
                tool = BrowserNavigateTool(session=session)
                obs = await tool.execute(url=fixture_url)

                self.assertTrue(obs.success)
                self.assertEqual(obs.result["title"], "Create Next App")
                self.assertEqual(obs.result["heading"], "Invoice Not Found")
                self.assertIn("No invoice with ID", obs.result["content_snippet"])
            finally:
                await session.close()

        asyncio.run(run_missing())


if __name__ == "__main__":
    unittest.main()
