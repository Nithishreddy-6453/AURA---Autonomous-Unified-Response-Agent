import asyncio
import os
import unittest
from pathlib import Path

from backend.tools.browser.browser_session import BrowserSession
from backend.tools.browser.browser_navigate import BrowserNavigateTool, is_url_allowed
from backend.tools.browser.browser_read import BrowserReadTool
from backend.tools.browser.browser_click import BrowserClickTool
from backend.tools.browser.browser_type import BrowserTypeTool
from backend.tools.browser.browser_screenshot import BrowserScreenshotTool
from backend.tools import get_default_tool_registry
from backend.models.observation import Observation


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_page.html"
LOCAL_TEST_URL = FIXTURE_PATH.resolve().as_uri()


class TestBrowserLayer(unittest.TestCase):
    """Test suite covering Playwright browser automation layer and security controls."""

    def test_url_security_whitelist(self):
        """Test URL validator allows localhost:3000 and project files, rejects arbitrary domains."""
        self.assertTrue(is_url_allowed("http://localhost:3000/finance"))
        self.assertTrue(is_url_allowed("http://localhost:3000/finance/invoices"))
        self.assertTrue(is_url_allowed("http://127.0.0.1:3000/finance"))
        self.assertTrue(is_url_allowed(LOCAL_TEST_URL))

        # Rejections:
        self.assertFalse(is_url_allowed("https://google.com"))
        self.assertFalse(is_url_allowed("http://malicious.com:3000"))
        self.assertFalse(is_url_allowed("http://localhost:8080"))
        self.assertFalse(is_url_allowed("ftp://localhost:3000"))
        self.assertFalse(is_url_allowed("file:///C:/Windows/system32/cmd.exe"))

    def test_browser_session_lifecycle(self):
        """Test browser session creation, page reuse, active status, context manager, and clean closure."""
        async def run_lifecycle():
            session = BrowserSession(headless=True)
            self.assertFalse(session.is_active)

            page1 = await session.get_page()
            self.assertTrue(session.is_active)
            self.assertIsNotNone(page1)

            # Same session reuses identical page
            page2 = await session.get_page()
            self.assertIs(page1, page2)

            await session.close()
            self.assertFalse(session.is_active)

            # Test async context manager
            async with BrowserSession(headless=True) as cm_session:
                self.assertTrue(cm_session.is_active)
            self.assertFalse(cm_session.is_active)

        asyncio.run(run_lifecycle())

    def test_local_page_navigation_read_click_type(self):
        """Test navigation, bounded read, typing, and clicking against local HTML test fixture."""
        async def run_flow():
            async with BrowserSession(headless=True) as session:
                navigate_tool = BrowserNavigateTool(session=session)
                read_tool = BrowserReadTool(session=session)
                type_tool = BrowserTypeTool(session=session)
                click_tool = BrowserClickTool(session=session)

                # 1. Navigation
                nav_obs = await navigate_tool.execute(url=LOCAL_TEST_URL)
                self.assertIsInstance(nav_obs, Observation)
                self.assertTrue(nav_obs.success, f"Navigation failed: {nav_obs.error}")
                self.assertEqual(nav_obs.result["title"], "AURA Browser Layer Test Environment")
                self.assertIn("file:", nav_obs.result["url"])

                # 2. Bounded Read (Full page overview)
                read_obs = await read_tool.execute()
                self.assertIsInstance(read_obs, Observation)
                self.assertTrue(read_obs.success)
                self.assertIn("AURA Browser Automation Test Page", read_obs.result["visible_text_summary"])
                self.assertGreater(len(read_obs.result["interactive_controls"]), 0)

                # 3. Read specific element by selector
                read_elem_obs = await read_tool.execute(selector="#status-box")
                self.assertTrue(read_elem_obs.success)
                self.assertEqual(read_elem_obs.result["visible_text_summary"], "Initial State")

                # 4. Typing into input field
                type_obs = await type_tool.execute(selector="#username", text="aura_tester")
                self.assertIsInstance(type_obs, Observation)
                self.assertTrue(type_obs.success, f"Typing failed: {type_obs.error}")
                self.assertEqual(type_obs.result["length"], len("aura_tester"))

                # 5. Clicking an action button and verifying DOM change
                click_obs = await click_tool.execute(selector="#action-btn")
                self.assertIsInstance(click_obs, Observation)
                self.assertTrue(click_obs.success, f"Click failed: {click_obs.error}")

                # Read updated status box
                updated_obs = await read_tool.execute(selector="#status-box")
                self.assertTrue(updated_obs.success)
                self.assertEqual(updated_obs.result["visible_text_summary"], "Action Button Clicked")

        asyncio.run(run_flow())

    def test_invalid_selector_handling(self):
        """Test graceful error reporting when targeting non-existent or invalid selectors."""
        async def run_invalid():
            async with BrowserSession(headless=True) as session:
                navigate_tool = BrowserNavigateTool(session=session)
                type_tool = BrowserTypeTool(session=session)
                click_tool = BrowserClickTool(session=session)

                await navigate_tool.execute(url=LOCAL_TEST_URL)

                # Click non-existent selector
                click_obs = await click_tool.execute(selector="#does-not-exist-btn")
                self.assertIsInstance(click_obs, Observation)
                self.assertFalse(click_obs.success)
                self.assertIsNotNone(click_obs.error)
                self.assertIn("Failed to click element", click_obs.error)

                # Type into non-existent selector
                type_obs = await type_tool.execute(selector="#does-not-exist-input", text="test")
                self.assertIsInstance(type_obs, Observation)
                self.assertFalse(type_obs.success)
                self.assertIsNotNone(type_obs.error)
                self.assertIn("Failed to type into target", type_obs.error)

                # Missing parameters
                empty_click = await click_tool.execute()
                self.assertFalse(empty_click.success)
                self.assertIn("Must specify", empty_click.error)

                empty_type = await type_tool.execute(text="something")
                self.assertFalse(empty_type.success)
                self.assertIn("Must specify", empty_type.error)

        asyncio.run(run_invalid())

    def test_navigation_failure_handling(self):
        """Test error handling when navigation targets unauthorized domains, invalid URLs, or empty strings."""
        async def run_nav_failures():
            async with BrowserSession(headless=True) as session:
                navigate_tool = BrowserNavigateTool(session=session)

                # Empty URL
                obs_empty = await navigate_tool.execute(url="")
                self.assertFalse(obs_empty.success)
                self.assertIn("cannot be empty", obs_empty.error)

                # Unauthorized domain
                obs_unauth = await navigate_tool.execute(url="https://external-website.com")
                self.assertFalse(obs_unauth.success)
                self.assertIn("Navigation rejected", obs_unauth.error)

                # Unauthorized port
                obs_port = await navigate_tool.execute(url="http://localhost:8080/portal")
                self.assertFalse(obs_port.success)
                self.assertIn("Navigation rejected", obs_port.error)

        asyncio.run(run_nav_failures())

    def test_finance_portal_poc(self):
        """Proof-of-concept verifying browser tools interact with the running local Finance Portal."""
        async def run_portal_poc():
            async with BrowserSession(headless=True) as session:
                navigate_tool = BrowserNavigateTool(session=session)
                read_tool = BrowserReadTool(session=session)
                click_tool = BrowserClickTool(session=session)

                # Navigate to Finance Overview
                nav_obs = await navigate_tool.execute(url="http://localhost:3000/finance")
                self.assertTrue(nav_obs.success, f"Navigation to Finance Portal failed: {nav_obs.error}")
                self.assertEqual(nav_obs.result["status_code"], 200)

                # Read page content
                read_obs = await read_tool.execute()
                self.assertTrue(read_obs.success)
                self.assertIn("Finance Overview", read_obs.result["visible_text_summary"])

                # Click navigation link to Invoices list
                click_obs = await click_tool.execute(text="View Invoices")
                self.assertTrue(click_obs.success, f"Click failed: {click_obs.error}")
                self.assertIn("/finance/invoices", click_obs.result["url"])

        asyncio.run(run_portal_poc())

    def test_browser_tools_in_default_registry(self):
        """Test that all browser tools are present in the default ToolRegistry with valid specifications."""
        reg = get_default_tool_registry()
        expected = [
            "browser_navigate",
            "browser_read",
            "browser_click",
            "browser_type",
            "browser_screenshot",
        ]
        for name in expected:
            self.assertTrue(reg.has(name), f"Missing tool in registry: {name}")
            tool = reg.get(name)
            self.assertIsNotNone(tool.description)
            self.assertIn("type", tool.input_schema)
            self.assertEqual(tool.input_schema["type"], "object")

        specs = reg.get_tool_specs()
        spec_names = [s["name"] for s in specs]
        for name in expected:
            self.assertIn(name, spec_names)


if __name__ == "__main__":
    unittest.main()
