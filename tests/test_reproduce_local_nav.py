import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright

def test_local_dialog_discard_and_second_navigation(tmp_path):
    """
    Reproduces navigation after dialog discard strictly with local HTML files.
    No network requests, no LinkedIn URLs.
    """
    page1_html = tmp_path / "page1.html"
    page1_html.write_text("""<!DOCTYPE html>
<html>
<head><title>Job 1</title></head>
<body>
    <h1>Job 1 Detail</h1>
    <button id="open-btn" onclick="document.getElementById('modal').showModal()">Easy Apply</button>
    <dialog id="modal">
        <h2>Apply Modal</h2>
        <button id="dismiss-btn" onclick="document.getElementById('modal').close()">Discard</button>
    </dialog>
</body>
</html>""", encoding="utf-8")

    page2_html = tmp_path / "page2.html"
    page2_html.write_text("""<!DOCTYPE html>
<html>
<head><title>Job 2</title></head>
<body>
    <h1>Job 2 Detail</h1>
</body>
</html>""", encoding="utf-8")

    page1_url = page1_html.as_uri()
    page2_url = page2_html.as_uri()

    profile_dir = tmp_path / "test_browser_profile"

    with sync_playwright() as p:
        # Launch persistent context headless
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Step 1: Navigate to Job 1 local page
        page.goto(page1_url)
        assert "Job 1" in page.title()

        # Step 2: Open modal dialog
        page.locator("#open-btn").click()
        assert page.locator("#modal").is_visible()

        # Step 3: Discard modal dialog
        page.locator("#dismiss-btn").click()
        assert not page.locator("#modal").is_visible()

        # Step 4: Verify page is alive
        assert not page.is_closed()

        # Step 5: Navigate to Job 2 local page
        page.goto(page2_url)
        assert "Job 2" in page.title()

        context.close()
