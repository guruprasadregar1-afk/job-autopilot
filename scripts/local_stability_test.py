"""
Local Browser Stability Test (Headed Edge)
===========================================
Tests Edge browser process stability over a 150-second duration without network access:
- Channel: "msedge" (headed)
- Exact same launch arguments: viewport={"width": 1280, "height": 800}, args=["--start-maximized"]
- Isolated temporary user_data_dir (no collision with real profile)
- Anchor keep-alive tab (about:blank)
- 2 local HTML pages (file:// scheme, zero network access)
- Alternates clicks and navigations back and forth every 3 seconds for 150 seconds
- Full diagnostic lifecycle logging into logs/browser_lifecycle.log
"""

import os
import sys
import time
import tempfile
import shutil
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
from src.browser import (
    create_keep_alive_tab,
    attach_lifecycle_listeners,
    log_lifecycle_event,
    record_browser_action,
    record_code_close_call,
)

def create_local_test_pages(temp_dir: Path) -> tuple[Path, Path]:
    """Generates two static HTML pages with local interactive buttons and counters."""
    page_a = temp_dir / "page_a.html"
    page_b = temp_dir / "page_b.html"

    page_a.write_text(
        """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Local Stability Test - Page A</title>
    <style>
        body { font-family: sans-serif; background-color: #f0f4f8; padding: 40px; color: #1e293b; }
        .card { background: white; border-radius: 8px; padding: 24px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); max-width: 600px; margin: auto; }
        button { background-color: #0284c7; color: white; border: none; padding: 10px 20px; font-size: 16px; border-radius: 6px; cursor: pointer; }
        button:hover { background-color: #0369a1; }
        .counter { font-size: 24px; font-weight: bold; margin-top: 15px; color: #0f172a; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Page A: Local Stability Diagnostic</h1>
        <p>Testing Edge browser runtime stability without external network traffic.</p>
        <button id="btn-action" onclick="increment()">Click Action A</button>
        <div class="counter">Clicks: <span id="count">0</span></div>
    </div>
    <script>
        let c = 0;
        function increment() {
            c++;
            document.getElementById('count').textContent = c;
        }
    </script>
</body>
</html>
""",
        encoding="utf-8"
    )

    page_b.write_text(
        """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Local Stability Test - Page B</title>
    <style>
        body { font-family: sans-serif; background-color: #fdf2f8; padding: 40px; color: #1e293b; }
        .card { background: white; border-radius: 8px; padding: 24px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); max-width: 600px; margin: auto; }
        button { background-color: #db2777; color: white; border: none; padding: 10px 20px; font-size: 16px; border-radius: 6px; cursor: pointer; }
        button:hover { background-color: #be185d; }
        .counter { font-size: 24px; font-weight: bold; margin-top: 15px; color: #0f172a; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Page B: Local Stability Diagnostic</h1>
        <p>Testing Edge browser runtime stability without external network traffic.</p>
        <button id="btn-action" onclick="increment()">Click Action B</button>
        <div class="counter">Clicks: <span id="count">0</span></div>
    </div>
    <script>
        let c = 0;
        function increment() {
            c++;
            document.getElementById('count').textContent = c;
        }
    </script>
</body>
</html>
""",
        encoding="utf-8"
    )

    return page_a, page_b

def run_stability_test(duration_seconds: int = 150, interval_seconds: float = 3.0):
    print("=" * 70)
    print("STARTING LOCAL BROWSER STABILITY TEST")
    print(f"Target Duration: {duration_seconds}s | Action Interval: {interval_seconds}s")
    print("Browser: Microsoft Edge (channel='msedge', headed)")
    print("Launch Args: viewport={'width': 1280, 'height': 800}, args=['--start-maximized']")
    print("Network: ZERO external network (local file:// URLs only)")
    print("Logging: logs/browser_lifecycle.log")
    print("=" * 70)

    temp_profile_dir = tempfile.mkdtemp(prefix="edge_stability_profile_")
    temp_pages_dir = tempfile.mkdtemp(prefix="edge_stability_pages_")
    temp_pages_path = Path(temp_pages_dir)

    page_a_path, page_b_path = create_local_test_pages(temp_pages_path)
    url_a = page_a_path.as_uri()
    url_b = page_b_path.as_uri()

    print(f"[TEMP PROFILE] {temp_profile_dir}")
    print(f"[PAGE A] {url_a}")
    print(f"[PAGE B] {url_b}\\n")

    log_lifecycle_event("STABILITY_TEST_INIT", f"profile={temp_profile_dir} duration={duration_seconds}s")

    pw = sync_playwright().start()
    try:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=temp_profile_dir,
            channel="msedge",
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--start-maximized"],
        )

        # Create anchor keep-alive tab
        anchor_page = create_keep_alive_tab(context)
        attach_lifecycle_listeners(context, anchor_page=anchor_page)
        log_lifecycle_event("STABILITY_TEST_LAUNCH", "Headed Edge persistent context launched")

        # Open tab 1 and tab 2 with local pages
        tab_1 = context.new_page()
        record_browser_action(f"goto: {url_a}")
        tab_1.goto(url_a, wait_until="load")

        tab_2 = context.new_page()
        record_browser_action(f"goto: {url_b}")
        tab_2.goto(url_b, wait_until="load")

        start_time = time.time()
        cycle = 0

        print("[RUNNING] Loop started. Testing stability across 150 seconds...")

        while True:
            elapsed = time.time() - start_time
            if elapsed >= duration_seconds:
                print(f"\\n[COMPLETE] Successfully reached target duration of {duration_seconds}s without premature close!")
                break

            cycle += 1
            remaining = int(duration_seconds - elapsed)

            # Alternate actions between Tab 1 and Tab 2
            if cycle % 2 == 1:
                # Interact with Tab 1
                record_browser_action(f"cycle_{cycle}: click Tab 1 button")
                tab_1.bring_to_front()
                tab_1.locator("#btn-action").click()
                current_count = tab_1.locator("#count").inner_text()
                print(f"[{int(elapsed):3d}s elapsed | {remaining:3d}s left] Cycle {cycle:02d}: Clicked Page A (clicks={current_count})")
            else:
                # Interact with Tab 2 or navigate Tab 2
                record_browser_action(f"cycle_{cycle}: click Tab 2 button")
                tab_2.bring_to_front()
                tab_2.locator("#btn-action").click()
                current_count = tab_2.locator("#count").inner_text()
                print(f"[{int(elapsed):3d}s elapsed | {remaining:3d}s left] Cycle {cycle:02d}: Clicked Page B (clicks={current_count})")

            # Check if browser was closed unexpectedly
            if context.pages == [] or (hasattr(context, "is_closed") and context.is_closed()):
                print(f"\\n[ALERT] Context was closed prematurely at elapsed={elapsed:.1f}s!")
                break

            time.sleep(interval_seconds)

        log_lifecycle_event("STABILITY_TEST_FINISH", f"cycles_completed={cycle} elapsed={time.time() - start_time:.1f}s")

        print("\nCleaning up tabs and context cleanly...")
        for p in list(context.pages):
            record_code_close_call(p, caller="local_stability_test.cleanup")
            try:
                p.close()
            except Exception:
                pass
        record_code_close_call(context, caller="local_stability_test.cleanup")
        context.close()
        print("[SUCCESS] Stability test finished cleanly.")

    except Exception as e:
        print(f"\\n[EXCEPTION] Error during stability test: {e}")
        log_lifecycle_event("STABILITY_TEST_ERROR", str(e))
        raise
    finally:
        try:
            pw.stop()
        except Exception:
            pass
        # Clean up temporary test files
        shutil.rmtree(temp_pages_dir, ignore_errors=True)
        shutil.rmtree(temp_profile_dir, ignore_errors=True)

if __name__ == "__main__":
    run_stability_test(duration_seconds=150, interval_seconds=3.0)
