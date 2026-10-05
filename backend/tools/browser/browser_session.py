import os
from typing import Optional
from dotenv import load_dotenv
from playwright.async_api import Browser, BrowserContext, Page, async_playwright, Playwright

load_dotenv()


class BrowserSession:
    """Manages the lifecycle of a Playwright Chromium browser instance.

    Reuses the same browser, context, and page across multiple actions
    within a task execution session.
    """

    def __init__(self, headless: Optional[bool] = None) -> None:
        if headless is not None:
            self.headless = headless
        else:
            env_val = os.getenv("BROWSER_HEADLESS", "false").strip().lower()
            self.headless = env_val in ("true", "1", "yes")

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def get_page(self) -> Page:
        """Returns the active Page instance, initializing browser session if needed."""
        if self._page is not None and not self._page.is_closed():
            return self._page

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        if self._browser is None or not self._browser.is_connected():
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

        if self._context is None:
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="AURA-Agent-Browser/1.0",
            )

        self._page = await self._context.new_page()
        # Default navigation timeout to 15 seconds
        self._page.set_default_navigation_timeout(15000)
        self._page.set_default_timeout(10000)
        return self._page

    async def close(self) -> None:
        """Gracefully shuts down page, context, browser, and playwright runner."""
        if self._page and not self._page.is_closed():
            try:
                await self._page.close()
            except Exception:
                pass
        self._page = None

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = None

    @property
    def is_active(self) -> bool:
        return self._page is not None and not self._page.is_closed()
