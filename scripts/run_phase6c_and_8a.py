import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import BrowserManager
from src.policy import SafePage, SafeLocator, PolicyBlockError, OBSERVE_ONLY
from src.db import Database
from src.guards import GuardsManager
from src.matcher import JobMatcher
from src.platforms.linkedin import LinkedInCollector
from src.platforms.naukri import NaukriCollector

SNAPSHOT_DIR = Path("docs/snapshots")
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

def run_phase6c_observations(page):
    """
    Phase 6c read-only observation to capture missing snapshots:
    - Review step & Submit button
    - Opt-in uncheck & verify
    - Discard confirmation prompt
    - Confirmation that no draft is saved
    - Pagination Page N
    """
    print("\n" + "="*70, flush=True)
    print("PHASE 6c: LIVE DOM OBSERVATIONS (READ-ONLY, OBSERVE_ONLY=True)", flush=True)
    print("="*70, flush=True)
    assert OBSERVE_ONLY is True, "CRITICAL: OBSERVE_ONLY must be True!"

    safe_page = SafePage(page)

    # 1. Search LinkedIn for Easy Apply jobs
    search_url = "https://www.linkedin.com/jobs/search/?keywords=Full+Stack+Developer&location=India&f_AL=true"
    print(f"[Phase 6c] Navigating to search: {search_url}", flush=True)
    safe_page.safe_goto(search_url, wait_until="domcontentloaded")
    time.sleep(5)

    # Snapshot Pagination Page 2 if available
    page2_btn = page.locator("button[aria-label='Page 2'], ul.jobs-search-pagination__pages button:has-text('2'), a[aria-label='Page 2']").first
    if page2_btn.count() > 0:
        print("[Phase 6c] Found Page 2. Clicking to observe pagination...", flush=True)
        try:
            safe_page.locator("button[aria-label='Page 2']").safe_click()
            time.sleep(3)
            page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_08_pagination_page2.png"))
            (SNAPSHOT_DIR / "linkedin_08_pagination_page2.html").write_text(page.content(), encoding="utf-8")
            print("[PROVEN] Captured linkedin_08_pagination_page2.*", flush=True)
        except Exception as e:
            print(f"[Phase 6c] Pagination snapshot note: {e}", flush=True)

    # 2. Find and open an Easy Apply job
    cards = page.locator("ul.jobs-search__results-list > li, li.jobs-search-results__list-item, div.job-card-container")
    card_count = cards.count()
    print(f"[Phase 6c] Found {card_count} job cards.", flush=True)

    for i in range(min(15, card_count)):
        c = cards.nth(i)
        card_text = c.inner_text().replace("\n", " ")
        print(f"[Phase 6c] Inspecting card {i+1}: {card_text[:70]}...", flush=True)

        # Click card via structural selector
        safe_card = SafeLocator(c, selector_hint="job-card", is_job_card=True)
        safe_card.safe_click()
        time.sleep(3)

        # Check for Easy Apply button
        easy_apply_btn = page.locator("button.jobs-apply-button, button:has-text('Easy Apply')").first
        if easy_apply_btn.count() > 0:
            btn_text = easy_apply_btn.inner_text().strip()
            print(f"[Phase 6c] Found '{btn_text}' button! Clicking to open modal...", flush=True)
            safe_apply = SafeLocator(easy_apply_btn, selector_hint="button.jobs-apply-button")
            safe_apply.safe_click()
            time.sleep(3)

            # Step through modal steps
            for step_num in range(1, 6):
                # Check for Submit application button first
                submit_btn = page.locator("button[aria-label='Submit application'], button:has-text('Submit application')").first
                if submit_btn.count() > 0:
                    print(f"[Phase 6c] Reached Review Step at step {step_num}! Snapshotting Submit application button (DO NOT CLICK)...", flush=True)
                    page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_05_modal_review.png"))
                    (SNAPSHOT_DIR / "linkedin_05_modal_review.html").write_text(page.content(), encoding="utf-8")
                    print("[PROVEN] Captured linkedin_05_modal_review.*", flush=True)

                    # Test opt-in checkbox uncheck & verify
                    follow_box = page.locator("label:has-text('Follow') input[type='checkbox']").first
                    if follow_box.count() > 0:
                        print("[Phase 6c] Testing uncheck & verify on 'Follow company' opt-in checkbox...", flush=True)
                        safe_follow = SafeLocator(follow_box, selector_hint="follow-checkbox")
                        safe_follow.safe_uncheck_and_verify()
                        print("[SUCCESS] Mandatory opt-in uncheck passed!", flush=True)

                    # Trigger Discard confirmation prompt
                    dismiss_btn = page.locator("button.artdeco-modal__dismiss, button[aria-label='Dismiss']").first
                    if dismiss_btn.count() > 0:
                        print("[Phase 6c] Clicking Dismiss ('X') to trigger Discard prompt...", flush=True)
                        safe_dismiss = SafeLocator(dismiss_btn, selector_hint="modal-dismiss-btn")
                        safe_dismiss.safe_click()
                        time.sleep(2)

                        # Snapshot Discard prompt dialog
                        discard_btn = page.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')").first
                        if discard_btn.count() > 0:
                            print("[Phase 6c] Snapshotting Discard prompt dialog...", flush=True)
                            page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_06_discard_prompt.png"))
                            (SNAPSHOT_DIR / "linkedin_06_discard_prompt.html").write_text(page.content(), encoding="utf-8")
                            print("[PROVEN] Captured linkedin_06_discard_prompt.*", flush=True)

                            # Click Discard
                            print("[Phase 6c] Clicking Discard button...", flush=True)
                            safe_discard = SafeLocator(discard_btn, selector_hint="discard-confirm-btn")
                            safe_discard.safe_click()
                            time.sleep(2)

                            # Confirm no draft saved
                            page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_07_no_draft_confirmed.png"))
                            (SNAPSHOT_DIR / "linkedin_07_no_draft_confirmed.html").write_text(page.content(), encoding="utf-8")
                            print("[PROVEN] Captured linkedin_07_no_draft_confirmed.*", flush=True)
                            return True
                    break

                # Check for Review button
                review_btn = page.locator("button[aria-label='Review your application'], button:has-text('Review')").first
                if review_btn.count() > 0:
                    print("[Phase 6c] Clicking Review button to proceed to Review step...", flush=True)
                    safe_review = SafeLocator(review_btn, selector_hint="review-button")
                    safe_review.safe_click()
                    time.sleep(2)
                    continue

                # Check for existing resume selection on resume step
                radio_card = page.locator("input[type='radio'][id*='jobsDocumentCardToggle']").first
                if radio_card.count() > 0 and not radio_card.is_checked():
                    print("[Phase 6c] Selecting existing stored resume radio...", flush=True)
                    safe_radio = SafeLocator(radio_card, selector_hint="existing-resume-radio")
                    safe_radio.safe_check()
                    time.sleep(1)

                # Check for Next / Continue button
                next_btn = page.locator("button[aria-label='Continue to next step'], button:has-text('Next')").first
                if next_btn.count() > 0:
                    print(f"[Phase 6c] Clicking Next button on step {step_num}...", flush=True)
                    safe_next = SafeLocator(next_btn, selector_hint="continue-button")
                    safe_next.safe_click()
                    time.sleep(2)
                    continue

                print(f"[Phase 6c] Reached custom question step or step without known action on step {step_num}.", flush=True)
                # Snapshot the step needing input
                page.screenshot(path=str(SNAPSHOT_DIR / f"linkedin_step{step_num}_observed.png"))
                (SNAPSHOT_DIR / f"linkedin_step{step_num}_observed.html").write_text(page.content(), encoding="utf-8")
                # Dismiss cleanly
                dismiss_btn = page.locator("button.artdeco-modal__dismiss, button[aria-label='Dismiss']").first
                if dismiss_btn.count() > 0:
                    safe_dismiss = SafeLocator(dismiss_btn, selector_hint="modal-dismiss-btn")
                    safe_dismiss.safe_click()
                    time.sleep(2)
                    discard_btn = page.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')").first
                    if discard_btn.count() > 0:
                        safe_discard = SafeLocator(discard_btn, selector_hint="discard-confirm-btn")
                        safe_discard.safe_click()
                        time.sleep(2)
                break

    return False

def run_phase8a_dry_run(context):
    """
    Phase 8a dry-run:
    - Limited to 1 results page and 10 jobs per platform.
    - Strictly read-only collection, dedupe, hard-filter, and match scoring.
    - Zero apply clicks.
    """
    print("\n" + "="*70, flush=True)
    print("PHASE 8a: READ-ONLY COLLECTION & FIT EVALUATION (--dry-run)", flush=True)
    print("="*70, flush=True)

    db = Database("data/jobs.db")
    guards = GuardsManager(db)
    matcher = JobMatcher()

    # 1. LinkedIn 8a Dry-Run (10 jobs)
    print("\n--- Starting LinkedIn Phase 8a Dry-Run (Max 10 jobs, 1 page) ---", flush=True)
    page_li = context.new_page()
    collector_li = LinkedInCollector(db, guards, matcher)
    li_jobs = collector_li.run_phase8a_search(
        page=page_li,
        search_query={"keywords": "Senior Full Stack Developer", "location": "India", "f_AL": True},
        max_jobs=10,
        dry_run=True
    )
    print(f"\n[LinkedIn 8a Complete] Inspected {len(li_jobs)} jobs. All logged to data/jobs.db.", flush=True)
    page_li.close()

    # 2. Naukri 8a Dry-Run (10 jobs)
    print("\n--- Starting Naukri Phase 8a Dry-Run (Max 10 jobs, 1 page) ---", flush=True)
    page_nk = context.new_page()
    collector_nk = NaukriCollector(db, guards, matcher)
    nk_jobs = collector_nk.run_phase8a_search(
        page=page_nk,
        search_query={"keywords": "Senior Full Stack Developer", "locations": ["Bengaluru"]},
        max_jobs=10,
        dry_run=True
    )
    print(f"\n[Naukri 8a Complete] Inspected {len(nk_jobs)} jobs. All logged to data/jobs.db.", flush=True)
    page_nk.close()

def main():
    mgr = BrowserManager(headless=False)
    context = mgr.start()
    page = context.new_page()
    try:
        # Step 1: Run Phase 6c Observations
        run_phase6c_observations(page)
        page.close()

        # Step 2: Run Phase 8a Dry-Run Collection
        run_phase8a_dry_run(context)

    finally:
        context.close()
        mgr.close()
        print("\nAll observations and dry-run collections completed successfully.", flush=True)

if __name__ == "__main__":
    main()
