import time
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import BrowserManager
from src.policy import SafePage, SafeLocator, PolicyBlockError, OBSERVE_ONLY

SNAPSHOT_DIR = Path("docs/snapshots")
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

def observe_linkedin_phase6c():
    """
    Phase 6c Read-Only Observations on LinkedIn:
    1. Search for Easy Apply jobs.
    2. Click Page 2 to capture Pagination Page N snapshot.
    3. Open an Easy Apply job detail.
    4. Click Easy Apply button to open modal.
    5. Step through Contact and Resume (selecting existing resume).
    6. Reach Review step: Snapshot Submit application button (DO NOT CLICK SUBMIT).
    7. Uncheck and verify 'Follow company' checkbox.
    8. Click Dismiss ('X') -> Snapshot Discard confirmation dialog.
    9. Click Discard -> Verify modal closes and no draft saved.
    """
    print("\n" + "="*60)
    print("PHASE 6c: READ-ONLY OBSERVATION (OBSERVE_ONLY = True)")
    print("="*60)
    import yaml
    profile = yaml.safe_load(open(Path(__file__).resolve().parent.parent / "config" / "profile.yaml", encoding="utf-8"))

    mgr = BrowserManager(headless=False)
    context = mgr.start()
    page = context.new_page()
    safe_page = SafePage(page)

    try:
        # Step 1: Navigate to LinkedIn jobs search
        search_url = "https://www.linkedin.com/jobs/search/?keywords=Senior+Full+Stack+Developer&location=India&f_AL=true"
        print(f"[Phase 6c] Navigating to: {search_url}")
        safe_page.safe_goto(search_url, wait_until="domcontentloaded")
        time.sleep(4)

        # Check pagination buttons on search results
        page2_btn = page.locator("button[aria-label='Page 2'], ul.jobs-search-pagination__pages button:has-text('2')").first
        if page2_btn.count() > 0:
            print("[Phase 6c] Found Page 2 button. Capturing pagination snapshot...")
            safe_page.locator("button[aria-label='Page 2']").safe_click()
            time.sleep(3)
            # Save pagination snapshot
            page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_08_pagination_page2.png"))
            (SNAPSHOT_DIR / "linkedin_08_pagination_page2.html").write_text(page.content(), encoding="utf-8")
            print("[PROVEN] Captured linkedin_08_pagination_page2.*")

        # Step 2: Find an Easy Apply job by checking cards
        cards = page.locator("div.job-card-container, li.jobs-search-results__list-item")
        print(f"[Phase 6c] Found {cards.count()} total job cards.")

        target_easy_apply_btn = None
        for i in range(min(12, cards.count())):
            c = cards.nth(i)
            # Scroll card into view
            c.scroll_into_view_if_needed()
            print(f"[Phase 6c] Checking card {i+1}...")
            safe_card = SafeLocator(c, selector_hint="job-card", is_job_card=True)
            safe_card.safe_click()
            time.sleep(2)

            details_pane = page.locator("div.jobs-search__job-details, div.job-view-layout, div.jobs-details").first
            easy_apply_btn = details_pane.locator("button.jobs-apply-button, button[aria-label*='Easy Apply']").first
            if easy_apply_btn.count() == 0:
                easy_apply_btn = page.locator("button.jobs-apply-button:has-text('Easy Apply'), button[aria-label^='Easy Apply']").first

            if easy_apply_btn.count() > 0:
                label = (easy_apply_btn.get_attribute("aria-label") or easy_apply_btn.inner_text()).lower()
                if "easy apply" in label:
                    print(f"[Phase 6c] Card {i+1} has Easy Apply button: '{label.strip()}'! Selecting this job.")
                    target_easy_apply_btn = easy_apply_btn
                    break

        if target_easy_apply_btn and target_easy_apply_btn.count() > 0:
            print("[Phase 6c] Clicking Easy Apply button to open modal...")
            safe_apply = SafeLocator(target_easy_apply_btn, selector_hint="button.jobs-apply-button")
            safe_apply.safe_click()
            time.sleep(3)

            # Wait for modal dialog
            modal = page.locator("div.jobs-easy-apply-modal, div[role='dialog']:has(button[aria-label='Dismiss'])").first
            modal.wait_for(state="visible", timeout=10000)
            print("[Phase 6c] Easy Apply modal dialog is visible.")

            # Track modal progression steps
            step_idx = 1
            max_modal_steps = 6

            while step_idx <= max_modal_steps:
                print(f"\n--- [Phase 6c] In Modal Step {step_idx} ---")
                
                # 1. Inspect and log all field types present in the modal
                inputs = modal.locator("input:visible")
                selects = modal.locator("select:visible")
                textareas = modal.locator("textarea:visible")
                radios = modal.locator("input[type='radio']:visible")
                checkboxes = modal.locator("input[type='checkbox']:visible")
                
                print(f"[Field Types Found] Inputs: {inputs.count()} | Selects: {selects.count()} | Textareas: {textareas.count()} | Radios: {radios.count()} | Checkboxes: {checkboxes.count()}")

                # Snapshot this step
                step_shot_png = SNAPSHOT_DIR / f"linkedin_modal_step_{step_idx}.png"
                step_shot_html = SNAPSHOT_DIR / f"linkedin_modal_step_{step_idx}.html"
                page.screenshot(path=str(step_shot_png))
                step_shot_html.write_text(page.content(), encoding="utf-8")
                print(f"[Phase 6c] Saved snapshot: {step_shot_png.name}")

                # Fill confirmed contact info if present on contact step
                email_select = modal.locator("select[id*='multipleChoice']").first
                if email_select.count() > 0 and email_select.is_visible():
                    email = profile.get("personal", {}).get("email")
                    if email:
                        print(f"[Phase 6c] Selecting confirmed email '{email}' in dropdown...")
                        safe_select = SafeLocator(email_select, selector_hint="email-select", is_form_field=True)
                        safe_select.safe_select_option(value=email)
                        time.sleep(1)

                phone_input = modal.locator("input[id*='phoneNumber']").first
                if phone_input.count() > 0 and phone_input.is_visible():
                    val = phone_input.input_value()
                    if not val.strip():
                        raw_phone = profile.get("personal", {}).get("phone", "")
                        digits = "".join(filter(str.isdigit, raw_phone))
                        if digits.startswith("91") and len(digits) > 10:
                            digits = digits[2:]
                        print(f"[Phase 6c] Filling confirmed phone digits...")
                        safe_phone = SafeLocator(phone_input, selector_hint="phone-input", is_form_field=True)
                        safe_phone.safe_fill(digits)
                        time.sleep(1)

                city_input = modal.locator("input[id*='location-GEO-LOCATION']").first
                if city_input.count() > 0 and city_input.is_visible():
                    val = city_input.input_value()
                    if not val.strip():
                        city = profile.get("personal", {}).get("current_city", "Jaipur")
                        print(f"[Phase 6c] Filling confirmed city '{city}'...")
                        safe_city = SafeLocator(city_input, selector_hint="city-input", is_form_field=True)
                        safe_city.safe_fill(city)
                        time.sleep(2)

                        # Check for autocomplete suggestion popup and select it to dismiss dropdown
                        auto_opt = modal.locator("div[data-test-single-typeahead-entity-form-search-result='true'], div.search-typeahead-v2__hit").first
                        if auto_opt.count() > 0 and auto_opt.is_visible():
                            print("[Phase 6c] Clicking city autocomplete suggestion to dismiss overlay...")
                            safe_opt = SafeLocator(auto_opt, selector_hint="city-autocomplete-option", is_form_field=True)
                            safe_opt.safe_click()
                            time.sleep(1)
                        else:
                            # Press Escape on city input to close popup
                            city_input.press("Escape")
                            time.sleep(1)

                # Check if Submit button is present in modal
                submit_btn = modal.locator("button[aria-label='Submit application'], button:has-text('Submit application')").first
                if submit_btn.count() > 0 and submit_btn.is_visible():
                    print("[Phase 6c] Reached Review Step! Submit application button is visible (NEVER CLICK).")
                    # Save dedicated review snapshot
                    page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_05_modal_review.png"))
                    (SNAPSHOT_DIR / "linkedin_05_modal_review.html").write_text(page.content(), encoding="utf-8")
                    print("[PROVEN] Captured linkedin_05_modal_review.*")
                    break

                # Check if Review button is present in modal
                review_btn = modal.locator("button[aria-label='Review your application'], button:has-text('Review')").first
                if review_btn.count() > 0 and review_btn.is_visible():
                    # Ensure existing resume radio is selected if on resume step
                    existing_resume_radio = modal.locator("input[type='radio'][id*='jobsDocumentCardToggle']").first
                    if existing_resume_radio.count() > 0 and not existing_resume_radio.is_checked():
                        print("[Phase 6c] Selecting existing stored resume radio...")
                        safe_radio = SafeLocator(existing_resume_radio, selector_hint="existing-resume-radio")
                        safe_radio.safe_check()
                        time.sleep(1)

                    print("[Phase 6c] Clicking Review button to reach Review Step...")
                    safe_review = SafeLocator(review_btn, selector_hint="review-button")
                    safe_review.safe_click()
                    time.sleep(2)
                    step_idx += 1
                    continue

                # Check for Next button in modal
                next_btn = modal.locator("button[aria-label='Continue to next step'], button:has-text('Next')").first
                if next_btn.count() > 0 and next_btn.is_visible():
                    # Ensure existing resume radio is selected if on resume step
                    existing_resume_radio = modal.locator("input[type='radio'][id*='jobsDocumentCardToggle']").first
                    if existing_resume_radio.count() > 0 and not existing_resume_radio.is_checked():
                        print("[Phase 6c] Selecting existing stored resume radio...")
                        safe_radio = SafeLocator(existing_resume_radio, selector_hint="existing-resume-radio")
                        safe_radio.safe_check()
                        time.sleep(1)

                    print("[Phase 6c] Clicking Next button to advance modal...")
                    safe_next = SafeLocator(next_btn, selector_hint="continue-button")
                    safe_next.safe_click()
                    time.sleep(2)
                    step_idx += 1
                    continue

                print("[Phase 6c] Terminal modal step reached.")
                break

            # At Review step: inspect Opt-in Follow Checkbox inside modal
            follow_box = modal.locator("label:has-text('Follow') input[type='checkbox']").first
            if follow_box.count() > 0:
                was_checked = follow_box.is_checked()
                label_text = modal.locator("label:has-text('Follow')").first.inner_text().strip()
                print(f"\n[Opt-in Checkbox] Found: '{label_text}' | Pre-checked: {was_checked}")
                print("[Phase 6c] Unchecking and verifying follow checkbox...")
                safe_follow = SafeLocator(follow_box, selector_hint="follow-checkbox")
                safe_follow.safe_uncheck_and_verify()
                print(f"[SUCCESS] Follow checkbox state verified: is_checked = {follow_box.is_checked()}")

            # Step 3: Trigger Discard prompt inside modal
            dismiss_btn = modal.locator("button.artdeco-modal__dismiss, button[aria-label='Dismiss']").first
            if dismiss_btn.count() > 0:
                print("\n[Phase 6c] Clicking Dismiss ('X') button on modal...")
                safe_dismiss = SafeLocator(dismiss_btn, selector_hint="modal-dismiss-btn")
                safe_dismiss.safe_click()
                time.sleep(2)

                # Snapshot Discard dialog
                discard_dialog = page.locator("div[data-test-modal], div.artdeco-modal").last
                discard_btn = discard_dialog.locator("button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')").first
                if discard_btn.count() > 0:
                    print("[Phase 6c] Snapshotting Discard prompt dialog...")
                    page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_06_discard_prompt.png"))
                    (SNAPSHOT_DIR / "linkedin_06_discard_prompt.html").write_text(page.content(), encoding="utf-8")
                    print("[PROVEN] Captured linkedin_06_discard_prompt.*")

                    # Click Discard
                    print("[Phase 6c] Clicking Discard button...")
                    safe_discard = SafeLocator(discard_btn, selector_hint="discard-confirm-btn")
                    safe_discard.safe_click()
                    time.sleep(2)

                    # Confirm no draft saved
                    page.screenshot(path=str(SNAPSHOT_DIR / "linkedin_07_no_draft_confirmed.png"))
                    (SNAPSHOT_DIR / "linkedin_07_no_draft_confirmed.html").write_text(page.content(), encoding="utf-8")
                    print("[PROVEN] Captured linkedin_07_no_draft_confirmed.*")

    finally:
        context.close()
        mgr.close()
        print("\n[Phase 6c] Completed observation session.")

if __name__ == "__main__":
    observe_linkedin_phase6c()
