import time
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import BrowserManager
from src.policy import SafePage, SafeLocator, PolicyBlockError, OBSERVE_ONLY
import yaml

SNAPSHOT_DIR = Path("docs/snapshots")
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

def observe_review_step():
    print("\n" + "="*60)
    print("PHASE 6c: TARGETING REVIEW STEP (OBSERVE_ONLY = True)")
    print("="*60)
    assert OBSERVE_ONLY is True

    profile = yaml.safe_load(open(Path("config/profile.yaml"), encoding="utf-8"))
    mgr = BrowserManager(headless=False)
    context = mgr.start()
    page = context.new_page()
    safe_page = SafePage(page)

    try:
        search_url = "https://www.linkedin.com/jobs/search/?keywords=Senior+Full+Stack+Developer&location=India&f_AL=true"
        print(f"[Phase 6c] Navigating to: {search_url}")
        safe_page.safe_goto(search_url, wait_until="domcontentloaded")
        time.sleep(4)

        cards = page.locator("div.job-card-container, li.jobs-search-results__list-item")
        print(f"[Phase 6c] Checking {cards.count()} cards for a 2-step Easy Apply job...")

        for i in range(1, min(10, cards.count())):
            c = cards.nth(i)
            c.scroll_into_view_if_needed()
            safe_card = SafeLocator(c, selector_hint="job-card", is_job_card=True)
            safe_card.safe_click()
            time.sleep(2)

            details_pane = page.locator("div.jobs-search__job-details, div.job-view-layout, div.jobs-details").first
            easy_apply_btn = details_pane.locator("button.jobs-apply-button, button[aria-label*='Easy Apply']").first
            if easy_apply_btn.count() == 0:
                continue

            btn_label = (easy_apply_btn.get_attribute("aria-label") or easy_apply_btn.inner_text()).lower()
            if "easy apply" not in btn_label:
                continue

            print(f"[Phase 6c] Testing card {i+1}: '{btn_label.strip()}'")
            safe_apply = SafeLocator(easy_apply_btn, selector_hint="button.jobs-apply-button")
            safe_apply.safe_click()
            time.sleep(3)

            modal = page.locator("div.jobs-easy-apply-modal, div[role='dialog']:has(button[aria-label='Dismiss'])").first
            if modal.count() == 0 or not modal.is_visible():
                continue

            # Check Step 1
            email_select = modal.locator("select[id*='multipleChoice']").first
            if email_select.count() > 0 and email_select.is_visible():
                email = profile.get("personal", {}).get("email")
                safe_select = SafeLocator(email_select, selector_hint="email-select", is_form_field=True)
                safe_select.safe_select_option(value=email)
                time.sleep(1)

            # Check next or review
            reached_review = False
            for step in range(1, 5):
                submit_btn = modal.locator("button[aria-label='Submit application'], button:has-text('Submit application')").first
                if submit_btn.count() > 0 and submit_btn.is_visible():
                    print("[Phase 6c] SUCCESS: Reached Review step with Submit button visible!")
                    page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_05_modal_review.png"))
                    (SNAPSHOT_DIR / "linkedin_05_modal_review.html").write_text(page.content(), encoding="utf-8")
                    print("[PROVEN] Captured linkedin_05_modal_review.*")
                    reached_review = True
                    break

                review_btn = modal.locator("button[aria-label='Review your application'], button:has-text('Review')").first
                if review_btn.count() > 0 and review_btn.is_visible():
                    print("[Phase 6c] Clicking Review button...")
                    safe_review = SafeLocator(review_btn, selector_hint="review-button")
                    safe_review.safe_click()
                    time.sleep(2)
                    continue

                next_btn = modal.locator("button[aria-label='Continue to next step'], button:has-text('Next')").first
                if next_btn.count() > 0 and next_btn.is_visible():
                    # Check if resume radio is present
                    resume_radio = modal.locator("input[type='radio'][id*='jobsDocumentCardToggle']").first
                    if resume_radio.count() > 0 and not resume_radio.is_checked():
                        safe_radio = SafeLocator(resume_radio, selector_hint="existing-resume-radio")
                        safe_radio.safe_check()
                        time.sleep(1)

                    print(f"[Phase 6c] Clicking Next button on step {step}...")
                    safe_next = SafeLocator(next_btn, selector_hint="continue-button")
                    safe_next.safe_click()
                    time.sleep(2)
                    continue

                break

            # If review reached: check follow checkbox and discard
            if reached_review:
                follow_box = modal.locator("label:has-text('Follow') input[type='checkbox']").first
                if follow_box.count() > 0:
                    was_checked = follow_box.is_checked()
                    lbl = modal.locator("label:has-text('Follow')").first.inner_text().strip()
                    print(f"[Follow Checkbox] Found: '{lbl}' | Pre-checked: {was_checked}")
                    safe_follow = SafeLocator(follow_box, selector_hint="follow-checkbox")
                    safe_follow.safe_uncheck_and_verify()
                    print(f"[SUCCESS] Follow checkbox unchecked and verified False!")

                # Dismiss and Discard
                dismiss_btn = modal.locator("button.artdeco-modal__dismiss, button[aria-label='Dismiss']").first
                if dismiss_btn.count() > 0:
                    safe_dismiss = SafeLocator(dismiss_btn, selector_hint="modal-dismiss-btn")
                    safe_dismiss.safe_click()
                    time.sleep(2)

                    discard_dialog = page.locator("div[data-test-modal], div.artdeco-modal").last
                    discard_btn = discard_dialog.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')").first
                    if discard_btn.count() > 0:
                        page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_06_discard_prompt.png"))
                        (SNAPSHOT_DIR / "linkedin_06_discard_prompt.html").write_text(page.content(), encoding="utf-8")
                        safe_discard = SafeLocator(discard_btn, selector_hint="discard-confirm-btn")
                        safe_discard.safe_click()
                        time.sleep(2)
                        page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_07_no_draft_confirmed.png"))
                        (SNAPSHOT_DIR / "linkedin_07_no_draft_confirmed.html").write_text(page.content(), encoding="utf-8")
                break
            else:
                # Close modal if not review step
                dismiss_btn = modal.locator("button.artdeco-modal__dismiss, button[aria-label='Dismiss']").first
                if dismiss_btn.count() > 0:
                    safe_dismiss = SafeLocator(dismiss_btn, selector_hint="modal-dismiss-btn")
                    safe_dismiss.safe_click()
                    time.sleep(1)
                    discard_dialog = page.locator("div[data-test-modal], div.artdeco-modal").last
                    discard_btn = discard_dialog.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')").first
                    if discard_btn.count() > 0:
                        safe_discard = SafeLocator(discard_btn, selector_hint="discard-confirm-btn")
                        safe_discard.safe_click()
                        time.sleep(1)

    finally:
        context.close()
        mgr.close()
        print("\n[Phase 6c] Completed observation session.")

if __name__ == "__main__":
    observe_review_step()
