import time
import random
import datetime
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Set, Tuple
import yaml

class SafetyStopError(Exception):
    """Raised when safety limits (CAPTCHA, login wall, account warning, 3 failures) are triggered."""
    pass

class DailyCapReachedError(Exception):
    """Raised when daily application cap for a platform is reached."""
    pass

class OutsideWorkingHoursError(Exception):
    """Raised when current time is outside configured working hours window."""
    pass

class SessionLimitExceededError(Exception):
    """Raised when max continuous session minutes exceeded."""
    pass

class AttemptsLimitReachedError(SafetyStopError):
    """Raised when session Easy Apply opened attempts limit is reached."""
    pass

class ResumeMismatchHaltError(SafetyStopError):
    """Raised when configured resume is missing, pending confirmation, or fails strict verification against selected DOM radio."""
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"

class GuardsManager:
    def __init__(self, db, config_path: Optional[Path] = None, max_apply: Optional[int] = None, max_attempts: Optional[int] = 10):
        self.db = db
        self.config_path = config_path or CONFIG_PATH
        self.settings = self._load_settings()
        self.consecutive_failures = 0
        self.session_start_time = datetime.datetime.now()
        self.max_apply = max_apply
        self.session_applied_count = 0

        # Session attempts cap tracking
        self.session_attempts_count = 0
        self.attempted_job_ids_in_run: Set[str] = set()
        self.attempts_summary: Dict[str, int] = {
            "opened": 0,
            "applied": 0,
            "needs_input": 0,
            "failed": 0,
            "skipped": 0,
            "reviewed": 0
        }
        self.needs_input_items: List[Dict[str, str]] = []
        self.failure_items: List[Dict[str, str]] = []
        self.review_reached_items: List[Dict[str, str]] = []
        self.submitted_jobs_in_run: List[Dict[str, str]] = []
        self.consecutive_modal_not_detected: int = 0
        self.modal_not_detected_snapshots: List[str] = []
        self.set_max_attempts(max_attempts if max_attempts is not None else 10)

    def is_job_attempted_in_run(self, job_id: str) -> bool:
        """Returns True if job_id was already attempted in the current execution run."""
        return str(job_id) in self.attempted_job_ids_in_run

    def mark_job_attempted_in_run(self, job_id: str) -> None:
        """Marks job_id as attempted in the current execution run."""
        self.attempted_job_ids_in_run.add(str(job_id))

    def set_max_attempts(self, max_attempts: Optional[int]) -> None:
        """
        Sets max_attempts limit for current session.
        Can only lower the hard limit (default hard limit 50), never exceed it.
        """
        hard_limit = self.settings.get("caps", {}).get("max_attempts_hard_limit", 50)
        target = 10 if max_attempts is None else max_attempts
        self.max_attempts = min(hard_limit, target)

    def record_form_opened(self, platform: str = "linkedin", job_id: str = "") -> None:
        """Called whenever an Easy Apply form is opened."""
        self.session_attempts_count += 1
        self.attempts_summary["opened"] += 1
        self.consecutive_modal_not_detected = 0
        if hasattr(self.db, "record_job_attempt"):
            self.db.record_job_attempt(platform, job_id)

    def record_needs_input(self, job_id: str, question: str) -> None:
        """Records a question causing NEEDS_INPUT."""
        self.needs_input_items.append({"job_id": str(job_id), "question": str(question)})

    def record_failure_reason(self, job_id: str, reason: str) -> None:
        """Records a job failure reason for the end-of-run summary."""
        self.failure_items.append({"job_id": str(job_id), "reason": str(reason)})

    def record_review_reached(self, job_id: str, follow_company_state: str) -> None:
        """Records reaching Review step and follow-company checkbox state."""
        self.review_reached_items.append({"job_id": str(job_id), "follow_company_state": str(follow_company_state)})

    def record_attempt_outcome(self, outcome: str, job_id: str = "", snapshot_path: Optional[str] = None) -> None:
        """
        Categorizes attempt outcome into applied, needs_input, failed, or skipped.
        Halts the run if 3 consecutive MODAL_NOT_DETECTED outcomes are encountered.
        """
        norm = str(outcome).upper()
        if norm in ("APPLIED", "UNVERIFIED"):
            self.attempts_summary["applied"] += 1
            self.consecutive_modal_not_detected = 0
        elif norm == "NEEDS_INPUT":
            self.attempts_summary["needs_input"] += 1
            self.consecutive_modal_not_detected = 0
        elif norm in ("FAILED", "STUCK_STEP", "STEP_CAP_EXCEEDED", "RESUME_NOT_FOUND", "RESUME_MISMATCH", "STEP_FAILED", "MODAL_NOT_DETECTED"):
            self.attempts_summary["failed"] += 1
            if norm == "MODAL_NOT_DETECTED":
                self.consecutive_modal_not_detected += 1
                snap = snapshot_path or f"docs/snapshots/rehearsal_{job_id}_modal_not_detected.html"
                self.modal_not_detected_snapshots.append(snap)
                if self.consecutive_modal_not_detected >= 3:
                    snaps = "\n".join(f"  - {s}" for s in self.modal_not_detected_snapshots[-3:])
                    err_msg = (
                        f"SAFETY HALT: 3 consecutive MODAL_NOT_DETECTED outcomes encountered. Halting run.\n"
                        f"Saved snapshot paths:\n{snaps}"
                    )
                    print(f"\n[SAFETY HALT] {err_msg}\n")
                    raise SafetyStopError(err_msg)
            else:
                self.consecutive_modal_not_detected = 0
        elif norm in ("OBSERVED_REVIEW", "REVIEW_REACHED"):
            self.attempts_summary["reviewed"] = self.attempts_summary.get("reviewed", 0) + 1
            self.consecutive_modal_not_detected = 0
        else:
            self.attempts_summary["skipped"] += 1
            self.consecutive_modal_not_detected = 0

    def check_attempts_guard(self) -> None:
        """Raises AttemptsLimitReachedError if session attempts cap is reached."""
        if self.session_attempts_count >= self.max_attempts:
            raise AttemptsLimitReachedError(
                f"Session attempts limit reached ({self.session_attempts_count}/{self.max_attempts} Easy Apply forms opened). Stopping run cleanly."
            )

    def print_attempts_summary(self) -> None:
        print("\n" + "="*60)
        print(f"SESSION ATTEMPTS SUMMARY (Cap: {self.max_attempts})")
        print(f"  - Opened      : {self.attempts_summary['opened']}")
        if self.attempts_summary.get("reviewed", 0) > 0 or self.settings.get("observe_only", True):
            print(f"  - Reviewed    : {self.attempts_summary.get('reviewed', 0)}")
        print(f"  - Applied     : {self.attempts_summary['applied']}")
        print(f"  - Needs Input : {self.attempts_summary['needs_input']}")
        print(f"  - Failed      : {self.attempts_summary['failed']}")
        print(f"  - Skipped     : {self.attempts_summary['skipped']}")

        print("\nNEEDS_INPUT Questions:")
        if self.needs_input_items:
            for item in self.needs_input_items:
                print(f"  - [Job ID: {item['job_id']}] Question: {item['question']}")
        else:
            print("  (None)")

        print("\nFailure Reasons:")
        if self.failure_items:
            for item in self.failure_items:
                print(f"  - [Job ID: {item['job_id']}] Reason: {item['reason']}")
        else:
            print("  (None)")

        print("\nFollow-Company State per Review Reached:")
        if self.review_reached_items:
            for item in self.review_reached_items:
                print(f"  - [Job ID: {item['job_id']}] Follow Company: {item['follow_company_state']}")
        else:
            print("  (None)")

        print("\nJobs Submitted in this Run:")
        if self.submitted_jobs_in_run:
            for job in self.submitted_jobs_in_run:
                u = job.get("url") or (f"https://www.linkedin.com/jobs/view/{job.get('job_id')}/" if job.get("job_id") else "")
                print(f"  - {job.get('title')} @ {job.get('company')} ({u})")
        else:
            print("  (None)")

        print("="*60 + "\n")

    def can_apply_to_company(self, company: str, days: int = 7) -> Tuple[bool, str]:
        """
        Enforces at most one application per company per `days` days (default 7).
        If already applied within the period, returns (False, 'SAME_COMPANY_RECENTLY_APPLIED').
        """
        if hasattr(self.db, "has_applied_to_company_recently"):
            has_applied, prev_id = self.db.has_applied_to_company_recently(company, days=days)
            if has_applied:
                return False, f"SAME_COMPANY_RECENTLY_APPLIED (Already applied to '{company}' in job {prev_id} within {days} days)"
        return True, ""

    def set_max_apply(self, max_apply: Optional[int]) -> None:
        """Sets max_apply limit for current session. Can only lower the daily cap."""
        self.max_apply = max_apply

    def record_application_success(
        self,
        platform: str = "",
        job_id: str = "",
        title: str = "",
        company: str = "",
        url: str = ""
    ) -> None:
        """Increments session applied count, tracks submitted job details, and resets consecutive failure counter."""
        self.session_applied_count += 1
        self.record_success()
        u = url or (f"https://www.linkedin.com/jobs/view/{job_id}/" if platform == "linkedin" and job_id else "")
        self.submitted_jobs_in_run.append({
            "job_id": str(job_id),
            "title": str(title),
            "company": str(company),
            "url": u,
            "platform": platform
        })

    def _load_settings(self) -> Dict[str, Any]:
        path = self.config_path
        if not path.exists():
            example_path = path.parent / (path.stem + ".example.yaml")
            if example_path.exists():
                path = example_path
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def check_pre_job_guards(self, platform: str) -> None:
        """
        Enforces working hours, session limits, consecutive failures, and daily caps
        BEFORE every job.
        """
        # 1. Check Consecutive Failures
        max_failures = self.settings.get("safety", {}).get("max_consecutive_failures", 3)
        if self.consecutive_failures >= max_failures:
            raise SafetyStopError(
                f"SAFETY STOP: {self.consecutive_failures} consecutive unexpected failures occurred. Halting run immediately."
            )

        # 2. Check Session Duration
        max_session = self.settings.get("timing", {}).get("max_session_minutes", 120)
        elapsed_minutes = (datetime.datetime.now() - self.session_start_time).total_seconds() / 60.0
        if elapsed_minutes >= max_session:
            raise SessionLimitExceededError(
                f"Session duration limit reached ({elapsed_minutes:.1f} / {max_session} minutes). Stopping run."
            )

        # 3. Check Working Hours Window
        timing_cfg = self.settings.get("timing", {})
        hours_cfg = timing_cfg.get("working_hours", {})
        if hours_cfg.get("enabled", True):
            now = datetime.datetime.now()
            start_parts = [int(p) for p in hours_cfg.get("start", "09:00").split(":")]
            end_parts = [int(p) for p in hours_cfg.get("end", "18:00").split(":")]
            start_time = now.replace(hour=start_parts[0], minute=start_parts[1], second=0, microsecond=0)
            end_time = now.replace(hour=end_parts[0], minute=end_parts[1], second=0, microsecond=0)
            if not (start_time <= now <= end_time):
                raise OutsideWorkingHoursError(
                    f"Current time ({now.strftime('%H:%M')}) is outside allowed working hours "
                    f"({hours_cfg.get('start')} - {hours_cfg.get('end')}). Halting run."
                )

        # 4. Check Daily Cap & Session Max Apply
        caps_cfg = self.settings.get("caps", {})
        if platform == "linkedin":
            configured_cap = caps_cfg.get("linkedin_daily_cap", 25)
        elif platform == "naukri":
            configured_cap = caps_cfg.get("naukri_daily_cap", 40)
        else:
            configured_cap = 25

        # --max-apply can only lower the cap, never raise it
        if self.max_apply is not None:
            effective_cap = min(configured_cap, self.max_apply)
        else:
            effective_cap = configured_cap

        applied_today = self.db.get_applied_count_today(platform)
        if applied_today >= effective_cap:
            raise DailyCapReachedError(
                f"Daily cap reached for {platform}: applied {applied_today}/{effective_cap} jobs today. Halting {platform} applications."
            )

        if self.max_apply is not None and self.session_applied_count >= self.max_apply:
            raise DailyCapReachedError(
                f"Session application limit reached (--max-apply {self.max_apply}). Halting applications."
            )

        # 5. Check DB Daily Attempts Cap (attempts_per_day across all runs)
        configured_attempts_day = caps_cfg.get("attempts_per_day", 25)
        if hasattr(self.db, "get_attempts_count_today"):
            db_attempts_today = self.db.get_attempts_count_today(platform)
            if db_attempts_today >= configured_attempts_day:
                raise DailyCapReachedError(
                    f"Daily attempts cap reached for {platform}: opened {db_attempts_today}/{configured_attempts_day} Easy Apply forms today across all runs. Halting."
                )

        # 6. Check Session Max Attempts
        if self.session_attempts_count >= self.max_attempts:
            raise AttemptsLimitReachedError(
                f"Session attempts limit reached ({self.session_attempts_count}/{self.max_attempts} Easy Apply forms opened). Halting applications."
            )

    def check_page_safety(self, page, platform: str) -> None:
        """
        Inspects page DOM for CAPTCHA, login-wall, or account warnings.
        Halts immediately without attempting bypass.
        """
        # 1. Login-wall detection
        current_url = getattr(page, "url", "").lower()
        if "login" in current_url or "uas/login" in current_url or "checkpoint" in current_url:
            raise SafetyStopError(f"SAFETY STOP: Session logged out or login wall hit on {platform} (URL: {current_url}).")

        # 2. Structural challenge detection (if real Playwright page)
        try:
            if hasattr(page, "locator"):
                challenge_elements = page.locator(
                    "iframe[src*='arkoselabs'], iframe[src*='bframe'], iframe[title*='challenge' i], "
                    "div#captcha-internal, div[data-test-id*='challenge'], div.checkpoint-challenge"
                )
                if hasattr(challenge_elements, "count") and challenge_elements.count() > 0:
                    raise SafetyStopError(f"SAFETY STOP: CAPTCHA / bot challenge iframe/element detected on {platform}. Never attempt bypass.")
        except SafetyStopError:
            raise
        except Exception:
            pass

        # 3. Clean body content extraction (exclude head/meta/scripts to avoid telemetry false positives)
        raw = ""
        try:
            raw = page.content() or ""
        except Exception:
            pass

        body_match = re.search(r"<body[^>]*>([\s\S]*?)</body>", raw, re.IGNORECASE)
        body_content = body_match.group(1) if body_match else raw
        clean_body = re.sub(r"<(script|style|meta)[\s\S]*?</\1>", " ", body_content, flags=re.IGNORECASE)
        clean_body = re.sub(r"<meta[^>]*>", " ", clean_body, flags=re.IGNORECASE)
        text_only = re.sub(r"<[^>]+>", " ", clean_body)
        clean_text = re.sub(r"\s+", " ", text_only).lower()

        # 4. CAPTCHA detection
        captcha_keywords = [
            "captcha", "recaptcha", "hcaptcha", "perimeterx", "arkoselabs",
            "security check", "verify you are human", "let's do a quick security check"
        ]
        for kw in captcha_keywords:
            if kw in clean_text:
                raise SafetyStopError(f"SAFETY STOP: CAPTCHA / bot challenge detected on {platform} ('{kw}'). Never attempt bypass.")

        # 5. Account warning / Unusual activity detection
        warning_keywords = [
            "unusual activity", "account restricted", "temporarily restricted",
            "we noticed unusual activity", "account has been locked"
        ]
        for kw in warning_keywords:
            if kw in clean_text:
                raise SafetyStopError(f"SAFETY STOP: Account warning or unusual activity notice detected on {platform} ('{kw}').")

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self, reason: str = "", job_id: str = "") -> None:
        if job_id:
            self.failure_items.append({"job_id": str(job_id), "reason": str(reason)})
        self.consecutive_failures += 1
        max_failures = self.settings.get("safety", {}).get("max_consecutive_failures", 3)
        if self.consecutive_failures >= max_failures:
            raise SafetyStopError(
                f"SAFETY STOP: {self.consecutive_failures} consecutive unexpected failures occurred ({reason}). Halting run."
            )

    def action_delay(self) -> None:
        """Randomized pause between UI clicks and field inputs."""
        t_cfg = self.settings.get("timing", {})
        min_d = t_cfg.get("action_delay_min", 2)
        max_d = t_cfg.get("action_delay_max", 6)
        delay = random.uniform(min_d, max_d)
        time.sleep(delay)

    def job_delay(self) -> None:
        """Randomized pause between complete job applications."""
        t_cfg = self.settings.get("timing", {})
        min_d = t_cfg.get("job_delay_min", 30)
        max_d = t_cfg.get("job_delay_max", 90)
        delay = random.uniform(min_d, max_d)
        time.sleep(delay)
