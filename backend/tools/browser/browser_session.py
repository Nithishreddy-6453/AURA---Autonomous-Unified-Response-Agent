import asyncio
import logging
import os
from typing import Optional
from dotenv import load_dotenv
from playwright.async_api import Browser, BrowserContext, Page, async_playwright, Playwright

load_dotenv()

logger = logging.getLogger(__name__)


class BrowserSession:
    """Manages the lifecycle of a Playwright Chromium browser instance.

    Reuses the same browser, context, and page across multiple actions
    within a task execution session, ensuring safe teardown on completion,
    failure, exception, or cancellation.
    """

    def __init__(
        self,
        headless: Optional[bool] = None,
        navigation_timeout: int = 15000,
        action_timeout: int = 10000,
    ) -> None:
        if headless is not None:
            self.headless = headless
        else:
            env_val = os.getenv("BROWSER_HEADLESS", "false").strip().lower()
            self.headless = env_val in ("true", "1", "yes")

        self.navigation_timeout = navigation_timeout
        self.action_timeout = action_timeout

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def get_page(self) -> Page:
        """Returns the active Page instance, initializing browser session if needed."""
        if (
            self._page is not None
            and not self._page.is_closed()
            and self._browser is not None
            and self._browser.is_connected()
        ):
            return self._page

        # Clean up any partial or dead resources before fresh launch
        if self._browser is not None and not self._browser.is_connected():
            await self.close()

        try:
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

            if self._page is None or self._page.is_closed():
                self._page = await self._context.new_page()
                self._page.set_default_navigation_timeout(self.navigation_timeout)
                self._page.set_default_timeout(self.action_timeout)

            return self._page
        except Exception as e:
            logger.error(f"Failed to initialize browser page: {e}")
            await self.close()
            raise

    async def close(self) -> None:
        """Gracefully shuts down page, context, browser, and playwright runner.

        Safely handles exceptions at each stage and shields teardown against
        asyncio task cancellation so Chromium processes are never orphaned.
        """
        page, self._page = self._page, None
        context, self._context = self._context, None
        browser, self._browser = self._browser, None
        pw, self._playwright = self._playwright, None

        if page:
            try:
                if not page.is_closed():
                    await asyncio.shield(page.close())
            except Exception as e:
                logger.debug(f"Error closing page: {e}")

        if context:
            try:
                for p in getattr(context, "pages", []):
                    if p != page and not p.is_closed():
                        try:
                            await asyncio.shield(p.close())
                        except Exception:
                            pass
                await asyncio.shield(context.close())
            except Exception as e:
                logger.debug(f"Error closing context: {e}")

        if browser:
            try:
                if browser.is_connected():
                    await asyncio.shield(browser.close())
            except Exception as e:
                logger.debug(f"Error closing browser: {e}")

        if pw:
            try:
                await asyncio.shield(pw.stop())
            except Exception as e:
                logger.debug(f"Error stopping playwright: {e}")

    @property
    def is_active(self) -> bool:
        """Indicates whether an active page and connected browser exist."""
        return (
            self._page is not None
            and not self._page.is_closed()
            and self._browser is not None
            and self._browser.is_connected()
        )

    @property
    def has_active_browser(self) -> bool:
        """Indicates whether the underlying browser process is active and connected."""
        return self._browser is not None and self._browser.is_connected()

    @property
    def has_active_context(self) -> bool:
        """Indicates whether a browser context is currently allocated."""
        return self._context is not None

    async def __aenter__(self) -> "BrowserSession":
        await self.get_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
