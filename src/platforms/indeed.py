import time
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlencode

from src.policy import SafePage, SafeLocator, BrowserClosedCleanStop, is_browser_closed_error
from src.matcher import JobMatcher, MatchResult
from src.guards import GuardsManager, SafetyStopError, AttemptsLimitReachedError
from src.db import Database
from src.answerer import FormAnswerer

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _safe_count(loc) -> int:
    """Safely extracts integer count from Playwright locator or mock."""
    try:
        if hasattr(loc, "count"):
            cnt = loc.count()
            if type(cnt) is int:
                return cnt
    except Exception:
        pass
    return 0


def _is_clean_str(val: Any) -> bool:
    return type(val) is str and bool(val.strip()) and not val.strip().startswith("<MagicMock")


class IndeedCollector:
    """
    Collector for Indeed (in.indeed.com / ae.indeed.com / www.indeed.com).
    Searches for jobs with &iafilter=1 ('Easily apply'), extracts job cards,
    evaluates match scores, and dispatches to IndeedApplicant.
    """
    def __init__(self, db: Database, guards: GuardsManager, matcher: JobMatcher, browser_manager: Optional[Any] = None):
        self.db = db
        self.guards = guards
        self.matcher = matcher
        self.platform = "indeed"
        self.browser_manager = browser_manager

    def build_search_url(self, search_query: Dict[str, Any]) -> str:
        """
        Builds the search URL with &iafilter=1 ('Easily apply' jobs only).
        Selects in.indeed.com for India, ae.indeed.com for Dubai/UAE, or custom domain.
        """
        keywords = search_query.get("keywords", "Senior Full Stack Developer")
        location = search_query.get("location", "India")
        domain = search_query.get("domain", "")

        if not domain:
            loc_lower = location.lower()
            if any(k in loc_lower for k in ("dubai", "uae", "united arab emirates", "abu dhabi", "sharjah")):
                domain = "ae.indeed.com"
            else:
                domain = "in.indeed.com"

        params = {
            "q": keywords,
            "l": location,
            "filter": "0",
        }
        if search_query.get("iafilter", True):
            params["iafilter"] = "1"

        return f"https://{domain}/jobs?{urlencode(params)}"

    def extract_job_card_data(self, card: Any, default_domain: str = "in.indeed.com") -> Optional[Dict[str, Any]]:
        """
        Extracts job_id (data-jk), title, company, location, and easily-apply status from card.
        """
        try:
            # 1. Job ID (data-jk)
            job_id = ""
            if hasattr(card, "get_attribute"):
                job_id = card.get_attribute("data-jk") or ""
            if not job_id:
                link = card.locator("a[data-jk], a[href*='jk='], a.jcs-JobTitle").first
                if _safe_count(link) > 0:
                    job_id = link.get_attribute("data-jk") or ""
                    if not job_id:
                        href = link.get_attribute("href") or ""
                        m = re.search(r"[?&]jk=([a-zA-Z0-9]+)", href)
                        if m:
                            job_id = m.group(1)

            if not job_id:
                return None

            # 2. Title
            title = ""
            title_loc = card.locator("h2.jobTitle span, a.jcs-JobTitle span, a[data-jk] span, h2 a").first
            if _safe_count(title_loc) > 0:
                title = (title_loc.inner_text() or "").strip()
            if not title:
                title = "Senior Full Stack Developer"

            # 3. Company
            company = ""
            comp_loc = card.locator("[data-testid='company-name'], span.companyName, span.css-63koeb, span.css-92r8pb").first
            if _safe_count(comp_loc) > 0:
                company = (comp_loc.inner_text() or "").strip()

            # 4. Location
            location = ""
            loc_elem = card.locator("[data-testid='text-location'], div.companyLocation, div.css-1p0sjhy").first
            if _safe_count(loc_elem) > 0:
                location = (loc_elem.inner_text() or "").strip()

            # 5. Easily Apply Check
            apply_badge = card.locator(
                "[data-testid='indeedApply'], "
                "span:has-text('Easily apply'), "
                "div:has-text('Easily apply'), "
                "span[data-testid='indeedApply-badge']"
            ).first
            is_easily_apply = (_safe_count(apply_badge) > 0)

            # URL
            url = f"https://{default_domain}/viewjob?jk={job_id}"

            return {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "is_easily_apply": is_easily_apply,
                "url": url,
            }
        except Exception as e:
            print(f"[Indeed Extract Warning] Failed parsing card: {e}")
            return None

    def run_search_and_apply(
        self,
        page: Any,
        search_query: Dict[str, Any],
        applicant: Optional[Any] = None,
        max_jobs: int = 10,
        is_rehearsal: bool = False,
        dry_run: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Executes search on Indeed, extracts job cards, evaluates matching, and applies.
        """
        safe_page = SafePage(page)
        search_url = self.build_search_url(search_query)
        print(f"\n[Indeed Search] Navigating to: {search_url}")

        try:
            safe_page.safe_goto(search_url, wait_until="domcontentloaded", timeout=30000)
            self.guards.action_delay()
            self.guards.check_page_safety(page, self.platform)
        except Exception as e:
            if is_browser_closed_error(e):
                raise
            print(f"[Indeed Search Error] Failed to load search page: {e}")
            return []

        # Find job cards
        card_locators = page.locator("div.job_seen_beacon, div[data-testid='slider_item'], div.cardOutline, div[data-jk]")
        card_count = _safe_count(card_locators)
        print(f"[Indeed Search] Found {card_count} job cards on current page.")

        domain = "ae.indeed.com" if "ae.indeed.com" in search_url else "in.indeed.com"
        processed = 0

        for i in range(min(card_count, max_jobs)):
            card = card_locators.nth(i)
            data = self.extract_job_card_data(card, default_domain=domain)
            if not data:
                continue

            job_id = data["job_id"]
            title = data["title"]
            company = data["company"]
            location = data["location"]
            is_easily_apply = data["is_easily_apply"]
            url = data["url"]

            # Dedupe check
            if not self.db.is_job_eligible(self.platform, job_id):
                print(f"[DEDUPE] Job {job_id} already in DB and not eligible. Skipping.")
                continue

            # Check external site apply
            if not is_easily_apply:
                print(f"[EXTERNAL SITE] Job {job_id} ('{title}' @ '{company}') redirects to external ATS. Skipping.")
                self.db.record_job(
                    platform=self.platform,
                    job_id=job_id,
                    title=title,
                    company=company,
                    location=location,
                    status="EXTERNAL_SITE",
                    failure_reason="EXTERNAL_SITE: Does not offer Indeed Apply (external ATS redirect)"
                )
                continue

            # Same company check (7-day rule)
            if hasattr(self.guards, "can_apply_to_company"):
                can_apply_comp, comp_reason = self.guards.can_apply_to_company(company, days=7)
                if not can_apply_comp:
                    print(f"[SAME COMPANY GUARD] Skipping job {job_id} at '{company}': {comp_reason}")
                    self.db.record_job(
                        platform=self.platform,
                        job_id=job_id,
                        title=title,
                        company=company,
                        location=location,
                        status="SKIPPED",
                        failure_reason="SAME_COMPANY_RECENTLY_APPLIED"
                    )
                    continue

            # Hard filter check (title exclusions / company blacklist)
            match_res = self.matcher.evaluate_match(title=title, description="", company=company)
            if match_res.score < self.matcher.threshold:
                print(f"[FILTER] Job '{title}' @ '{company}' score {match_res.score} below threshold {self.matcher.threshold}. Skipping.")
                self.db.record_job(
                    platform=self.platform,
                    job_id=job_id,
                    title=title,
                    company=company,
                    location=location,
                    status="SKIPPED",
                    failure_reason=f"Score {match_res.score} < {self.matcher.threshold}"
                )
                continue

            # Store in DB as FOUND
            self.db.record_job(
                platform=self.platform,
                job_id=job_id,
                title=title,
                company=company,
                location=location,
                match_score=match_res.score,
                match_reason=match_res.reason,
                status="FOUND"
            )

            # Apply Flow
            if not dry_run and applicant:
                if self.guards.session_attempts_count >= self.guards.max_attempts:
                    print(f"[ATTEMPTS LIMIT] Session attempts cap reached ({self.guards.session_attempts_count}/{self.guards.max_attempts}). Stopping.")
                    break

                self.guards.check_pre_job_guards(self.platform)
                print(f"\n>>> Applying to Indeed Job: '{title}' @ '{company}' (ID: {job_id})")
                res = applicant.process_application(
                    page=page,
                    job_id=job_id,
                    title=title,
                    company=company,
                    url=url,
                    match_score=match_res.score,
                    match_reason=match_res.reason
                )
                processed += 1
                self.guards.job_delay()

        return []

    def process_eligible_found_jobs(
        self,
        page: Any,
        applicant: Any,
        limit: int = 10,
        is_rehearsal: bool = False,
        target_job_id: Optional[str] = None
    ) -> None:
        """Processes existing FOUND jobs from DB for Indeed."""
        jobs = self.db.get_eligible_found_jobs(self.platform, limit=limit)
        if target_job_id:
            jobs = [j for j in jobs if j.get("job_id") == target_job_id]

        print(f"\n[Indeed Pipeline] Found {len(jobs)} eligible FOUND jobs in database to process first.")
        for j in jobs:
            job_id = j.get("job_id")
            title = j.get("title", "")
            company = j.get("company", "")
            url = j.get("url") or f"https://in.indeed.com/viewjob?jk={job_id}"

            if self.guards.session_attempts_count >= self.guards.max_attempts:
                print(f"[ATTEMPTS LIMIT] Session cap reached. Halting FOUND jobs.")
                break

            self.guards.check_pre_job_guards(self.platform)
            applicant.process_application(
                page=page,
                job_id=job_id,
                title=title,
                company=company,
                url=url
            )
            self.guards.job_delay()


class IndeedApplicant:
    """
    Indeed Application Engine.
    Navigates to Indeed job, opens SmartApply modal or iframe, answers questions via FormAnswerer,
    enforces Consent Guard, and handles Review step with typed YES confirmation.
    """
    def __init__(
        self,
        db: Database,
        guards: GuardsManager,
        answerer: Optional[Any] = None,
        profile_path: Optional[Path] = None,
        review_mode: bool = False,
        is_rehearsal: bool = False
    ):
        from src.policy import OBSERVE_ONLY
        self.db = db
        self.guards = guards
        self.answerer = answerer or FormAnswerer()
        self.platform = "indeed"
        self.review_mode = review_mode
        self.is_rehearsal = is_rehearsal
        self.observe_only = OBSERVE_ONLY or is_rehearsal
        self.current_modal_step = 1
        self.fields_detail: List[Dict[str, str]] = []
        self.answers_filled: Dict[str, Any] = {}

    def locate_apply_button(self, page: Any) -> Tuple[Optional[Any], str]:
        """Locates the Apply now / Easily apply button on Indeed viewjob page."""
        btn_loc = page.locator(
            "button#indeedApplyButton, "
            "button[data-testid='indeedApply'], "
            "div#indeedApplyButton button, "
            "button:has-text('Apply now'), "
            "button:has-text('Easily apply')"
        ).first
        if _safe_count(btn_loc) > 0:
            txt = (btn_loc.inner_text() or "").strip()
            return btn_loc, txt or "Apply now"

        # Check if only external apply exists
        ext_btn = page.locator("a:has-text('Apply on company site'), button:has-text('Apply on company site')").first
        if _safe_count(ext_btn) > 0:
            return None, "EXTERNAL_SITE"

        return None, ""

    def locate_application_container(self, page: Any) -> Optional[Any]:
        """
        Locates the SmartApply application container: either an embedded iframe or dialog modal.
        """
        # 1. Embedded iframe
        iframe_loc = page.locator("iframe[src*='smartapply'], iframe#vjs-container-iframe, iframe[title*='application']").first
        if _safe_count(iframe_loc) > 0:
            try:
                frame = page.frame_locator("iframe[src*='smartapply'], iframe#vjs-container-iframe, iframe[title*='application']").first
                return frame
            except Exception:
                pass

        # 2. In-DOM dialog or modal
        modal_loc = page.locator("div[role='dialog'], div.ia-BasePage, div[data-testid='smartApply-modal']").first
        if _safe_count(modal_loc) > 0:
            return modal_loc

        return page

    def is_review_step(self, container: Any) -> bool:
        """Determines if the current step is the final Review step."""
        heading_loc = container.locator("h1, h2, h3, [role='heading']").first
        if _safe_count(heading_loc) > 0:
            txt = (heading_loc.inner_text() or "").lower()
            if "review" in txt:
                return True

        submit_btn = container.locator("button:has-text('Submit your application'), button:has-text('Apply'), button[aria-label*='Submit']").first
        return _safe_count(submit_btn) > 0

    def answer_screening_fields(self, container: Any) -> Tuple[bool, Optional[str]]:
        """
        Answers screening questions in the active container using FormAnswerer.
        Strictly enforces Consent Guard: unapproved consent questions return (False, label).
        """
        try:
            # Check text inputs
            inputs = container.locator("input[type='text'], input[type='number'], input:not([type]), textarea")
            for i in range(_safe_count(inputs)):
                inp = inputs.nth(i)
                label = ""
                # Find associated label
                inp_id = inp.get_attribute("id") if hasattr(inp, "get_attribute") else ""
                if inp_id:
                    lbl_loc = container.locator(f"label[for='{inp_id}']").first
                    if _safe_count(lbl_loc) > 0:
                        label = (lbl_loc.inner_text() or "").strip()
                if not label:
                    label = (inp.get_attribute("aria-label") or inp.get_attribute("placeholder") or "").strip()

                if not label:
                    continue

                if self.answerer.is_consent_question(label):
                    ans = self.answerer.find_direct_answer(label, field_type="text")
                    if not ans:
                        return False, f"CONSENT_GUARD: Unapproved consent question: '{label}'"

                ans = self.answerer.answer_question(label, field_type="text")
                if ans == "UNKNOWN":
                    # If required field, return false
                    req = (inp.get_attribute("required") is not None) or ("*" in label)
                    if req:
                        return False, label
                else:
                    SafeLocator(inp, selector_hint=f"Indeed input {label}").safe_fill(ans)
                    self.answers_filled[label] = ans
                    self.fields_detail.append({
                        "step": self.current_modal_step,
                        "label": label,
                        "value": ans,
                        "source": "answers.yaml"
                    })

            # Check radio buttons
            radios = container.locator("fieldset")
            for i in range(_safe_count(radios)):
                fset = radios.nth(i)
                legend = fset.locator("legend").first
                lbl = (legend.inner_text() or "").strip() if _safe_count(legend) > 0 else ""
                if not lbl:
                    continue

                if self.answerer.is_consent_question(lbl):
                    ans = self.answerer.find_direct_answer(lbl, field_type="radio")
                    if not ans:
                        return False, f"CONSENT_GUARD: Unapproved consent question: '{lbl}'"

                ans = self.answerer.answer_question(lbl, field_type="radio", options=["Yes", "No"])
                if ans and ans != "UNKNOWN":
                    opt_radio = fset.locator(f"input[type='radio'][value='{ans}'], label:has-text('{ans}')").first
                    if _safe_count(opt_radio) > 0:
                        SafeLocator(opt_radio, selector_hint=f"Indeed radio {lbl} -> {ans}").safe_click()
                        self.answers_filled[lbl] = ans
                        self.fields_detail.append({
                            "step": self.current_modal_step,
                            "label": lbl,
                            "value": ans,
                            "source": "answers.yaml"
                        })
                elif ans == "UNKNOWN":
                    req = ("*" in lbl)
                    if req:
                        return False, lbl

            return True, None
        except Exception as e:
            print(f"[Indeed Answer Fields Warning] {e}")
            return True, None

    def generate_approval_sheet(
        self,
        job_id: str,
        title: str,
        company: str,
        location: str,
        url: str,
        match_score: Optional[int] = None,
        match_reason: str = "",
        steps_handled: int = 1
    ) -> str:
        """Generates clear, deduplicated terminal approval sheet."""
        lines = [
            "\n" + "=" * 70,
            "             INDEED APPLICATION APPROVAL SHEET",
            "=" * 70,
            f"Job Title           : {title}",
            f"Company             : {company}",
            f"Location            : {location or 'India/Dubai'}",
            f"URL                 : {url}",
            f"Match Score         : {match_score if match_score is not None else 'N/A'}",
            f"Match Reason        : {match_reason or 'Profile matches skills'}",
            f"Steps Handled       : {steps_handled}",
            "",
            "Fields and Values to be Submitted:",
        ]
        if self.fields_detail:
            seen = set()
            for f in self.fields_detail:
                lbl = f.get("label", "")
                if lbl not in seen:
                    seen.add(lbl)
                    lines.append(f"  - [Step {f.get('step', 1)}] [{f.get('source', 'answers.yaml')}] {lbl}: {f.get('value')}")
        else:
            lines.append("  (Standard profile resume applied; no custom screening answers)")

        lines.extend([
            "",
            "=" * 70,
            "AWAITING YOUR CONFIRMATION" if (self.review_mode and not self.observe_only) else "REHEARSAL MODE (SUBMIT BLOCKED)",
            "=" * 70 + "\n"
        ])
        return "\n".join(lines)

    def process_application(
        self,
        page: Any,
        job_id: str,
        title: str,
        company: str,
        url: str = "",
        match_score: Optional[int] = None,
        match_reason: str = ""
    ) -> Dict[str, Any]:
        """
        Executes Indeed application flow with max 8 steps cap,
        Screening answers, Consent Guard, Review verification, and typed YES prompt.
        """
        self.answers_filled = {}
        self.fields_detail = []
        current_step = 0

        def _finish(res: Dict[str, Any]) -> Dict[str, Any]:
            st = res.get("status", "FAILED")
            reason = res.get("reason", "")
            print(f"[Indeed Status] Job {job_id}: {st} | Reason: {reason}")
            if hasattr(self.guards, "record_attempt_outcome"):
                self.guards.record_attempt_outcome(st, job_id=job_id)
            if st == "NEEDS_INPUT" and hasattr(self.guards, "record_needs_input"):
                self.guards.record_needs_input(job_id, res.get("question", "Unknown"))
            elif st in ("FAILED", "STEP_FAILED", "SKIPPED") and hasattr(self.guards, "record_failure_reason"):
                self.guards.record_failure_reason(job_id, reason or "Failure")
            return res

        # 1. Same Company Guard (7 days)
        if hasattr(self.guards, "can_apply_to_company"):
            can_res = self.guards.can_apply_to_company(company, days=7)
            can_apply = can_res[0] if isinstance(can_res, tuple) else (can_res if isinstance(can_res, bool) else True)
            if not can_apply:
                reason = "SAME_COMPANY_RECENTLY_APPLIED"
                print(f"[SAME COMPANY GUARD] Skipping Indeed application for '{title}' @ '{company}': already applied within 7 days.")
                self.db.update_job_status(platform=self.platform, job_id=job_id, status="SKIPPED", failure_reason=reason)
                return _finish({"status": "SKIPPED", "reason": reason, "job_id": job_id})

        # 2. Navigate to view job page if not already there
        target_url = url or f"https://in.indeed.com/viewjob?jk={job_id}"
        safe_page = SafePage(page)
        try:
            safe_page.safe_goto(target_url, wait_until="domcontentloaded", timeout=25000)
            self.guards.action_delay()
            self.guards.check_page_safety(page, self.platform)
        except Exception as e:
            if is_browser_closed_error(e):
                raise
            return _finish({"status": "STEP_FAILED", "reason": f"Failed loading job view: {e}", "job_id": job_id})

        # 3. Locate Apply Button
        apply_btn, btn_desc = self.locate_apply_button(page)
        if btn_desc == "EXTERNAL_SITE":
            self.db.update_job_status(platform=self.platform, job_id=job_id, status="EXTERNAL_SITE", failure_reason="EXTERNAL_SITE")
            return _finish({"status": "EXTERNAL_SITE", "reason": "External ATS redirect", "job_id": job_id})

        if apply_btn is None:
            self.db.update_job_status(platform=self.platform, job_id=job_id, status="FAILED", failure_reason="APPLY_BUTTON_NOT_FOUND")
            return _finish({"status": "FAILED", "reason": "APPLY_BUTTON_NOT_FOUND", "job_id": job_id})

        # Record form opened
        if hasattr(self.guards, "record_form_opened"):
            self.guards.record_form_opened(platform=self.platform, job_id=job_id)

        # 4. Click Apply Button
        SafeLocator(apply_btn, selector_hint="Indeed Apply Button").safe_click()
        time.sleep(2)

        container = self.locate_application_container(page)
        MAX_STEPS = 8

        while current_step < MAX_STEPS:
            current_step += 1
            self.current_modal_step = current_step

            # Check if Review step reached
            if self.is_review_step(container):
                sheet = self.generate_approval_sheet(
                    job_id=job_id,
                    title=title,
                    company=company,
                    location="",
                    url=target_url,
                    match_score=match_score,
                    match_reason=match_reason,
                    steps_handled=current_step
                )
                print(sheet)

                if self.observe_only or self.is_rehearsal:
                    print(f"[REHEARSAL] Review step reached for Indeed job {job_id}. Submit strictly blocked.")
                    self.db.update_job_status(platform=self.platform, job_id=job_id, status="OBSERVED_REVIEW")
                    return _finish({"status": "OBSERVED_REVIEW", "job_id": job_id, "reason": "Reached Review step in rehearsal"})

                if not self.review_mode:
                    print(f"[SAFETY BLOCK] Live submit requires --review mode enabled. Halting.")
                    return _finish({"status": "BLOCKED_REQUIRES_REVIEW", "job_id": job_id})

                # Terminal prompt for typed YES
                try:
                    user_confirm = input("Type 'YES' to confirm and submit Indeed application: ").strip()
                except (EOFError, KeyboardInterrupt):
                    user_confirm = ""

                if user_confirm != "YES":
                    print(f"[SKIPPED] Submit cancelled by user ('{user_confirm}' != 'YES').")
                    return _finish({"status": "SKIPPED_BY_USER", "job_id": job_id, "reason": "User cancelled at prompt"})

                # Click Submit
                submit_btn = container.locator("button:has-text('Submit your application'), button:has-text('Apply')").first
                if _safe_count(submit_btn) > 0:
                    SafeLocator(submit_btn, selector_hint="Indeed Submit button").safe_click()
                    time.sleep(3)
                    from src.policy import verify_and_record_post_submit
                    res_status = verify_and_record_post_submit(page, platform=self.platform, job_id=job_id, db=self.db)
                    if hasattr(self.guards, "record_application_success"):
                        self.guards.record_application_success(
                            platform=self.platform,
                            job_id=job_id,
                            title=title,
                            company=company,
                            url=target_url
                        )
                    return _finish({"status": res_status, "job_id": job_id})

            # Answer screening questions
            ok, pending_q = self.answer_screening_fields(container)
            if not ok:
                reason = f"NEEDS_INPUT: Unanswered screening question or consent guard: '{pending_q}'"
                print(f"[SAFETY BLOCK] {reason}")
                self.db.update_job_status(platform=self.platform, job_id=job_id, status="NEEDS_INPUT", pending_question=pending_q or "")
                return _finish({"status": "NEEDS_INPUT", "question": pending_q, "reason": reason, "job_id": job_id})

            # Click Continue / Next to advance
            cont_btn = container.locator("button:has-text('Continue'), button:has-text('Next'), button[aria-label*='Continue']").first
            if _safe_count(cont_btn) > 0:
                SafeLocator(cont_btn, selector_hint="Indeed Continue button").safe_click()
                time.sleep(1.5)
            else:
                break

        return _finish({"status": "IN_PROGRESS", "job_id": job_id})
