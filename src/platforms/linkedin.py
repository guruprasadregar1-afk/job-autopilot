import time
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from src.policy import SafePage, SafeLocator
from src.matcher import JobMatcher, MatchResult
from src.guards import GuardsManager, ResumeMismatchHaltError
from src.db import Database

class LinkedInCollector:
    def __init__(self, db: Database, guards: GuardsManager, matcher: JobMatcher):
        self.db = db
        self.guards = guards
        self.matcher = matcher
        self.platform = "linkedin"

    def run_phase8a_search(
        self,
        page,
        search_query: Dict[str, Any],
        max_jobs: int = 10,
        dry_run: bool = True,
        applicant: Optional[Any] = None,
        is_rehearsal: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Search, collect, dedupe, hard-filter, check Easy Apply button with bounded timeout,
        reuse stored score (or call Claude matcher), and if applicant provided, run application flow.
        """
        safe_page = SafePage(page)
        keywords = search_query.get("keywords", "Senior Full Stack Developer")
        location = search_query.get("location", "India")
        f_al = "true" if search_query.get("f_AL", True) else "false"

        url = f"https://www.linkedin.com/jobs/search/?keywords={keywords.replace(' ', '+')}&location={location.replace(' ', '+')}&f_AL={f_al}"
        print(f"\n[LinkedIn Search] Navigating to search: {url}")
        safe_page.safe_goto(url, wait_until="domcontentloaded")
        self.guards.action_delay()
        self.guards.check_page_safety(page, self.platform)

        # Collect job cards
        cards = page.locator("li.jobs-search-results__list-item, div.job-card-container")
        card_count = cards.count()
        print(f"[LinkedIn Search] Found {card_count} job cards on current page.")

        collected_jobs = []

        for i in range(min(max_jobs, card_count)):
            self.guards.check_pre_job_guards(self.platform)
            card = cards.nth(i)

            # Extract job ID
            job_id = None
            try:
                job_id = card.get_attribute("data-job-id")
                if not job_id:
                    inner_container = card.locator("div[data-job-id]").first
                    if inner_container.count() > 0:
                        job_id = inner_container.get_attribute("data-job-id")
                    else:
                        job_id = card.get_attribute("data-occludable-job-id")
            except Exception:
                pass

            if not job_id:
                print(f"[SKIP] LinkedIn card {i+1} has no real job ID. Logged NO_JOB_ID. Skipping.")
                continue

            # Structural safe locator for the job card
            safe_card = SafeLocator(card, selector_hint=f"div[data-job-id='{job_id}']")

            # Extract Title, Company & Location
            title = ""
            company = ""
            location = ""
            try:
                title_el = card.locator("a.job-card-list__title--link").first
                if title_el.count() > 0:
                    title = title_el.inner_text().strip()
                comp_el = card.locator("span.job-card-container__primary-description, .artdeco-entity-lockup__subtitle").first
                if comp_el.count() > 0:
                    company = comp_el.inner_text().strip()
                loc_el = card.locator("ul.job-card-container__metadata-wrapper li, .artdeco-entity-lockup__caption").first
                if loc_el.count() > 0:
                    location = loc_el.inner_text().strip()
            except Exception:
                pass

            if not location:
                location = search_query.get("location", "India")

            if not title:
                continue

            print(f"\n--- [LinkedIn Search] Inspecting Job {i+1}: {title} @ {company} (ID: {job_id}) ---")

            # 1. Dedupe against DB (only final outcomes block: APPLIED, UNVERIFIED, EXTERNAL_SITE, SKIPPED, SKIPPED_BY_USER, FAILED >= 2)
            if self.db.is_job_blocked(self.platform, job_id):
                print(f"[DEDUPE] Job {job_id} already has a final blocking outcome in DB. Skipping.")
                continue

            # 2. Hard-filter in Python (checks company blacklist, excluded titles, regional restrictions, location)
            is_rejected, reject_reason = self.matcher.evaluate_hard_filters(title, company, location)
            if is_rejected:
                print(f"[HARD-REJECT] {reject_reason}")
                self.db.record_job(
                    platform=self.platform,
                    job_id=job_id,
                    title=title,
                    company=company,
                    location=location,
                    status="SKIPPED",
                    failure_reason=reject_reason
                )
                continue

            # 3. Open job card via structural selector to view full description
            safe_card.safe_click()
            self.guards.action_delay()
            self.guards.check_page_safety(page, self.platform)

            # Wait for detail pane to render and check Easy Apply button presence with bounded timeout
            apply_btn_loc = page.locator(
                "div.jobs-search__job-details button#jobs-apply-button-id, "
                "div.jobs-search__job-details button:has-text('Easy Apply'), "
                "div.jobs-search__job-details button.jobs-apply-button, "
                "button#jobs-apply-button-id, "
                "button:has-text('Easy Apply')"
            )
            has_apply_btn = False
            try:
                if hasattr(apply_btn_loc, "first") and hasattr(apply_btn_loc.first, "wait_for"):
                    apply_btn_loc.first.wait_for(state="visible", timeout=3000)
                    has_apply_btn = True
                elif apply_btn_loc.count() > 0:
                    has_apply_btn = True
            except Exception:
                has_apply_btn = (apply_btn_loc.count() > 0)

            if not has_apply_btn:
                # Check if an Applied indicator is present
                applied_indicator = page.locator(
                    "div.jobs-search__job-details span:has-text('Applied'), "
                    "div.jobs-search__job-details div:has-text('Applied'), "
                    "span.artdeco-inline-feedback__message:has-text('Applied'), "
                    "div.jobs-s-apply__application-link"
                )
                is_already_applied = False
                try:
                    if applied_indicator.count() > 0:
                        txt = applied_indicator.first.inner_text().strip().lower()
                        if "applied" in txt:
                            is_already_applied = True
                except Exception:
                    pass

                if is_already_applied:
                    print(f"[SKIP] Applied indicator detected for job {job_id} -> ALREADY_APPLIED_OR_NA (final)")
                    self.db.record_job(
                        platform=self.platform,
                        job_id=job_id,
                        title=title,
                        company=company,
                        location=location,
                        status="SKIPPED",
                        failure_reason="ALREADY_APPLIED_OR_NA"
                    )
                    continue
                else:
                    reason = "APPLY_BUTTON_NOT_FOUND: Easy Apply button not visible after bounded timeout (no Applied indicator detected)"
                    print(f"[LOG] {reason} for job {job_id} ('{title}' @ '{company}'). Not marked final.")
                    self.db.record_job(
                        platform=self.platform,
                        job_id=job_id,
                        title=title,
                        company=company,
                        location=location,
                        status="APPLY_BUTTON_NOT_FOUND",
                        failure_reason=reason
                    )
                    continue

            # 4. Extract Description
            description = ""
            desc_el = page.locator("div.jobs-description-content__text, article.jobs-description__container")
            if desc_el.count() > 0:
                description = desc_el.first.inner_text().strip()

            # 5. Fit Evaluation (Reuse stored score if in DB, otherwise call Claude)
            stored_score, stored_reason = None, None
            if hasattr(self.db, "get_job_match_score"):
                try:
                    score_res = self.db.get_job_match_score(self.platform, job_id)
                    if isinstance(score_res, (tuple, list)) and len(score_res) == 2:
                        stored_score, stored_reason = score_res
                except Exception:
                    stored_score, stored_reason = None, None
            if stored_score is not None:
                threshold = 65
                if hasattr(self.matcher, "settings") and isinstance(self.matcher.settings, dict):
                    threshold = self.matcher.settings.get("llm", {}).get("match_score_threshold", 65)
                try:
                    threshold = int(threshold)
                except (ValueError, TypeError):
                    threshold = 65
                score = stored_score
                should_apply = score >= threshold
                reason = stored_reason or "Stored score from previous evaluation"
                print(f"[REUSE SCORE] Job {job_id} already scored in DB: {score} | Apply: {should_apply} (0 Claude calls)")
            else:
                match_res: MatchResult = self.matcher.evaluate_fit(title, company, location, description)
                score = match_res.score
                should_apply = match_res.should_apply
                reason = match_res.reason
                print(f"[MATCH RESULT] Score: {score} | Apply: {should_apply} | Reason: {reason}")

            status = "FOUND" if should_apply else "SKIPPED"
            self.db.record_job(
                platform=self.platform,
                job_id=job_id,
                title=title,
                company=company,
                location=location,
                description=description[:1000],
                match_score=score,
                match_reason=reason,
                status=status
            )

            job_data = {
                "platform": self.platform,
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "match_score": score,
                "should_apply": should_apply,
                "reason": reason
            }
            collected_jobs.append(job_data)

            # 6. Apply Flow: If applicant provided and job meets threshold
            if not dry_run and applicant and should_apply:
                if hasattr(self.guards, "session_attempts_count") and hasattr(self.guards, "max_attempts"):
                    if self.guards.session_attempts_count >= self.guards.max_attempts:
                        print(f"[ATTEMPTS LIMIT] Session attempts cap reached ({self.guards.session_attempts_count}/{self.guards.max_attempts}). Stopping.")
                        break

                print(f"[APPLY FLOW] Opening Easy Apply for '{title}' @ '{company}' (ID: {job_id})...")
                safe_apply_btn = SafeLocator(apply_btn_loc.first, selector_hint="Easy Apply button")
                safe_apply_btn.safe_click()
                time.sleep(1)

                app_res = applicant.process_application(
                    page,
                    job_id=job_id,
                    title=title,
                    company=company,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                    match_score=score,
                    match_reason=reason
                )
                print(f"[APPLY RESULT] Outcome: {app_res.get('status')}")

            elif dry_run:
                print(f"[DRY-RUN 8a] Match evaluation complete. No apply button clicked.")

        return collected_jobs

    def process_eligible_found_jobs(self, page, applicant: Any, limit: int = 10, is_rehearsal: bool = False) -> List[Dict[str, Any]]:
        """
        Processes jobs already in DB with status 'FOUND' before searching for new jobs.
        Navigates directly to job view URL, opens Easy Apply, and runs applicant flow.
        """
        found_jobs = self.db.get_eligible_found_jobs(self.platform, limit=limit)
        if not found_jobs:
            return []

        print(f"\n[LinkedIn Pipeline] Found {len(found_jobs)} eligible FOUND jobs in database to process first.")
        processed = []
        safe_page = SafePage(page)

        for j in found_jobs:
            if hasattr(self.guards, "session_attempts_count") and hasattr(self.guards, "max_attempts"):
                if self.guards.session_attempts_count >= self.guards.max_attempts:
                    print(f"[ATTEMPTS LIMIT] Session attempts cap reached ({self.guards.session_attempts_count}/{self.guards.max_attempts}). Stopping.")
                    break

            job_id = j["job_id"]
            title = j["title"]
            company = j["company"]
            url = j.get("url") or f"https://www.linkedin.com/jobs/view/{job_id}/"
            match_score = j.get("match_score")
            match_reason = j.get("match_reason") or ""

            try:
                self.guards.check_pre_job_guards(self.platform)
            except Exception as e:
                print(f"[GUARD STOP] Halting FOUND jobs processing: {e}")
                break

            print(f"\n--- [LinkedIn Pipeline] Processing FOUND Job: {title} @ {company} (ID: {job_id}) ---")
            safe_page.safe_goto(url, wait_until="domcontentloaded")
            self.guards.action_delay()
            self.guards.check_page_safety(page, self.platform)

            # Wait for apply button with bounded timeout
            apply_btn_loc = page.locator(
                "div.jobs-search__job-details button#jobs-apply-button-id, "
                "div.jobs-search__job-details button:has-text('Easy Apply'), "
                "div.jobs-search__job-details button.jobs-apply-button, "
                "button#jobs-apply-button-id, "
                "button:has-text('Easy Apply')"
            )
            has_apply_btn = False
            try:
                if hasattr(apply_btn_loc, "first") and hasattr(apply_btn_loc.first, "wait_for"):
                    apply_btn_loc.first.wait_for(state="visible", timeout=3000)
                    has_apply_btn = True
                elif apply_btn_loc.count() > 0:
                    has_apply_btn = True
            except Exception:
                has_apply_btn = (apply_btn_loc.count() > 0)

            if not has_apply_btn:
                applied_indicator = page.locator(
                    "div.jobs-search__job-details span:has-text('Applied'), "
                    "div.jobs-search__job-details div:has-text('Applied'), "
                    "span.artdeco-inline-feedback__message:has-text('Applied'), "
                    "div.jobs-s-apply__application-link"
                )
                is_already_applied = False
                try:
                    if applied_indicator.count() > 0:
                        txt = applied_indicator.first.inner_text().strip().lower()
                        if "applied" in txt:
                            is_already_applied = True
                except Exception:
                    pass

                if is_already_applied:
                    print(f"[SKIP] Applied indicator detected for job {job_id} -> ALREADY_APPLIED_OR_NA")
                    self.db.update_job_status(
                        platform=self.platform,
                        job_id=job_id,
                        status="SKIPPED",
                        failure_reason="ALREADY_APPLIED_OR_NA"
                    )
                else:
                    reason = "APPLY_BUTTON_NOT_FOUND: Easy Apply button not visible after bounded timeout (no Applied indicator detected)"
                    print(f"[LOG] {reason} for job {job_id}. Not marked final.")
                    self.db.update_job_status(
                        platform=self.platform,
                        job_id=job_id,
                        status="APPLY_BUTTON_NOT_FOUND",
                        failure_reason=reason
                    )
                continue

            # Open Easy Apply modal
            print(f"[APPLY FLOW] Opening Easy Apply for '{title}' @ '{company}' (ID: {job_id})...")
            safe_apply_btn = SafeLocator(apply_btn_loc.first, selector_hint="Easy Apply button")
            safe_apply_btn.safe_click()
            time.sleep(1)

            res = applicant.process_application(
                page,
                job_id=job_id,
                title=title,
                company=company,
                url=url,
                match_score=match_score,
                match_reason=match_reason
            )
            processed.append(res)

        return processed

    def run_search_and_apply(
        self,
        page,
        search_query: Dict[str, Any],
        applicant: Any,
        max_jobs: int = 10,
        is_rehearsal: bool = False,
        dry_run: bool = False
    ) -> List[Dict[str, Any]]:
        """Convenience method to execute search collection followed by applicant flow."""
        return self.run_phase8a_search(
            page=page,
            search_query=search_query,
            max_jobs=max_jobs,
            dry_run=dry_run,
            applicant=applicant,
            is_rehearsal=is_rehearsal
        )


class LinkedInApplicant:
    """
    Phase 8b: LinkedIn Easy Apply modal progression engine.
    Strict constraints enforced:
    1. Resume selected by exact character-for-character filename from config/profile.yaml.
       If absent -> logs and records RESUME_NOT_FOUND, discards modal, and stops. Never uploads.
    2. Form fields answered from config/answers.yaml ONLY.
       If any field has no confirmed answer -> logs and records NEEDS_INPUT, discards modal, and stops.
    3. Follow-company checkbox is safely unchecked and re-verified.
    4. Advances to Review step.
    5. In OBSERVE_ONLY mode (code constant), NEVER clicks Submit application; discards modal.
    6. Post-submit confirmation verification: if confirmation not found -> UNVERIFIED and halt run.
    """
    def __init__(self, db: Database, guards: GuardsManager, answerer: Optional[Any] = None, profile_path: Optional[Path] = None, review_mode: bool = False, is_rehearsal: bool = False):
        from pathlib import Path
        import yaml
        from src.answerer import FormAnswerer, format_numeric_digits_only
        from src.policy import OBSERVE_ONLY, verify_and_record_post_submit

        self.db = db
        self.guards = guards
        self.answerer = answerer or FormAnswerer()
        self.platform = "linkedin"
        self.is_rehearsal = is_rehearsal
        self.observe_only = OBSERVE_ONLY or is_rehearsal
        self.review_mode = review_mode
        self.answers_filled: Dict[str, Any] = {}

        p_path = profile_path or Path(__file__).resolve().parent.parent.parent / "config" / "profile.yaml"
        if not p_path.exists():
            p_path = Path(__file__).resolve().parent.parent / "config" / "profile.yaml"

        with open(p_path, "r", encoding="utf-8") as f:
            self.profile = yaml.safe_load(f)

    def get_step_fingerprint(self, modal) -> str:
        """Returns a fingerprint string of the current modal step to detect stuck forms."""
        headers = modal.locator("h3, legend, span.jobs-easy-apply-form-section__group-subtitle, label").all_inner_texts()
        return " | ".join(h.strip() for h in headers if h.strip())

    def handle_city_typeahead(self, modal) -> None:
        """Fills City typeahead from config/profile.yaml personal.current_city."""
        city = self.profile.get("personal", {}).get("current_city", "Jaipur")
        city_loc = modal.locator(
            "div[data-test-single-typeahead-entity-form-component] input, "
            "input[id*='GEO-LOCATION']"
        )
        if city_loc.count() > 0:
            city_input = city_loc.first
            current_val = city_input.input_value() if hasattr(city_input, "input_value") else ""
            if not current_val:
                SafeLocator(city_input, selector_hint="City typeahead input", is_form_field=True).safe_fill(city)
                self.answers_filled["City"] = city

    def _get_card_filename(self, card) -> str:
        """Safely extracts resume filename from a resume card container."""
        try:
            fn_loc = card.locator("h3.jobs-document-upload-redesign-card__file-name")
            target = fn_loc.first if hasattr(fn_loc, "first") else fn_loc
            txt = target.inner_text() if hasattr(target, "inner_text") else ""
            if txt and not str(txt).startswith("<MagicMock"):
                return str(txt).strip()
            txt = fn_loc.inner_text() if hasattr(fn_loc, "inner_text") else ""
            if txt and not str(txt).startswith("<MagicMock"):
                return str(txt).strip()
        except Exception:
            pass
        return ""

    def select_resume_by_name(self, modal) -> bool:
        """
        Locates stored resume matching profile.yaml resume.selected_filename exactly.
        Fails if absent. Never clicks upload.
        After selecting the resume radio, re-reads which radio is checked and compares it
        to the exact configured filename. If different, raises ResumeMismatchHaltError.
        """
        expected_filename = self.profile.get("resume", {}).get("selected_filename", "").strip()

        cards = modal.locator("div.jobs-document-upload-redesign-card__container")
        card_count = cards.count()
        if card_count == 0:
            return True  # Step does not require resume selection

        if not expected_filename or expected_filename == "PENDING_USER_CONFIRMATION":
            raise ResumeMismatchHaltError(
                f"RESUME_PENDING_CONFIRMATION: Resume filename is '{expected_filename or 'EMPTY'}'. Run halted."
            )

        found_index = -1
        for i in range(card_count):
            c = cards.nth(i)
            fn_text = self._get_card_filename(c)

            # Exact character-for-character match
            if fn_text == expected_filename:
                found_index = i
                break

        if found_index == -1:
            raise ResumeMismatchHaltError(
                f"RESUME_NOT_FOUND: Configured resume '{expected_filename}' not found among {card_count} stored resumes in modal. Run halted."
            )

        target_card = cards.nth(found_index)
        self.answers_filled["Resume"] = expected_filename

        cls_val = target_card.get_attribute("class") or ""
        aria_val = target_card.get_attribute("aria-label") or ""
        is_selected = "selected" in cls_val.lower() or aria_val.strip().lower() == "selected"
        if not is_selected:
            radio_loc = target_card.locator("input[type='radio'], label[for*='jobsDocumentCardToggle']")
            has_radio = True
            try:
                cnt = radio_loc.count()
                if isinstance(cnt, int) and cnt == 0:
                    has_radio = False
            except Exception:
                pass
            if has_radio:
                radio_el = radio_loc.first if hasattr(radio_loc, "first") else radio_loc
                SafeLocator(radio_el, selector_hint=f"Select resume radio: {expected_filename}").safe_click(force=True)

        # Post-selection verification: re-read which radio is checked and compare to expected_filename
        checked_filename = None
        for i in range(card_count):
            c = cards.nth(i)
            is_checked = False
            cls = (c.get_attribute("class") or "").lower()
            aria = (c.get_attribute("aria-label") or "").strip().lower()
            if "selected" in cls or aria == "selected":
                is_checked = True
            else:
                try:
                    r = c.locator("input[type='radio']").first
                    if hasattr(r, "is_checked"):
                        val = r.is_checked()
                        if val is True:
                            is_checked = True
                    if not is_checked and hasattr(r, "get_attribute"):
                        checked_attr = r.get_attribute("checked")
                        if checked_attr and not str(checked_attr).startswith("<MagicMock") and str(checked_attr).lower() in ("true", "checked"):
                            is_checked = True
                except Exception:
                    pass


            if is_checked:
                fn_text_checked = self._get_card_filename(c)
                if fn_text_checked:
                    checked_filename = fn_text_checked
                    break

        if checked_filename != expected_filename:
            raise ResumeMismatchHaltError(
                f"RESUME_MISMATCH: After selecting resume, checked resume is '{checked_filename}', expected '{expected_filename}'. Run halted."
            )

        return True

    def answer_screening_fields(self, modal) -> Tuple[bool, Optional[str]]:
        """
        Answers form fields from answers.yaml ONLY.
        Returns (True, None) if all answered, or (False, question_text) if unknown.
        """
        from src.answerer import format_numeric_digits_only

        # 1. Check numeric and text inputs
        inputs = modal.locator("input.artdeco-text-input--input, input[data-test-single-line-text-input]")
        for i in range(inputs.count()):
            inp = inputs.nth(i)
            parent = inp.locator("xpath=ancestor::div[contains(@class, 'fb-dash-form-element') or contains(@class, 'artdeco-text-input--container')]").first
            label_el = parent.locator("label, span.jobs-easy-apply-form-section__group-subtitle").first
            q_text = label_el.inner_text().strip() if label_el.count() > 0 else "Unknown question"

            # Check if LinkedIn profile URL (must stay unanswered until user gives it in writing)
            if "linkedin" in q_text.lower() and "profile" in q_text.lower():
                return False, q_text

            is_numeric = "numeric" in (inp.get_attribute("id") or "") or "numeric" in (inp.get_attribute("inputmode") or "")
            field_type = "number" if is_numeric else "text"

            ans = self.answerer.find_direct_answer(q_text, field_type=field_type)
            if not ans or ans == "UNKNOWN":
                return False, q_text

            # Succeeded for INR compensation or notice period in days
            is_inr_or_notice = any(k in q_text.lower() for k in ["ctc", "salary", "compensation", "inr", "notice period", "notice"])
            if is_inr_or_notice:
                fill_val = format_numeric_digits_only(ans)
                if fill_val == "UNKNOWN":
                    return False, q_text
            else:
                fill_val = ans

            SafeLocator(inp, selector_hint=f"Form input: {q_text[:25]}", is_form_field=True).safe_fill(fill_val)
            self.answers_filled[q_text] = fill_val

        # 2. Check dropdowns
        selects = modal.locator("select")
        for i in range(selects.count()):
            sel = selects.nth(i)
            parent = sel.locator("xpath=ancestor::div[contains(@class, 'fb-dash-form-element')]").first
            label_el = parent.locator("label, span[data-test-text-entity-list-form-title]").first
            q_text = label_el.inner_text().strip() if label_el.count() > 0 else "Unknown dropdown"

            opts_count = sel.locator("option").count()
            options = [sel.locator("option").nth(oi).inner_text().strip() for oi in range(opts_count)]
            options = [o for o in options if o and not o.lower().startswith("select")]

            ans = self.answerer.find_direct_answer(q_text, field_type="dropdown", options=options)
            if not ans or ans == "UNKNOWN":
                return False, q_text

            SafeLocator(sel, selector_hint=f"Form dropdown: {q_text[:25]}", is_form_field=True).safe_select_option(value=ans)
            self.answers_filled[q_text] = ans

        # 3. Check radio groups (fieldsets)
        fieldsets = modal.locator("fieldset")
        for i in range(fieldsets.count()):
            fs = fieldsets.nth(i)
            if fs.locator("div.jobs-document-upload-redesign-card__container").count() > 0:
                continue
            radios = fs.locator("input[type='radio']")
            if radios.count() == 0:
                continue
            legend_el = fs.locator("legend, span.jobs-easy-apply-form-section__group-subtitle").first
            q_text = legend_el.inner_text().strip() if legend_el.count() > 0 else "Unknown radio question"

            options = []
            for ri in range(radios.count()):
                r_el = radios.nth(ri)
                r_id = r_el.get_attribute("id") or ""
                r_lbl = fs.locator(f"label[for='{r_id}']").first if r_id else None
                if r_lbl and r_lbl.count() > 0:
                    options.append(r_lbl.inner_text().strip())
                else:
                    val = r_el.get_attribute("value") or ""
                    if val:
                        options.append(val)

            ans = self.answerer.find_direct_answer(q_text, field_type="radio", options=options)
            if not ans or ans == "UNKNOWN":
                return False, q_text

            clicked = False
            for ri in range(radios.count()):
                r_el = radios.nth(ri)
                r_id = r_el.get_attribute("id") or ""
                r_lbl = fs.locator(f"label[for='{r_id}']").first if r_id else None
                lbl_text = r_lbl.inner_text().strip() if r_lbl and r_lbl.count() > 0 else (r_el.get_attribute("value") or "")
                if lbl_text.lower() == str(ans).lower():
                    SafeLocator(r_el, selector_hint=f"Radio option: {lbl_text}").safe_click(force=True)
                    self.answers_filled[q_text] = ans
                    clicked = True
                    break
            if not clicked:
                return False, q_text

        # 4. Check standalone checkboxes (excluding follow-company)
        checkboxes = modal.locator("input[type='checkbox']")
        for i in range(checkboxes.count()):
            cb = checkboxes.nth(i)
            cb_id = cb.get_attribute("id") or ""
            cb_name = cb.get_attribute("name") or ""
            if "follow" in cb_id.lower() or "follow" in cb_name.lower():
                continue
            parent = cb.locator("xpath=ancestor::div[contains(@class, 'fb-dash-form-element')]").first
            lbl = parent.locator("label").first if parent.count() > 0 else modal.locator(f"label[for='{cb_id}']").first
            q_text = lbl.inner_text().strip() if lbl and lbl.count() > 0 else "Unknown checkbox"

            ans = self.answerer.find_direct_answer(q_text, field_type="checkbox")
            if not ans or ans == "UNKNOWN":
                return False, q_text

            if str(ans).lower() in ("true", "yes", "checked", "1"):
                SafeLocator(cb, selector_hint=f"Checkbox: {q_text}").safe_check()
                self.answers_filled[q_text] = "Yes"
            else:
                SafeLocator(cb, selector_hint=f"Checkbox: {q_text}").safe_uncheck_and_verify()
                self.answers_filled[q_text] = "No"

        # 5. Check textareas
        textareas = modal.locator("textarea")
        for i in range(textareas.count()):
            ta = textareas.nth(i)
            parent = ta.locator("xpath=ancestor::div[contains(@class, 'fb-dash-form-element')]").first
            label_el = parent.locator("label, span.jobs-easy-apply-form-section__group-subtitle").first
            q_text = label_el.inner_text().strip() if label_el.count() > 0 else "Unknown textarea"

            ans = self.answerer.find_direct_answer(q_text, field_type="textarea")
            if not ans or ans == "UNKNOWN":
                return False, q_text

            SafeLocator(ta, selector_hint=f"Form textarea: {q_text[:25]}", is_form_field=True).safe_fill(ans)
            self.answers_filled[q_text] = ans

        return True, None

    def uncheck_follow_company(self, modal) -> str:
        """Unchecks follow company checkbox using safe_uncheck_and_verify and returns verification state."""
        follow_cb = modal.locator(
            "input[type='checkbox'][id*='follow'], "
            "label:has-text('Follow') input[type='checkbox'], "
            "input#follow-company-checkbox"
        ).first
        if follow_cb.count() > 0:
            SafeLocator(follow_cb, selector_hint="Follow company checkbox").safe_uncheck_and_verify()
            return "unchecked, verified"
        return "not present / unchecked, verified"

    def discard_modal(self, page) -> None:
        """Safely discards draft application and dismisses modal."""
        dismiss_btn = page.locator("button[aria-label='Dismiss'], button.artdeco-modal__dismiss").first
        if dismiss_btn.count() > 0:
            SafeLocator(dismiss_btn, selector_hint="Dismiss modal button").safe_click()
            time.sleep(0.5)
            discard_btn = page.locator(
                "button[data-control-name='discard_application_confirm_btn'], "
                "button:has-text('Discard')"
            ).first
            if discard_btn.count() > 0:
                SafeLocator(discard_btn, selector_hint="Confirm discard draft button").safe_click()

    def process_application(self, page, job_id: str, title: str, company: str, url: str = "", match_score: Optional[int] = None, match_reason: str = "") -> Dict[str, Any]:
        """
        Executes LinkedIn modal progression with stuck-step guard and max 8 step cap.
        Under OBSERVE_ONLY: advances to Review, verifies fields, and discards draft without submit.
        """
        self.answers_filled = {}
        if hasattr(self.guards, "record_form_opened"):
            self.guards.record_form_opened(platform=self.platform, job_id=job_id)

        def _finish(res: Dict[str, Any]) -> Dict[str, Any]:
            st = res.get("status", "SKIPPED")
            if hasattr(self.guards, "record_attempt_outcome"):
                self.guards.record_attempt_outcome(st)
            if st == "NEEDS_INPUT" and hasattr(self.guards, "record_needs_input"):
                self.guards.record_needs_input(job_id, res.get("question", "Unknown question"))
            elif st in ("FAILED", "STUCK_STEP", "STEP_CAP_EXCEEDED", "RESUME_NOT_FOUND", "RESUME_MISMATCH") and hasattr(self.guards, "record_failure_reason"):
                self.guards.record_failure_reason(job_id, res.get("reason", "Unknown failure"))
            if hasattr(self.guards, "check_attempts_guard"):
                self.guards.check_attempts_guard()
            return res

        modal = page.locator("div.jobs-easy-apply-modal, div[data-test-modal]").first
        MAX_STEPS = 8
        current_step = 0
        previous_fingerprint = None

        while current_step < MAX_STEPS:
            current_step += 1
            fingerprint = self.get_step_fingerprint(modal)

            # Stuck-step guard: if fingerprint is unchanged after previous step
            if previous_fingerprint is not None and fingerprint == previous_fingerprint:
                print(f"[STUCK STEP GUARD] Step {current_step} did not advance! Form unchanged. Halting.")
                self.db.update_job_status(
                    platform=self.platform,
                    job_id=job_id,
                    status="FAILED",
                    failure_reason="STUCK_STEP: Modal form step did not advance after click"
                )
                self.discard_modal(page)
                return _finish({"status": "FAILED", "reason": "STUCK_STEP: Form did not advance"})

            previous_fingerprint = fingerprint

            # 1. City typeahead from config
            self.handle_city_typeahead(modal)

            # 2. Resume selection check (Fatal halt on missing/pending/mismatch)
            try:
                self.select_resume_by_name(modal)
            except ResumeMismatchHaltError as e:
                err_msg = str(e)
                if "RESUME_PENDING_CONFIRMATION" in err_msg:
                    st = "RESUME_PENDING_CONFIRMATION"
                elif "RESUME_NOT_FOUND" in err_msg:
                    st = "RESUME_NOT_FOUND"
                else:
                    st = "RESUME_MISMATCH"
                print(f"[FATAL RESUME HALT] {err_msg}")
                self.db.update_job_status(
                    platform=self.platform,
                    job_id=job_id,
                    status=st,
                    failure_reason=err_msg
                )
                self.discard_modal(page)
                _finish({"status": st, "reason": err_msg})
                raise

            # 3. Form fields / screening questions check
            fields_ok, pending_q = self.answer_screening_fields(modal)
            if not fields_ok:
                self.db.update_job_status(
                    platform=self.platform,
                    job_id=job_id,
                    status="NEEDS_INPUT",
                    pending_question=pending_q or "Unknown question"
                )
                self.discard_modal(page)
                return _finish({"status": "NEEDS_INPUT", "question": pending_q})

            # 4. Review step check
            is_review = modal.locator(
                "h3:has-text('Review'), "
                "button:has-text('Submit application'), "
                "span:has-text('Review your application')"
            ).count() > 0

            if is_review:
                follow_state = self.uncheck_follow_company(modal)
                if hasattr(self.guards, "record_review_reached"):
                    self.guards.record_review_reached(job_id, follow_state)

                # Each Review reached must print: job title, company, follow-company state, and every answer to be sent
                print("\n" + "="*70)
                print("                     REVIEW STEP REACHED")
                if self.observe_only or self.is_rehearsal:
                    print("         (REHEARSAL / OBSERVE_ONLY - SUBMIT IMPOSSIBLE)")
                else:
                    print("                (LIVE REVIEW CONFIRMATION)")
                print("="*70)
                print(f"Job Title           : {title}")
                print(f"Company             : {company}")
                print(f"URL                 : {url or f'https://www.linkedin.com/jobs/view/{job_id}/'}")
                print(f"Follow Company State: {follow_state}")
                print(f"Match Score         : {match_score if match_score is not None else 'N/A'}")
                print(f"Match Reason        : {match_reason or 'Profile skills and background match'}")
                print(f"Total Steps Handled : {current_step}")
                print("\nAnswers to be submitted:")
                if self.answers_filled:
                    for q, a in self.answers_filled.items():
                        print(f"  - {q}: {a}")
                else:
                    print("  - (Standard profile data applied; no custom screening answers)")
                print("="*70 + "\n")

                if self.observe_only or self.is_rehearsal:
                    print(f"[REHEARSAL / OBSERVE_ONLY] Reached Review step for '{title}' @ '{company}'. Submit blocked. Discarding draft.")
                    self.discard_modal(page)
                    self.db.update_job_status(
                        platform=self.platform,
                        job_id=job_id,
                        status="OBSERVED_REVIEW"
                    )
                    return _finish({"status": "OBSERVED_REVIEW", "job_id": job_id})

                # Live Submit branch (only possible when OBSERVE_ONLY = False and is_rehearsal = False):
                # Strict requirement: Even with OBSERVE_ONLY False, Submit requires --review and typed "YES" in terminal
                if not self.review_mode:
                    print(f"[SAFETY BLOCK] Live submit requires --review mode enabled. Discarding draft for '{title}' @ '{company}'.")
                    self.discard_modal(page)
                    return _finish({"status": "BLOCKED_REQUIRES_REVIEW", "job_id": job_id})

                try:
                    user_confirm = input("Type 'YES' to confirm and submit application: ").strip()
                except (EOFError, KeyboardInterrupt):
                    user_confirm = ""

                if user_confirm != "YES":
                    print(f"[SKIPPED] Submit cancelled by user (confirmation was '{user_confirm}', expected 'YES'). Discarding modal.")
                    self.discard_modal(page)
                    return _finish({"status": "SKIPPED_BY_USER", "job_id": job_id})

                from src.policy import verify_and_record_post_submit, handle_post_apply_dialog
                submit_btn = modal.locator("button:has-text('Submit application'), button[aria-label='Submit application']").first
                if submit_btn.count() > 0:
                    SafeLocator(submit_btn, selector_hint="Submit application button").safe_click()
                    time.sleep(2)
                    verify_res = verify_and_record_post_submit(page, platform=self.platform, job_id=job_id, db=self.db)
                    handle_post_apply_dialog(page)
                    if verify_res in ("APPLIED", "UNVERIFIED"):
                        if hasattr(self.guards, "record_application_success"):
                            self.guards.record_application_success(self.platform)
                    return _finish({"status": verify_res, "job_id": job_id})

            # 5. Advance to next step (click Next / Review button)
            next_btn = modal.locator(
                "button[data-easy-apply-next-button], "
                "button:has-text('Next'), "
                "button:has-text('Review')"
            ).first

            if next_btn.count() == 0:
                break

            SafeLocator(next_btn, selector_hint="Easy Apply Next button").safe_click()
            time.sleep(0.5)

        # If loop completed because step count reached MAX_STEPS
        if current_step >= MAX_STEPS:
            print(f"[STEP CAP EXCEEDED] Modal exceeded maximum {MAX_STEPS} steps! Halting.")
            self.db.update_job_status(
                platform=self.platform,
                job_id=job_id,
                status="FAILED",
                failure_reason=f"STEP_CAP_EXCEEDED: Modal exceeded maximum {MAX_STEPS} steps"
            )
            self.discard_modal(page)
            return _finish({"status": "FAILED", "reason": "STEP_CAP_EXCEEDED"})

        return _finish({"status": "IN_PROGRESS", "job_id": job_id})

