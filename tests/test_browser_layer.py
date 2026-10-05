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


class TestBrowserLayer(unittest.TestCase):
    """Test suite covering Playwright browser automation layer and security controls."""

    def test_url_security_whitelist(self):
        """Test URL validator allows localhost:3000 and rejects arbitrary domains."""
        self.assertTrue(is_url_allowed("http://localhost:3000/finance"))
        self.assertTrue(is_url_allowed("http://localhost:3000/finance/invoices"))
        self.assertTrue(is_url_allowed("http://127.0.0.1:3000/finance"))

        # Rejections:
        self.assertFalse(is_url_allowed("https://google.com"))
        self.assertFalse(is_url_allowed("http://malicious.com:3000"))
        self.assertFalse(is_url_allowed("http://localhost:8080"))
        self.assertFalse(is_url_allowed("ftp://localhost:3000"))

    def test_reject_unauthorized_navigation(self):
        """Test that browser_navigate rejects unauthorized external URLs."""
        async def run_test():
            session = BrowserSession(headless=True)
            try:
                navigate_tool = BrowserNavigateTool(session=session)
                obs = await navigate_tool.execute(url="https://example.com")
                self.assertFalse(obs.success)
                self.assertIn("Navigation rejected", obs.error)
            finally:
                await session.close()

        asyncio.run(run_test())

    def test_browser_workflow_and_lifecycle(self):
        """Test complete browser workflow: session startup, navigation, read, click, type, screenshot, and cleanup."""
        async def run_workflow():
            session = BrowserSession(headless=True)
            try:
                navigate_tool = BrowserNavigateTool(session=session)
                read_tool = BrowserReadTool(session=session)
                click_tool = BrowserClickTool(session=session)
                type_tool = BrowserTypeTool(session=session)
                screenshot_tool = BrowserScreenshotTool(session=session)

                # 1. Navigation
                nav_obs = await navigate_tool.execute(url="http://localhost:3000/finance")
                self.assertTrue(nav_obs.success, f"Navigation failed: {nav_obs.error}")
                self.assertEqual(nav_obs.result["status_code"], 200)

                # 2. Reading
                read_obs = await read_tool.execute()
                self.assertTrue(read_obs.success)
                self.assertIn("Finance Overview", read_obs.result["visible_text_summary"])
                self.assertGreater(len(read_obs.result["interactive_controls"]), 0)

                # 3. Clicking
                click_obs = await click_tool.execute(text="View Invoices")
                self.assertTrue(click_obs.success, f"Click failed: {click_obs.error}")
                self.assertIn("/finance/invoices", click_obs.result["url"])

                # 4. Typing
                type_obs = await type_tool.execute(target="invoice-search-input", text="Acme")
                self.assertTrue(type_obs.success, f"Type failed: {type_obs.error}")
                self.assertEqual(type_obs.result["length"], 4)

                # 5. Screenshot
                snap_obs = await screenshot_tool.execute(name="test_portal_workflow_snap")
                self.assertTrue(snap_obs.success, f"Screenshot failed: {snap_obs.error}")
                self.assertTrue(os.path.exists(snap_obs.result["evidence_path"]))

                # Verify session remains active
                self.assertTrue(session.is_active)
            finally:
                # 6. Cleanup
                await session.close()
                self.assertFalse(session.is_active)

        asyncio.run(run_workflow())

    def test_browser_tools_in_default_registry(self):
        """Test that browser tools are registered in default registry."""
        reg = get_default_tool_registry()
        expected = [
            "search_company_files",
            "read_company_file",
            "document_extract",
            "browser_navigate",
            "browser_read",
            "browser_click",
            "browser_type",
            "browser_screenshot",
        ]
        for name in expected:
            self.assertTrue(reg.has(name), f"Missing tool: {name}")


if __name__ == "__main__":
    unittest.main()
