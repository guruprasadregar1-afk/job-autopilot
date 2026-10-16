import time
import re
from typing import List, Dict, Any, Optional
from src.policy import SafePage, SafeLocator
from src.matcher import JobMatcher, MatchResult
from src.guards import GuardsManager
from src.db import Database

class NaukriCollector:
    def __init__(self, db: Database, guards: GuardsManager, matcher: JobMatcher):
        self.db = db
        self.guards = guards
        self.matcher = matcher
        self.platform = "naukri"

    def run_phase8a_search(self, page, search_query: Dict[str, Any], max_jobs: int = 10, dry_run: bool = True) -> List[Dict[str, Any]]:
        """
        Phase 8a ONLY: Search, collect, dedupe, hard-filter, extract description, and match score.
        Strictly zero apply logic.
        """
        safe_page = SafePage(page)
        
        # Ensure session warm-up via homepage first
        safe_page.safe_goto("https://www.naukri.com/mnjuser/homepage", wait_until="domcontentloaded")
        self.guards.action_delay()

        keywords = search_query.get("keywords", "Senior Full Stack Developer")
        locations = search_query.get("locations", ["Bengaluru"])
        primary_loc = locations[0] if locations else "Bengaluru"

        # Naukri standard search URL
        url_kw = keywords.lower().replace(" ", "-")
        url_loc = primary_loc.lower().replace(" ", "-")
        search_url = f"https://www.naukri.com/{url_kw}-jobs-in-{url_loc}"

        print(f"\n[Naukri 8a] Navigating to search: {search_url}")
        safe_page.safe_goto(search_url, wait_until="load", timeout=30000)
        self.guards.action_delay()
        self.guards.check_page_safety(page, self.platform)

        # Collect job tuples
        tuples = page.locator("div.srp-jobtuple-wrapper, article.jobTuple, div.cust-job-tuple")
        tuple_count = tuples.count()
        print(f"[Naukri 8a] Found {tuple_count} job tuples on current page.")

        collected_jobs = []

        for i in range(min(max_jobs, tuple_count)):
            self.guards.check_pre_job_guards(self.platform)
            t = tuples.nth(i)

            # Extract Title & Link
            title_el = t.locator("a.title").first
            if title_el.count() == 0:
                continue

            title = title_el.inner_text().strip()
            job_url = title_el.get_attribute("href") or ""
            if not job_url:
                link_el = t.locator("a[href*='job-listings']").first
                if link_el.count() > 0:
                    job_url = link_el.get_attribute("href") or ""

            if not job_url:
                print(f"[SKIP] Job '{title}' has no valid URL. Skipping.")
                continue

            if job_url.startswith("/"):
                job_url = f"https://www.naukri.com{job_url}"
            
            # Extract Company & Location
            company = ""
            comp_el = t.locator("a.comp-name, span.comp-name").first
            if comp_el.count() > 0:
                company = comp_el.inner_text().strip()

            location = primary_loc
            loc_el = t.locator("span.loc-wrap span.loc").first
            if loc_el.count() > 0:
                location = loc_el.inner_text().strip()

            # Extract Job ID: Prefer data-job-id attribute, fallback to URL regex
            job_id = t.get_attribute("data-job-id") or ""
            if not job_id:
                job_id_match = re.search(r"(\d{10,14})(?:\?|$)", job_url)
                if job_id_match:
                    job_id = job_id_match.group(1)
            
            if not job_id:
                print(f"[SKIP] Naukri tuple {i+1} has no real job ID. Logged NO_JOB_ID. Skipping.")
                continue

            print(f"\n--- [Naukri 8a] Inspecting Job {i+1}: {title} @ {company} (ID: {job_id}) ---")

            # 1. Dedupe against DB (only final outcomes block: APPLIED, UNVERIFIED, EXTERNAL_SITE, SKIPPED, SKIPPED_BY_USER, FAILED >= 2)
            if self.db.is_job_blocked(self.platform, job_id):
                print(f"[DEDUPE] Job {job_id} already has a final blocking outcome in DB. Skipping.")
                continue

            # 2. Hard-filter in Python
            is_rejected, reject_reason = self.matcher.evaluate_hard_filters(title, company, location)
            if is_rejected:
                print(f"[HARD-REJECT] {reject_reason}")
                self.db.record_job(
                    platform=self.platform,
                    job_id=job_id,
                    title=title,
                    company=company,
                    location=location,
                    url=job_url,
                    status="SKIPPED",
                    failure_reason=reject_reason
                )
                continue

            # 3. Open job detail page
            safe_detail = safe_page.safe_new_page()
            try:
                safe_detail.safe_goto(job_url, wait_until="domcontentloaded", timeout=25000)
                self.guards.action_delay()
                self.guards.check_page_safety(safe_detail._page, self.platform)

                # Check Apply Button Classification
                comp_site_btn = safe_detail.locator("button.company-site-button, button:has-text('Apply on company site')")
                if comp_site_btn.count() > 0:
                    print(f"[EXTERNAL SITE] Job requires external apply. Logging as EXTERNAL_SITE.")
                    self.db.record_job(
                        platform=self.platform,
                        job_id=job_id,
                        title=title,
                        company=company,
                        location=location,
                        url=job_url,
                        status="EXTERNAL_SITE",
                        failure_reason="External site redirect - not automated"
                    )
                    safe_detail.close()
                    continue

                plain_apply_btn = safe_detail.locator("button.apply-button:not(.company-site-button), button:text-is('Apply'), #apply-button")
                if plain_apply_btn.count() == 0:
                    print(f"[SKIP] Plain Apply button not found (non-plain or absent apply control). Skipping.")
                    self.db.record_job(
                        platform=self.platform,
                        job_id=job_id,
                        title=title,
                        company=company,
                        location=location,
                        url=job_url,
                        status="SKIPPED",
                        failure_reason="Apply control is not plain Apply"
                    )
                    safe_detail.close()
                    continue

                # 4. Extract Description
                description = ""
                desc_el = safe_detail.locator("div.job-desc-wrap, section.styles_job-desc-container__txpYf")
                if desc_el.count() > 0:
                    description = desc_el.first.inner_text().strip()

                # 5. Claude Matcher Fit Evaluation
                match_res: MatchResult = self.matcher.evaluate_fit(title, company, location, description)
                print(f"[MATCH RESULT] Score: {match_res.score} | Apply: {match_res.should_apply} | Reason: {match_res.reason}")

                status = "FOUND" if match_res.should_apply else "SKIPPED"
                self.db.record_job(
                    platform=self.platform,
                    job_id=job_id,
                    title=title,
                    company=company,
                    location=location,
                    url=job_url,
                    description=description[:1000],
                    match_score=match_res.score,
                    match_reason=match_res.reason,
                    status=status
                )

                job_data = {
                    "platform": self.platform,
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "location": location,
                    "match_score": match_res.score,
                    "should_apply": match_res.should_apply,
                    "reason": match_res.reason
                }
                collected_jobs.append(job_data)

                # ZERO APPLY LOGIC in Phase 8a
                if dry_run:
                    print(f"[DRY-RUN 8a] Match evaluation complete. No apply button clicked.")

            finally:
                try:
                    safe_detail.close()
                except Exception:
                    pass

        return collected_jobs
