import pytest
from pathlib import Path
from unittest.mock import MagicMock
from playwright.sync_api import sync_playwright
from src.platforms.linkedin import LinkedInCollector
from src.db import Database

SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "snapshots"

EXCLUSIONS = ":not(#searchFilter_applyWithLinkedin):not([role='radio']):not([role='link']):not([aria-label*='company website'])"
STANDALONE_SELECTOR = (
    f"[data-sdui-screen*='JobDetails'] button[aria-label^='Easy Apply to']{EXCLUSIONS}, "
    f"main button[aria-label^='Easy Apply to']{EXCLUSIONS}"
)
SEARCH_SPLIT_SELECTOR = (
    f"div.jobs-search__job-details button[aria-label^='Easy Apply to']{EXCLUSIONS}"
)


def test_standalone_sdui_locator_matches_saved_standalone_snapshots():
    """
    Layout (a): Standalone SDUI view locator matches saved standalone /jobs/view/ snapshots.
    """
    standalone_files = [
        "rehearsal_4476699604_modal_not_detected.html",
        "rehearsal_4477293332_modal_not_detected.html"
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for fn in standalone_files:
            file_path = SNAPSHOTS_DIR / fn
            assert file_path.exists(), f"Snapshot {fn} missing"
            page.goto(file_path.as_uri(), wait_until="domcontentloaded")

            loc = page.locator(STANDALONE_SELECTOR)
            assert loc.count() >= 1, f"Expected standalone locator to match in {fn}"
            label = loc.first.get_attribute("aria-label") or ""
            assert label.startswith("Easy Apply to"), f"Expected 'Easy Apply to', got '{label}' in {fn}"
        browser.close()


def test_search_split_view_locator_matches_saved_search_snapshots():
    """
    Layout (b): Search split view locator matches saved split view snapshots.
    """
    split_files = [
        "linkedin_02_job_detail.html",
        "linkedin_01_search_results.html"
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for fn in split_files:
            file_path = SNAPSHOTS_DIR / fn
            assert file_path.exists(), f"Snapshot {fn} missing"
            page.goto(file_path.as_uri(), wait_until="domcontentloaded")

            loc = page.locator(SEARCH_SPLIT_SELECTOR)
            assert loc.count() >= 1, f"Expected search split locator to match in {fn}"
            label = loc.first.get_attribute("aria-label") or ""
            assert label.startswith("Easy Apply to"), f"Expected 'Easy Apply to', got '{label}' in {fn}"
        browser.close()


def test_filter_pill_and_external_apply_never_match_either_locator():
    """
    Verifies that the Easy Apply filter pill (#searchFilter_applyWithLinkedin)
    and external-apply button (Jobgether company website button) never match either locator.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Search results snapshot containing the filter pill
        search_file = SNAPSHOTS_DIR / "linkedin_01_search_results.html"
        page.goto(search_file.as_uri(), wait_until="domcontentloaded")
        pill_loc = page.locator("#searchFilter_applyWithLinkedin")
        assert pill_loc.count() == 1
        # Pill must NOT match standalone or search split locators
        assert page.locator(f"#searchFilter_applyWithLinkedin{EXCLUSIONS}").count() == 0

        # 2. External apply snapshot (Jobgether 4479309031)
        ext_file = SNAPSHOTS_DIR / "rehearsal_4479309031_modal_not_detected.html"
        page.goto(ext_file.as_uri(), wait_until="domcontentloaded")
        assert page.locator(STANDALONE_SELECTOR).count() == 0
        assert page.locator(SEARCH_SPLIT_SELECTOR).count() == 0

        browser.close()


def test_collector_locate_easy_apply_button_method():
    """
    Verifies that LinkedInCollector.locate_easy_apply_button returns the button
    and the correct layout tag.
    """
    collector = LinkedInCollector(db=MagicMock(), guards=MagicMock(), matcher=MagicMock())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Standalone layout
        page.goto((SNAPSHOTS_DIR / "rehearsal_4476699604_modal_not_detected.html").as_uri(), wait_until="domcontentloaded")
        btn, layout = collector.locate_easy_apply_button(page)
        assert btn is not None
        assert layout == "standalone_sdui"

        # Search split layout
        page.goto((SNAPSHOTS_DIR / "linkedin_02_job_detail.html").as_uri(), wait_until="domcontentloaded")
        btn2, layout2 = collector.locate_easy_apply_button(page)
        assert btn2 is not None
        assert layout2 in ("standalone_sdui", "search_split_view")

        # External apply
        page.goto((SNAPSHOTS_DIR / "rehearsal_4479309031_modal_not_detected.html").as_uri(), wait_until="domcontentloaded")
        btn3, layout3 = collector.locate_easy_apply_button(page)
        assert btn3 is None
        assert layout3 == ""

        browser.close()


def test_detect_closed_or_applied_jobs():
    """
    Verifies detection of 'No longer accepting applications', 'Applied' / 'Applied X ago',
    and 'This job is no longer available' text in job details root.
    """
    collector = LinkedInCollector(db=MagicMock(), guards=MagicMock(), matcher=MagicMock())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Real applied snapshot
        applied_file = SNAPSHOTS_DIR / "rehearsal_4478456211_modal_not_detected.html"
        page.goto(applied_file.as_uri(), wait_until="domcontentloaded")
        reason = collector.detect_closed_or_applied(page)
        assert reason in ("ALREADY_APPLIED", "ALREADY_APPLIED_OR_NA")

        # 2. Open job snapshot (should return "")
        open_file = SNAPSHOTS_DIR / "rehearsal_4476699604_modal_not_detected.html"
        page.goto(open_file.as_uri(), wait_until="domcontentloaded")
        assert collector.detect_closed_or_applied(page) == ""

        # 3. Synthetic closed: No longer accepting applications
        page2 = browser.new_page()
        page2.set_content("<main><div class='jobs-search__job-details'><h1>Role</h1><p>No longer accepting applications</p></div></main>")
        assert collector.detect_closed_or_applied(page2) == "NO_LONGER_ACCEPTING_APPLICATIONS"

        # 4. Synthetic closed: This job is no longer available
        page2.set_content("<main><div class='jobs-search__job-details'><h1>Role</h1><p>This job is no longer available</p></div></main>")
        assert collector.detect_closed_or_applied(page2) == "JOB_NO_LONGER_AVAILABLE"

        # 5. Synthetic applied: Applied pill
        page2.set_content("<main><div class='jobs-search__job-details'><div class='jobs-s-apply'><span class='artdeco-inline-feedback__message'>Applied</span></div></div></main>")
        assert collector.detect_closed_or_applied(page2) in ("ALREADY_APPLIED", "ALREADY_APPLIED_OR_NA")

        browser.close()


def test_get_job_details_button_labels():
    """
    Verifies that get_job_details_button_labels returns aria-label/text of all buttons in root.
    """
    collector = LinkedInCollector(db=MagicMock(), guards=MagicMock(), matcher=MagicMock())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto((SNAPSHOTS_DIR / "rehearsal_4476699604_modal_not_detected.html").as_uri(), wait_until="domcontentloaded")
        labels = collector.get_job_details_button_labels(page)
        assert len(labels) > 0
        assert any("Easy Apply" in lbl for lbl in labels)
        browser.close()


def test_apply_button_not_found_counts_towards_two_strike_block(tmp_path):
    """
    Item 5: Verifies that APPLY_BUTTON_NOT_FOUND increments failure_count
    and blocks the job after 2 strikes, exactly like MODAL_NOT_DETECTED.
    """
    db = Database(tmp_path / "test_retry_rules.db")

    # Initial state: eligible
    assert db.is_job_eligible("linkedin", "job-100") is True

    # Strike 1: APPLY_BUTTON_NOT_FOUND
    db.record_job(
        platform="linkedin",
        job_id="job-100",
        title="Test Job",
        company="Test Co",
        location="Remote",
        status="APPLY_BUTTON_NOT_FOUND",
        failure_reason="Easy Apply button not visible"
    )
    assert db.get_failure_count("linkedin", "job-100") == 1
    # After 1 strike, still eligible for retry
    assert db.is_job_eligible("linkedin", "job-100") is True

    eligible_jobs = db.get_eligible_found_jobs("linkedin", limit=10)
    assert any(j["job_id"] == "job-100" for j in eligible_jobs)

    # Strike 2: APPLY_BUTTON_NOT_FOUND
    db.update_job_status(
        platform="linkedin",
        job_id="job-100",
        status="APPLY_BUTTON_NOT_FOUND",
        failure_reason="Easy Apply button not visible"
    )
    assert db.get_failure_count("linkedin", "job-100") == 2
    # After 2 strikes, job is BLOCKED (2-strike rule)
    assert db.is_job_eligible("linkedin", "job-100") is False
    assert db.is_job_blocked("linkedin", "job-100") is True

    eligible_jobs_after = db.get_eligible_found_jobs("linkedin", limit=10)
    assert not any(j["job_id"] == "job-100" for j in eligible_jobs_after)


def test_closed_or_applied_job_is_skipped_and_marked_final(tmp_path):
    """
    Item 3: Verifies that closed or applied jobs are recorded as SKIPPED,
    which is an immediate final blocking outcome.
    """
    db = Database(tmp_path / "test_skipped.db")

    db.record_job(
        platform="linkedin",
        job_id="job-200",
        title="Closed Job",
        company="Old Co",
        location="Remote",
        status="SKIPPED",
        failure_reason="NO_LONGER_ACCEPTING_APPLICATIONS"
    )
    # SKIPPED is final, immediately blocks from retry
    assert db.is_job_eligible("linkedin", "job-200") is False
    assert db.is_job_blocked("linkedin", "job-200") is True
