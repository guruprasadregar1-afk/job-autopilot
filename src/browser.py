import os
import sys
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright, BrowserContext, Page, Playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "browser_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

def cleanup_startup_tabs(context: BrowserContext) -> None:
    """
    On launch, closes every restored or pre-existing tab (including tabs
    whose URL is still empty or loading) and leaves exactly one clean blank tab,
    BEFORE any navigation or validation occurs.
    """
    old_pages = list(context.pages)
    # Open one pristine blank page before closing restored pages
    context.new_page()
    for page in old_pages:
        try:
            page.close()
        except Exception:
            pass

def validate_startup_tabs(context: BrowserContext) -> None:
    """
    Aborts the run if any open tab's URL is not on the allowlist (or blank).
    Protects profile, feed, settings, or external pages from being open at startup.
    """
    from src.policy import PolicyEngine, CriticalPolicyViolationError, PolicyBlockError

    for page in context.pages:
        url = page.url.strip()
        # Allow empty or blank initial tabs
        if not url or url in ("about:blank", "chrome://newtab/", "edge://newtab/"):
            continue
        try:
            PolicyEngine.validate_navigation(url)
        except (CriticalPolicyViolationError, PolicyBlockError) as e:
            raise CriticalPolicyViolationError(
                f"CRITICAL VIOLATION: Disallowed URL found in open browser tab at startup: '{url}'. Aborting run immediately."
            ) from e

def ensure_clean_tabs(context: BrowserContext) -> None:
    """
    Re-checks open tabs immediately before the first navigation of every run.
    If a restored tab appeared asynchronously after initial cleanup, closes any
    that are not blank and re-validates startup tabs to guarantee only clean tabs remain.
    """
    for page in list(context.pages):
        url = page.url.strip()
        is_blank = (not url) or (url in ("about:blank", "chrome://newtab/", "edge://newtab/"))
        if not is_blank:
            try:
                page.close()
            except Exception:
                pass
            if hasattr(context, "pages") and isinstance(context.pages, list) and page in context.pages:
                try:
                    context.pages.remove(page)
                except ValueError:
                    pass
    if len(context.pages) == 0:
        cleanup_startup_tabs(context)
    validate_startup_tabs(context)

class BrowserManager:
    def __init__(self, headless: bool = False, profile_dir: Optional[Path] = None):
        self.headless = headless
        self.profile_dir = profile_dir or PROFILE_DIR
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None

    def start(self, validate_tabs: bool = True) -> BrowserContext:
        """
        Launches persistent Chromium context.
        Cookies and login sessions persist inside browser_profile/.
        """
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel="msedge",
            headless=self.headless,
            viewport={"width": 1280, "height": 800},
            args=[
                "--start-maximized"
            ]
        )
        if validate_tabs:
            cleanup_startup_tabs(self.context)
            validate_startup_tabs(self.context)
        return self.context

    def close(self) -> None:
        if self.context:
            self.context.close()
            self.context = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
