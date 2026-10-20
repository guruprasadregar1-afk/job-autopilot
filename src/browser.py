import os
import sys
import datetime
from collections import deque
from pathlib import Path
from typing import Optional, Any
from playwright.sync_api import sync_playwright, BrowserContext, Page, Playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "browser_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)
LIFECYCLE_LOG_PATH = PROJECT_ROOT / "logs" / "browser_lifecycle.log"

_LAST_BROWSER_ACTION = "Initialized"
_CURRENT_JOB_ID: Optional[str] = None
_RECENT_REQUESTS = deque(maxlen=20)
_CODE_CLOSE_CALLS = []

def set_current_job_id(job_id: Optional[str]) -> None:
    """Sets current active job ID for diagnostic lifecycle logging."""
    global _CURRENT_JOB_ID
    _CURRENT_JOB_ID = job_id

def get_current_job_id() -> str:
    """Returns current active job ID or 'N/A'."""
    return _CURRENT_JOB_ID or "N/A"

def record_request_url(url: str) -> None:
    """Records HTTP request URL into recent requests circular buffer (last 20)."""
    _RECENT_REQUESTS.append(url)

def get_recent_requests() -> list:
    """Returns list of last 20 request URLs."""
    return list(_RECENT_REQUESTS)

def record_browser_action(action: str) -> None:
    """Updates the tracked last browser action for lifecycle diagnostic logs."""
    global _LAST_BROWSER_ACTION
    _LAST_BROWSER_ACTION = action

def get_last_browser_action() -> str:
    """Returns the tracked last browser action."""
    return _LAST_BROWSER_ACTION

def log_lifecycle_event(event_type: str, details: str = "") -> None:
    """Logs browser lifecycle events to logs/browser_lifecycle.log with timestamps, job ID, and last action."""
    try:
        LIFECYCLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().isoformat()
        action = get_last_browser_action()
        job_id = get_current_job_id()
        line = f"[{ts}] JOB_ID={job_id} | EVENT={event_type} | LAST_ACTION={action} | DETAILS={details}\n"
        with open(LIFECYCLE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

def record_code_close_call(target: Any, caller: str) -> None:
    """
    Records an intentional .close() call made by our bot code before calling .close()
    on a page, context, or browser.
    """
    ts = datetime.datetime.now().isoformat()
    target_type = "unknown"
    target_id = id(target)
    raw_target = getattr(target, "_page", target)
    raw_id = id(raw_target)

    if isinstance(target, str):
        target_type = target.lower()
    else:
        type_name = type(target).__name__.lower()
        if hasattr(target, "goto") or hasattr(raw_target, "goto") or "page" in type_name:
            target_type = "page"
            try:
                setattr(target, "_code_close_called", True)
                setattr(raw_target, "_code_close_called", True)
            except Exception:
                pass
        elif hasattr(target, "new_page") or "context" in type_name:
            target_type = "context"
            try:
                setattr(target, "_code_close_called", True)
            except Exception:
                pass
        elif "browsermanager" in type_name or "browser" in type_name:
            target_type = "browser"
            try:
                setattr(target, "_code_close_called", True)
            except Exception:
                pass

    _CODE_CLOSE_CALLS.append({
        "timestamp": ts,
        "caller": caller,
        "target_type": target_type,
        "target_id": target_id,
        "raw_id": raw_id
    })
    log_lifecycle_event("CODE_CLOSE_CALL", f"target={target_type} | caller={caller} | id={target_id}")

def was_code_close_called(target: Any) -> bool:
    """Checks whether a CODE_CLOSE_CALL preceded closing for the given target."""
    if getattr(target, "_code_close_called", False) is True:
        return True
    raw_target = getattr(target, "_page", target)
    if getattr(raw_target, "_code_close_called", False) is True:
        return True
    target_id = id(target)
    raw_id = id(raw_target)
    for call in _CODE_CLOSE_CALLS:
        if call.get("target_id") == target_id or call.get("raw_id") == raw_id:
            return True
    return False

def clear_code_close_calls() -> None:
    """Clears the code close calls history (used for test isolation)."""
    global _CODE_CLOSE_CALLS, _RECENT_REQUESTS
    _CODE_CLOSE_CALLS = []
    _RECENT_REQUESTS.clear()

def attach_lifecycle_listeners(context: BrowserContext, anchor_page: Optional[Page] = None) -> None:
    """
    Attaches diagnostic lifecycle listeners for page close, context close,
    browser disconnect, crash, and popup events, recording detailed metrics to
    logs/browser_lifecycle.log.
    """
    def on_page_crash(p):
        try:
            setattr(p, "_crashed", True)
        except Exception:
            pass
        url = ""
        try:
            url = getattr(p, "url", "")
        except Exception:
            pass
        log_lifecycle_event("PAGE_CRASH", f"Page crashed (url='{url}')")

    def on_page_popup(popup):
        url = ""
        try:
            url = getattr(popup, "url", "")
        except Exception:
            pass
        log_lifecycle_event("PAGE_POPUP", f"Popup created (url='{url}')")

    def on_page_dialog(dialog):
        try:
            d_type = getattr(dialog, "type", "")
            d_msg = getattr(dialog, "message", "")
            log_lifecycle_event("PAGE_DIALOG", f"Dialog opened (type='{d_type}', message='{d_msg}')")
        except Exception:
            pass

    def on_frame_navigated(frame):
        try:
            if hasattr(frame, "page") and frame.page and frame == getattr(frame.page, "main_frame", None):
                url = getattr(frame, "url", "")
                log_lifecycle_event("PAGE_NAVIGATED", f"Frame navigated (url='{url}')")
        except Exception:
            pass

    def on_request(request):
        try:
            req_url = getattr(request, "url", "")
            if req_url:
                record_request_url(req_url)
        except Exception:
            pass

    def on_download_created(download):
        try:
            d_url = getattr(download, "url", "")
            d_file = getattr(download, "suggested_filename", "")
            log_lifecycle_event("DOWNLOAD_CREATED", f"Download initiated (url='{d_url}', filename='{d_file}')")
        except Exception:
            pass

    def on_page_close(p):
        url = ""
        try:
            url = getattr(p, "url", "")
        except Exception:
            pass
        init_url = getattr(p, "_initial_url", "")
        url_changed = bool(init_url and url != init_url)
        crashed = getattr(p, "_crashed", False)

        other_open_pages_count = 0
        try:
            ctx = getattr(p, "context", None) or context
            pages = getattr(ctx, "pages", [])
            for other in pages:
                if other is not p:
                    try:
                        if hasattr(other, "is_closed"):
                            res = other.is_closed()
                            if not (res is True):
                                other_open_pages_count += 1
                        else:
                            other_open_pages_count += 1
                    except Exception:
                        pass
        except Exception:
            pass

        closed_by_code = was_code_close_called(p)
        if not closed_by_code:
            ctx = getattr(p, "context", None) or context
            if ctx is not None and was_code_close_called(ctx):
                closed_by_code = True
            elif any(c.get("target_type") in ("context", "browser") for c in _CODE_CLOSE_CALLS):
                closed_by_code = True

        details = (
            f"Page closed (url='{url}', initial_url='{init_url}', "
            f"url_changed={url_changed}, crashed={crashed}, "
            f"other_open_pages={other_open_pages_count}, "
            f"closed_by_code={'true' if closed_by_code else 'false'})"
        )
        log_lifecycle_event("PAGE_CLOSE", details)

        recent_reqs = get_recent_requests()
        if recent_reqs:
            log_lifecycle_event("RECENT_REQUESTS", f"Last {len(recent_reqs)} requests before PAGE_CLOSE: {recent_reqs}")

        if not closed_by_code:
            print("closed externally: no close call from the bot")

    def on_context_close():
        anchor_alive = False
        if anchor_page is not None:
            try:
                if hasattr(anchor_page, "is_closed"):
                    anchor_alive = not (anchor_page.is_closed() is True)
            except Exception:
                anchor_alive = False
        closed_by_code = was_code_close_called(context) or any(
            c.get("target_type") in ("context", "browser") for c in _CODE_CLOSE_CALLS
        )
        log_lifecycle_event(
            "CONTEXT_CLOSE",
            f"BrowserContext closed (anchor_present={anchor_page is not None}, "
            f"anchor_alive={anchor_alive}, "
            f"closed_by_code={'true' if closed_by_code else 'false'})"
        )
        if not closed_by_code:
            print("closed externally: no close call from the bot")

    def on_browser_disconnect():
        log_lifecycle_event("BROWSER_DISCONNECT", "Browser disconnected")

    def attach_page_listeners(p):
        try:
            if not hasattr(p, "_initial_url"):
                setattr(p, "_initial_url", getattr(p, "url", ""))
            if not hasattr(p, "_crashed"):
                setattr(p, "_crashed", False)
            p.on("close", lambda p=p: on_page_close(p))
            p.on("crash", lambda p=p: on_page_crash(p))
            p.on("popup", lambda popup: on_page_popup(popup))
            p.on("dialog", on_page_dialog)
            p.on("framenavigated", on_frame_navigated)
            p.on("request", on_request)
        except Exception:
            pass

    def on_page_created(p):
        log_lifecycle_event("PAGE_CREATED", f"New page created (url='{getattr(p, 'url', '')}')")
        attach_page_listeners(p)

    try:
        context.on("page", on_page_created)
        context.on("close", on_context_close)
        context.on("download", on_download_created)
        if hasattr(context, "browser") and context.browser:
            context.browser.on("disconnected", on_browser_disconnect)
        for p in getattr(context, "pages", []):
            attach_page_listeners(p)
    except Exception:
        pass

def create_keep_alive_tab(context: BrowserContext) -> Page:
    """
    Creates a permanent blank anchor tab (about:blank) that is never navigated
    and never closed until the run ends, preventing context shutdown when all
    job tabs are closed during navigation or discard transitions.
    """
    page = context.new_page()
    setattr(page, "_is_keep_alive", True)
    log_lifecycle_event("KEEP_ALIVE_CREATED", "Anchor tab created to prevent context exit")
    return page

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
            record_code_close_call(page, caller="cleanup_startup_tabs")
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
    Leaves the keep-alive anchor tab untouched.
    """
    for page in list(context.pages):
        if getattr(page, "_is_keep_alive", False) is True:
            continue
        url = page.url.strip()
        is_blank = (not url) or (url in ("about:blank", "chrome://newtab/", "edge://newtab/"))
        if not is_blank:
            try:
                record_code_close_call(page, caller="ensure_clean_tabs")
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
        self.keep_alive_page: Optional[Page] = None

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
        self.keep_alive_page = create_keep_alive_tab(self.context)
        attach_lifecycle_listeners(self.context, anchor_page=self.keep_alive_page)
        log_lifecycle_event("BROWSER_START", f"Browser launched (headless={self.headless})")
        return self.context

    def close(self) -> None:
        log_lifecycle_event("BROWSER_CLOSE_REQUESTED", "BrowserManager.close called")
        if self.context:
            record_code_close_call(self.context, caller="BrowserManager.close")
            try:
                for p in getattr(self.context, "pages", []):
                    try:
                        record_code_close_call(p, caller="BrowserManager.close")
                    except Exception:
                        pass
            except Exception:
                pass
        if self.keep_alive_page:
            try:
                record_code_close_call(self.keep_alive_page, caller="BrowserManager.close")
                self.keep_alive_page.close()
            except Exception:
                pass
            self.keep_alive_page = None
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
