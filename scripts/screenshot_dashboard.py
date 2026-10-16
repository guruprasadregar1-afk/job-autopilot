import os
import sys
import sqlite3
import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
from src.db import Database
from src.dashboard import generate_dashboard

def create_sample_test_dashboard_screenshot():
    test_db_path = Path("data/test_dashboard_sample.db")
    if test_db_path.exists():
        test_db_path.unlink()

    db = Database(test_db_path)

    # Seed sample jobs
    now = datetime.datetime.now().isoformat()
    db.record_job(
        platform="linkedin",
        job_id="test-li-001",
        title="Senior Full Stack Engineer",
        company="Stripe",
        location="Bengaluru, Karnataka, India",
        url="https://www.linkedin.com/jobs/view/test-li-001/",
        match_score=92,
        match_reason="Strong fit for React, Node, and TypeScript",
        status="APPLIED"
    )
    db.record_job(
        platform="linkedin",
        job_id="test-li-002",
        title="Lead React Developer",
        company="Razorpay",
        location="Bengaluru, Karnataka, India",
        url="https://www.linkedin.com/jobs/view/test-li-002/",
        match_score=88,
        match_reason="Excellent match on MERN architecture",
        status="UNVERIFIED",
        failure_reason="Confirmation not detected on page after submit"
    )
    db.record_job(
        platform="linkedin",
        job_id="test-li-003",
        title="Full Stack Developer",
        company="Swiggy",
        location="Bengaluru, Karnataka, India",
        url="https://www.linkedin.com/jobs/view/test-li-003/",
        match_score=75,
        match_reason="Good match on Node and PostgreSQL",
        status="NEEDS_INPUT",
        pending_question="Please enter your LinkedIn profile URL"
    )
    db.record_job(
        platform="naukri",
        job_id="test-nk-001",
        title="Senior Frontend Engineer",
        company="Flipkart",
        location="Bengaluru",
        url="https://www.naukri.com/job-listings-test-nk-001",
        match_score=85,
        match_reason="Strong React and Next.js match",
        status="EXTERNAL_SITE",
        failure_reason="External company careers portal"
    )
    db.record_job(
        platform="naukri",
        job_id="test-nk-002",
        title="Full Stack Engineer",
        company="Zomato",
        location="Gurugram",
        url="https://www.naukri.com/job-listings-test-nk-002",
        match_score=45,
        match_reason="Job requires 8+ years experience and Java",
        status="SKIPPED",
        failure_reason="Low match score: 45 < 65"
    )

    # Record sample events
    db.record_event("linkedin", "test-li-001", "FOUND", note="Identified from LinkedIn search")
    db.record_event("linkedin", "test-li-001", "APPLIED", old_status="FOUND", new_status="APPLIED", note="Successfully submitted Easy Apply")
    db.record_event("linkedin", "test-li-002", "UNVERIFIED", old_status="FOUND", new_status="UNVERIFIED", note="Submit clicked but no confirmation modal appeared")
    db.record_event("linkedin", "test-li-003", "NEEDS_INPUT", old_status="FOUND", new_status="NEEDS_INPUT", note="Encountered question: LinkedIn profile URL")

    # Generate dashboard HTML
    out_html = Path("data/test_dashboard.html")
    generate_dashboard(db_path=test_db_path, output_path=out_html)
    print(f"Test dashboard generated at: {out_html.resolve()}")

    # Render and screenshot using Playwright
    screenshot_path = Path("docs/snapshots/dashboard_preview.png")
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"file:///{out_html.resolve().as_posix()}", wait_until="load")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()

    print(f"Dashboard screenshot captured at: {screenshot_path.resolve()} ({screenshot_path.stat().st_size} bytes)")

    # Clean up test database & test html
    if test_db_path.exists():
        test_db_path.unlink()
    if out_html.exists():
        out_html.unlink()
    print("Cleaned up temporary test database.")

if __name__ == "__main__":
    create_sample_test_dashboard_screenshot()
