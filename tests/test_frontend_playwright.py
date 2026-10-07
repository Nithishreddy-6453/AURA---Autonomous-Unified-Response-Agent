import asyncio
import unittest
from playwright.async_api import async_playwright


class TestControlCenterPlaywright(unittest.IsolatedAsyncioTestCase):
    """Playwright browser test for AURA Control Center frontend on port 3001."""

    async def test_control_center_ui_flow(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # 1. Navigate to Control Center
            await page.goto("http://localhost:3001", timeout=15000)

            # 2. Verify Header & Connection Status
            title = await page.title()
            self.assertIn("AURA", title)

            # Wait for initial async health check
            await page.wait_for_selector("text=API Connected", timeout=10000)
            header_text = await page.locator("header").text_content()
            self.assertIn("AURA", header_text)
            self.assertIn("API Connected", header_text)

            # 3. Verify Task Input
            textarea = page.locator("#user-goal")
            self.assertTrue(await textarea.is_visible())

            # Click example button
            example_btn = page.locator("text=Insert Acme Invoice Example")
            await example_btn.click()

            entered_val = await textarea.input_value()
            self.assertIn("Acme", entered_val)

            # 4. Verify Task History section
            history_sec = page.locator("text=Recent Tasks")
            self.assertTrue(await history_sec.is_visible())

            # 5. Verify Timeline section
            timeline_sec = page.locator("text=Live Activity Timeline")
            self.assertTrue(await timeline_sec.is_visible())

            await browser.close()
            print("\n[PASS] Playwright frontend browser tests passed successfully.")


if __name__ == "__main__":
    unittest.main()
