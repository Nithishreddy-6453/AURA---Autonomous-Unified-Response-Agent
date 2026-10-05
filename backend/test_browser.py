import asyncio
import os
import sys

from backend.tools.browser.browser_session import BrowserSession
from backend.tools.browser.browser_navigate import BrowserNavigateTool
from backend.tools.browser.browser_read import BrowserReadTool
from backend.tools.browser.browser_click import BrowserClickTool
from backend.tools.browser.browser_screenshot import BrowserScreenshotTool


async def main():
    print("=" * 60)
    print("AURA Browser Layer: Manual Verification Script")
    print("=" * 60)

    # Use headless=False if configured or fallback to True for CLI tests
    env_headless = os.getenv("BROWSER_HEADLESS", "false").strip().lower() in ("true", "1", "yes")
    print(f"Browser Mode: {'Headless' if env_headless else 'Headed/Visible'}")

    session = BrowserSession(headless=env_headless)
    navigate_tool = BrowserNavigateTool(session=session)
    read_tool = BrowserReadTool(session=session)
    click_tool = BrowserClickTool(session=session)
    screenshot_tool = BrowserScreenshotTool(session=session)

    try:
        # Step 1: Open Finance Portal and navigate to /finance
        portal_url = os.getenv("FINANCE_PORTAL_URL", "http://localhost:3000/finance")
        print(f"\n[1] Navigating to: {portal_url}...")
        obs = await navigate_tool.execute(url=portal_url)
        print(f"    Observation Status: {'SUCCESS' if obs.success else 'FAILED'}")
        if not obs.success:
            print(f"    Error: {obs.error}")
            sys.exit(1)
        print(f"    Result: {obs.result}")

        # Step 2: Read the /finance page
        print("\n[2] Reading page state at /finance...")
        obs = await read_tool.execute(max_elements=15)
        print(f"    Observation Status: {'SUCCESS' if obs.success else 'FAILED'}")
        print(f"    Title: {obs.result.get('title')}")
        print(f"    URL: {obs.result.get('url')}")
        print("    Visible Text Snippet:")
        for line in obs.result.get("visible_text_summary", "").splitlines()[:5]:
            print(f"      | {line}")

        # Step 3: Click "View Invoices"
        print("\n[3] Clicking 'View Invoices'...")
        obs = await click_tool.execute(text="View Invoices")
        print(f"    Observation Status: {'SUCCESS' if obs.success else 'FAILED'}")
        if not obs.success:
            print(f"    Error: {obs.error}")
            sys.exit(1)
        print(f"    Navigated to: {obs.result.get('url')}")

        # Step 4: Read the invoice page
        print("\n[4] Reading invoice page state at /finance/invoices...")
        obs = await read_tool.execute(max_elements=15)
        print(f"    Observation Status: {'SUCCESS' if obs.success else 'FAILED'}")
        print(f"    Title: {obs.result.get('title')}")
        print(f"    URL: {obs.result.get('url')}")
        print("    Visible Text Snippet:")
        for line in obs.result.get("visible_text_summary", "").splitlines()[:5]:
            print(f"      | {line}")

        # Step 5: Capture a screenshot
        print("\n[5] Taking screenshot...")
        obs = await screenshot_tool.execute(name="finance_portal_invoices_view")
        print(f"    Observation Status: {'SUCCESS' if obs.success else 'FAILED'}")
        evidence_path = obs.result.get("evidence_path")
        print(f"    Evidence Saved At: {evidence_path}")

        print("\n" + "=" * 60)
        print("[SUCCESS] All manual browser verification steps completed successfully!")
        print("=" * 60)

    finally:
        # Step 6: Close browser session
        print("\n[6] Closing browser session...")
        await session.close()
        print("    Browser closed cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
