import sys
import time
import argparse
import csv
from pathlib import Path
from typing import Optional, Any

# Ensure stdout and stderr flush immediately with line buffering
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from src.browser import BrowserManager, ensure_clean_tabs
from src.db import Database
from src.guards import GuardsManager, SafetyStopError, DailyCapReachedError, OutsideWorkingHoursError, SessionLimitExceededError, AttemptsLimitReachedError, ResumeMismatchHaltError
from src.matcher import JobMatcher
from src.llm import UsageLimitReached, get_claude_call_count, reset_claude_call_count
from src.platforms.linkedin import LinkedInCollector
from src.platforms.naukri import NaukriCollector


def login_flow():
    """
    Opens persistent browser context for manual user login to LinkedIn and Naukri.
    Waits for user to log in and confirms authenticated state.
    """
    print("\n" + "="*60)
    print("MANUAL LOGIN SESSION (Zero Passwords Handled by Automation)")
    print("="*60)
    print("Opening persistent browser profile in Microsoft Edge...")
    print("Please log in manually on LinkedIn and Naukri (including any OTP/2FA).")
    print("Your session will be saved in browser_profile/.")
    print("="*60 + "\n")

    mgr = BrowserManager(headless=False)
    context = mgr.start()

    page_li = context.new_page()
    page_li.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

    page_nk = context.new_page()
    page_nk.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")

    print("\nBrowser is open with LinkedIn and Naukri tabs.")
    print("When you have finished logging in on both platforms, return here.")
    input("Press ENTER after you have successfully logged in on both sites... ")

    print("\nVerifying sessions...")
    page_li.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded")
    time.sleep(3)
    li_logged_in = ("jobs" in page_li.url or page_li.locator(".global-nav__me, nav, [data-test-global-nav-me]").count() > 0)
    if li_logged_in:
        print("[SUCCESS] LinkedIn session detected and active!")
    else:
        print("[WARNING] Could not confirm LinkedIn jobs landing page. Current URL:", page_li.url)

    page_nk.goto("https://www.naukri.com/mnjuser/homepage", wait_until="domcontentloaded")
    time.sleep(3)
    nk_logged_in = ("homepage" in page_nk.url or "mnjuser" in page_nk.url or page_nk.locator(".nI-gNb-drawer, .view-profile-wrapper").count() > 0)
    if nk_logged_in:
        print("[SUCCESS] Naukri session detected and active!")
    else:
        print("[WARNING] Could not confirm Naukri homepage. Current URL:", page_nk.url)

    print("\nClosing browser to flush session state to disk...")
    mgr.close()

    if li_logged_in and nk_logged_in:
        print("\n[ALL SESSIONS SAVED] Both LinkedIn and Naukri sessions are preserved in browser_profile/.")
    else:
        print("\n[NOTICE] One or more sessions may not have fully completed login. You can rerun anytime.")

def show_status(db: Database):
    print("\n" + "="*50)
    print("JOB AUTOPILOT STATUS DASHBOARD")
    print("="*50)
    counts = db.get_counts_by_status()
    print("Jobs by Status:")
    for status, count in counts.items():
        print(f"  - {status:15}: {count}")
    
    print("\nApplications Today:")
    print(f"  - LinkedIn : {db.get_applied_count_today('linkedin')}")
    print(f"  - Naukri   : {db.get_applied_count_today('naukri')}")
    
    approvals = db.get_review_approval_count()
    print(f"\nReview Approvals for --auto Unlock:")
    print(f"  - Approved : {approvals} / 20 required")
    if approvals >= 20:
        print("  - Status   : UNLOCKED (--auto mode is permitted)")
    else:
        print("  - Status   : LOCKED (Requires " + str(20 - approvals) + " more approvals in --review mode)")
    print("="*50 + "\n")

def export_csv(db: Database, output_file: str = "data/applied_jobs.csv"):
    jobs = db.export_applied_jobs()
    out_path = PROJECT_ROOT / output_file
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not jobs:
        print("No applied jobs found to export.")
        return
    keys = jobs[0].keys()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(jobs)
    print(f"Successfully exported {len(jobs)} applied jobs to {out_path}")

def show_needs_input(db: Database):
    import re
    from src.answerer import FormAnswerer

    answerer = FormAnswerer()
    pending = db.get_pending_questions()
    print("\n" + "="*70)
    print(f"UNANSWERED SCREENING QUESTIONS REQUIRING INPUT ({len(pending)})")
    print("="*70)
    if not pending:
        print("No pending questions found. All application questions were answered!")
        return

    for item in pending:
        platform = item.get("platform", "")
        job_id = item.get("job_id", "")
        title = item.get("title", "")
        company = item.get("company", "")
        raw_q = (item.get("pending_question") or "").strip()

        # Extract explicit metadata if formatted as "[type: ..., options: ...]"
        field_type = "text"
        options_seen = []
        clean_q = raw_q

        meta_match = re.search(r"\[type:\s*([^,\]]+)(?:,\s*options:\s*([^\]]+))?\]", raw_q, re.IGNORECASE)
        if meta_match:
            field_type = meta_match.group(1).strip()
            if meta_match.group(2):
                options_seen = [o.strip() for o in meta_match.group(2).split(",") if o.strip()]
            clean_q = re.sub(r"\s*\[type:\s*[^\]]+\]", "", raw_q).strip()
        else:
            # Heuristic detection for field type and options
            lower_q = clean_q.lower()
            if any(lower_q.startswith(prefix) for prefix in ("are you", "do you", "will you", "have you", "can you", "would you", "is ", "was ")):
                field_type = "radio / dropdown"
                options_seen = ["Yes", "No"]
            elif any(k in lower_q for k in ("years", "how many", "notice period", "ctc", "salary", "pincode", "postal code", "zip code", "days", "months")):
                field_type = "numeric / text"
                options_seen = ["None (free-text or numeric input)"]
            elif any(k in lower_q for k in ("describe", "please explain", "summary", "elaborate", "tell us")):
                field_type = "textarea"
                options_seen = ["None (multiline textarea)"]
            else:
                field_type = "text / dropdown"
                options_seen = ["Not specified / see form"]

        normalized_q = answerer.normalize(clean_q)
        options_display = ", ".join(options_seen) if options_seen else "None"

        print(f"Platform    : {platform.upper()} | Job ID: {job_id}")
        print(f"Job         : {title} @ {company}")
        print(f"Question    : {clean_q}")
        print(f"Field Type  : {field_type}")
        print(f"Options Seen: {options_display}")
        print("\nReady-to-paste answers.yaml entry (EXAMPLE only - fill value before use):")
        print("  - patterns:")
        print(f'      - "{normalized_q}"')
        print('    value: ""')
        print("    exact_match: true")
        print("-" * 70)

    print("\nTo enable automatic answering, add approved entries to config/answers.yaml with your verified value.\n")

def print_run_banner(platform: str, mode: str, guards: GuardsManager, resume_name: str, active_searches: list, is_rehearsal: bool = False):
    from src.policy import OBSERVE_ONLY
    daily_cap_li = guards.settings.get("caps", {}).get("linkedin_daily_cap", 25)
    daily_cap_nk = guards.settings.get("caps", {}).get("naukri_daily_cap", 40)
    attempts_day = guards.settings.get("caps", {}).get("attempts_per_day", 25)
    max_apply_val = guards.max_apply if guards.max_apply is not None else "Not set (bounded by daily cap)"
    max_attempts_val = guards.max_attempts
    max_jobs_plat = guards.settings.get("search", {}).get("max_jobs_per_platform", 10)

    effective_observe_only = True if (is_rehearsal or "rehearsal" in mode.lower() or "dry-run" in mode.lower()) else OBSERVE_ONLY

    print("\n" + "="*70)
    print("                      JOB AUTOPILOT RUN BANNER")
    print("="*70)
    if is_rehearsal:
        print("REHEARSAL: submit impossible")
    print(f"Target Platform       : {platform.upper()}")
    print(f"Execution Mode        : {mode.upper()}")
    print(f"OBSERVE_ONLY State    : {effective_observe_only} (Submit strictly blocked)" if effective_observe_only else f"OBSERVE_ONLY State    : {effective_observe_only} (LIVE SUBMISSIONS PERMITTED)")
    print(f"Configured Resume Name: {resume_name}")
    print("\nCAPS & LIMITS:")
    print(f"  - Daily App Cap     : LinkedIn = {daily_cap_li}, Naukri = {daily_cap_nk}")
    print(f"  - Daily Attempts Cap: {attempts_day} Easy Apply forms opened/day (across runs)")
    print(f"  - Per-Run Attempts  : {max_attempts_val} forms opened/session (--max-attempts)")
    print(f"  - Per-Run Max Apply : {max_apply_val}")
    print(f"  - Jobs Per Platform : {max_jobs_plat} (1 page limit)")
    print("\nACTIVE SEARCHES:")
    for s in active_searches:
        plat = s.get("platform", platform)
        kw = s.get("keywords")
        loc = s.get("location") or s.get("locations")
        print(f"  - [{plat.upper()}] '{kw}' in {loc}")
    print("="*70)
    try:
        user_ack = input("Type 'START' to proceed: ").strip()
    except (EOFError, KeyboardInterrupt):
        user_ack = ""
    if user_ack != "START":
        print(f"\n[ABORTED] Run cancelled by user (received '{user_ack}', expected 'START'). Exiting.")
        sys.exit(0)
    print("[CONFIRMED] 'START' accepted. Beginning execution...\n")

def run_pipeline(
    db: Database,
    guards: GuardsManager,
    matcher: JobMatcher,
    platform: str = "linkedin",
    is_rehearsal: bool = False,
    review_mode: bool = False,
    browser_manager: Optional[Any] = None,
    target_job_id: Optional[str] = None
):
    """
    Executes full job application pipeline:
    1. Re-checks and cleans tabs.
    2. Processes eligible FOUND jobs from DB first (up to session attempts cap).
    3. Runs search collection on active search queries.
    4. Evaluates hard-filters in Python (company blacklist, title exclusions, regional restrictions, locations).
    5. Checks / reuses stored match score in DB (0 Claude calls if already scored; calls Claude only if unscored).
    6. For every job passing threshold: opens Easy Apply, runs LinkedInApplicant
       (city typeahead, character-for-character resume verification, answers approved screening fields from answers.yaml,
       safely unchecks follow-company checkbox).
    7. Advances to Review step.
    8. In rehearsal (or OBSERVE_ONLY): Submit click is impossible; prints full Review details, safely discards draft, and records OBSERVED_REVIEW in DB.
    9. In live --review mode (with OBSERVE_ONLY=False): prompts user for typed YES, submits, verifies on-page success confirmation, and records APPLIED.
    """
    from src.platforms.linkedin import LinkedInCollector, LinkedInApplicant
    from src.platforms.naukri import NaukriCollector
    from src.policy import OBSERVE_ONLY, BrowserClosedCleanStop, is_browser_closed_error, UnverifiedApplicationHaltError

    effective_rehearsal = bool(is_rehearsal or OBSERVE_ONLY)
    mode_desc = "REHEARSAL (SUBMIT IMPOSSIBLE)" if effective_rehearsal else "LIVE (REVIEW MODE)"
    print("\n" + "="*70)
    print(f"STARTING JOB APPLICATION PIPELINE: {platform.upper()} [{mode_desc}]")
    print("="*70)

    reset_claude_call_count()
    mgr = browser_manager or BrowserManager(headless=False)
    ctx = mgr.start()
    ensure_clean_tabs(ctx)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    applicant = LinkedInApplicant(
        db=db,
        guards=guards,
        review_mode=review_mode,
        is_rehearsal=effective_rehearsal
    )
    li_collector = LinkedInCollector(db, guards, matcher, browser_manager=mgr)
    nk_collector = NaukriCollector(db, guards, matcher)

    try:
        max_jobs = guards.settings.get("search", {}).get("max_jobs_per_platform", 10)

        if platform in ("linkedin", "all"):
            # 1. Process eligible FOUND jobs from DB first (or specific target job)
            remaining_attempts = guards.max_attempts - guards.session_attempts_count
            if remaining_attempts > 0:
                li_collector.process_eligible_found_jobs(
                    page,
                    applicant=applicant,
                    limit=remaining_attempts,
                    is_rehearsal=effective_rehearsal,
                    target_job_id=target_job_id
                )

            # 2. Search and apply for new jobs if not targeting a single job and attempts limit not reached
            if not target_job_id:
                remaining_attempts = guards.max_attempts - guards.session_attempts_count
                if remaining_attempts > 0:
                    li_cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "search_linkedin.yaml", encoding="utf-8"))
                    for q in li_cfg.get("searches", [])[:1]:
                        li_collector.run_search_and_apply(
                            page,
                            search_query=q,
                            applicant=applicant,
                            max_jobs=max_jobs,
                            is_rehearsal=effective_rehearsal,
                            dry_run=False
                        )

        if platform in ("naukri", "all"):
            nk_cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "search_naukri.yaml", encoding="utf-8"))
            for q in nk_cfg.get("searches", [])[:1]:
                nk_collector.run_phase8a_search(page, q, max_jobs=max_jobs, dry_run=True)

        if platform in ("indeed", "all"):
            from src.platforms.indeed import IndeedCollector, IndeedApplicant
            in_applicant = IndeedApplicant(
                db=db,
                guards=guards,
                review_mode=review_mode,
                is_rehearsal=effective_rehearsal
            )
            in_collector = IndeedCollector(db, guards, matcher, browser_manager=mgr)
            remaining_attempts = guards.max_attempts - guards.session_attempts_count
            if remaining_attempts > 0:
                in_collector.process_eligible_found_jobs(
                    page,
                    applicant=in_applicant,
                    limit=remaining_attempts,
                    is_rehearsal=effective_rehearsal,
                    target_job_id=target_job_id
                )
            if not target_job_id:
                remaining_attempts = guards.max_attempts - guards.session_attempts_count
                if remaining_attempts > 0:
                    indeed_cfg_file = PROJECT_ROOT / "config" / "search_indeed.yaml"
                    if indeed_cfg_file.exists():
                        in_cfg = yaml.safe_load(open(indeed_cfg_file, encoding="utf-8")) or {}
                        for q in in_cfg.get("searches", [])[:1]:
                            in_collector.run_search_and_apply(
                                page,
                                search_query=q,
                                applicant=in_applicant,
                                max_jobs=max_jobs,
                                is_rehearsal=effective_rehearsal,
                                dry_run=False
                            )

    except BrowserClosedCleanStop as e:
        print("\n[STOP] Browser closed unexpectedly (see logs/browser_lifecycle.log). Saving state and exiting cleanly.")
    except UsageLimitReached as e:
        print(f"\n[USAGE LIMIT STOP] {e}")
        print("Exiting cleanly without retrying against quota. Run again after your quota resets.")
    except ResumeMismatchHaltError as e:
        print(f"\n[FATAL RESUME HALT STOP] {e}")
    except UnverifiedApplicationHaltError:
        print("\nApplication submitted, success not confirmed: UNVERIFIED. Check LinkedIn My Jobs -> Applied.")
    except (SafetyStopError, DailyCapReachedError, OutsideWorkingHoursError, SessionLimitExceededError, AttemptsLimitReachedError) as e:
        print(f"\n[SAFETY GUARD STOP] {e}")
    except Exception as e:
        from src.policy import is_browser_closed_error
        if is_browser_closed_error(e):
            print("\n[STOP] Browser closed unexpectedly (see logs/browser_lifecycle.log). Saving state and exiting cleanly.")
        else:
            raise
    finally:
        mgr.close()
        guards.print_attempts_summary()
        print("\n" + "="*70)
        print("PIPELINE EXECUTION SUMMARY REPORT")
        print("="*70)
        counts = db.get_counts_by_status()
        print("Database Job Counts by Status:")
        for status, count in counts.items():
            print(f"  - {status:25}: {count}")

        print("\nJobs Submitted in this Run:")
        if guards.submitted_jobs_in_run:
            for job in guards.submitted_jobs_in_run:
                u = job.get("url") or f"https://www.linkedin.com/jobs/view/{job.get('job_id')}/"
                print(f"  - {job.get('title')} @ {job.get('company')} ({u})")
        else:
            print("  (None)")

        claude_calls = get_claude_call_count()
        print(f"\nTotal Claude CLI Calls Used: {claude_calls}")
        print("="*70 + "\n")

def mark_applied_cmd(db: Database, job_id: str) -> None:
    job = db.get_job_by_id(job_id)
    if not job:
        print(f"\n[ERROR] Job ID '{job_id}' not found in database.")
        sys.exit(1)

    current_status = job.get("status")
    if current_status != "UNVERIFIED":
        print(f"\n[REFUSAL] Job '{job_id}' status is '{current_status}'. mark-applied only accepts jobs in 'UNVERIFIED' status.")
        sys.exit(1)

    platform = job.get("platform", "linkedin")
    title = job.get("title", "")
    company = job.get("company", "")

    db.update_job_status(platform=platform, job_id=job_id, status="APPLIED")
    db.record_event(
        platform=platform,
        job_id=job_id,
        event="MANUALLY_CONFIRMED",
        old_status="UNVERIFIED",
        new_status="APPLIED",
        note="Manually confirmed applied by user"
    )
    print(f"\n[SUCCESS] Job {job_id} ('{title}' @ '{company}') marked as APPLIED with event MANUALLY_CONFIRMED.")

def run_dry_run_8a(db: Database, guards: GuardsManager, matcher: JobMatcher, platform: str = "linkedin"):
    """Backward-compatible wrapper for Phase 8a dry-run."""
    run_pipeline(db, guards, matcher, platform=platform, is_rehearsal=True, review_mode=False)

def main():
    parser = argparse.ArgumentParser(description="Job Autopilot CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("login", help="Open browser to log in manually")
    subparsers.add_parser("status", help="Show application counts and database status")
    subparsers.add_parser("export", help="Export applied jobs to CSV")
    subparsers.add_parser("needs-input", help="List unanswered questions requiring manual input")

    run_parser = subparsers.add_parser("run", help="Run application automation")
    run_parser.add_argument("--platform", choices=["linkedin", "naukri", "indeed", "all"], default="linkedin", help="Target platform to run (choices: linkedin, naukri, indeed, all; default: linkedin)")
    run_parser.add_argument("--dry-run", action="store_true", help="Simulate flow without final submit")
    run_parser.add_argument("--rehearse", action="store_true", help="Force rehearsal mode (observe-only, submit impossible)")
    run_parser.add_argument("--review", action="store_true", help="Pause and ask for confirmation before submit")
    run_parser.add_argument("--auto", action="store_true", help="Submit automatically (requires 20 approved reviews)")
    run_parser.add_argument("--max-apply", type=int, default=None, help="Limit maximum applications for this session (can only lower daily cap)")
    run_parser.add_argument("--max-attempts", type=int, default=10, help="Limit maximum Easy Apply forms opened for this session (default: 10; can only lower hard limits)")
    run_parser.add_argument("--job-id", type=str, default=None, help="Process only a single stored FOUND job by ID (refuses if not in DB)")

    dashboard_parser = subparsers.add_parser("dashboard", help="Generate or serve read-only Application History Dashboard")
    dashboard_parser.add_argument("--serve", action="store_true", help="Serve dashboard using standard library HTTP server bound to 127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8080, help="Port to serve dashboard on (default: 8080)")

    mark_applied_parser = subparsers.add_parser("mark-applied", help="Manually confirm an UNVERIFIED application as APPLIED")
    mark_applied_parser.add_argument("--job-id", type=str, required=True, help="Job ID to mark as APPLIED")

    args = parser.parse_args()
    db = Database()
    guards = GuardsManager(db)
    matcher = JobMatcher()

    if args.command == "login":
        login_flow()
    elif args.command == "status":
        show_status(db)
    elif args.command == "export":
        export_csv(db)
    elif args.command == "needs-input":
        show_needs_input(db)
    elif args.command == "dashboard":
        from src.dashboard import generate_dashboard, serve_dashboard
        out = generate_dashboard()
        if args.serve:
            serve_dashboard(output_file=out, port=args.port)
    elif args.command == "mark-applied":
        mark_applied_cmd(db, args.job_id)
    elif args.command == "run":
        if args.rehearse and args.auto:
            print("\n[CONFIG ERROR] --rehearse cannot be combined with live mode (--auto).")
            sys.exit(1)
        if args.auto:
            approvals = db.get_review_approval_count()
            if approvals < 20:
                print(f"\n[AUTO LOCKED] --auto requires at least 20 approved applications in --review mode. Currently: {approvals}/20.")
                sys.exit(1)

        target_job_id = getattr(args, "job_id", None)
        if target_job_id:
            job_rec = db.get_job_by_id(target_job_id)
            if not job_rec:
                print(f"\n[ERROR] Job ID '{target_job_id}' not found in database. Single-job mode requires an existing stored job.")
                sys.exit(1)
            print(f"\n[SINGLE-JOB MODE] Targeting stored job ID: {target_job_id}")

        if args.max_apply is not None:
            if args.max_apply <= 0:
                print(f"[ERROR] --max-apply must be a positive integer (got {args.max_apply}).")
                sys.exit(1)
            guards.set_max_apply(args.max_apply)
            configured_li = guards.settings.get("caps", {}).get("linkedin_daily_cap", 25)
            effective_li = min(configured_li, args.max_apply)
            print(f"[SESSION LIMIT] --max-apply set to {args.max_apply} (effective LinkedIn daily cap: {effective_li})")

        if args.max_attempts is not None:
            if args.max_attempts <= 0:
                print(f"[ERROR] --max-attempts must be a positive integer (got {args.max_attempts}).")
                sys.exit(1)
            guards.set_max_attempts(args.max_attempts)
            print(f"[SESSION LIMIT] --max-attempts set to {guards.max_attempts}")

        resume_name = matcher.profile.get("resume", {}).get("selected_filename", "")
        if not resume_name or resume_name == "PENDING_USER_CONFIRMATION":
            print(f"\n[REFUSAL TO START] Applications are strictly blocked while resume.selected_filename is '{resume_name}'.")
            print("Please upload your new resume PDF to LinkedIn, verify the exact filename shown in the Easy Apply modal, and update config/profile.yaml.")
            sys.exit(1)

        from src.policy import OBSERVE_ONLY
        is_rehearsal = bool(args.rehearse or args.dry_run or OBSERVE_ONLY)
        mode = "rehearsal (dry-run)" if is_rehearsal else "live (review mode)"

        # Collect active searches for run banner (only first LinkedIn search for live/rehearsal runs)
        active_searches = []
        if not target_job_id:
            if args.platform in ("linkedin", "all"):
                li_cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "search_linkedin.yaml", encoding="utf-8"))
                for s in [sc for sc in li_cfg.get("searches", []) if not sc.get("disabled", False)][:1]:
                    s_copy = dict(s)
                    s_copy["platform"] = "linkedin"
                    active_searches.append(s_copy)
            if args.platform in ("naukri", "all"):
                nk_cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "search_naukri.yaml", encoding="utf-8"))
                for s in [sc for sc in nk_cfg.get("searches", []) if not sc.get("disabled", False)][:1]:
                    s_copy = dict(s)
                    s_copy["platform"] = "naukri"
                    active_searches.append(s_copy)
            if args.platform in ("indeed", "all"):
                ind_path = PROJECT_ROOT / "config" / "search_indeed.yaml"
                if ind_path.exists():
                    ind_cfg = yaml.safe_load(open(ind_path, encoding="utf-8")) or {}
                    for s in [sc for sc in ind_cfg.get("searches", []) if not sc.get("disabled", False)][:1]:
                        s_copy = dict(s)
                        s_copy["platform"] = "indeed"
                        active_searches.append(s_copy)

        print_run_banner(platform=args.platform, mode=mode, guards=guards, resume_name=resume_name, active_searches=active_searches, is_rehearsal=is_rehearsal)

        if args.rehearse or args.dry_run or OBSERVE_ONLY:
            if args.rehearse:
                print("\n[REHEARSAL ACTIVE] Running in rehearsal mode: submit impossible.")
            elif args.dry_run:
                print("\n[DRY RUN ACTIVE] Simulating flow without final submit.")
            else:
                print("\n[OBSERVE_ONLY ACTIVE] Live submissions are disabled because OBSERVE_ONLY = True in src/policy.py.")
                print("Rehearsal observation mode will be run instead.")
            run_pipeline(
                db=db,
                guards=guards,
                matcher=matcher,
                platform=args.platform,
                is_rehearsal=True,
                review_mode=args.review,
                target_job_id=target_job_id
            )
        else:
            if not args.review:
                print("\n[SAFETY ENFORCEMENT] Live execution strictly requires --review mode and typed 'YES' in terminal for each application.")
                print("Usage: python -m src.main run --review [--max-apply N]")
                sys.exit(1)

            print("\nLive application mode active with --review and explicit confirmation.")
            run_pipeline(
                db=db,
                guards=guards,
                matcher=matcher,
                platform=args.platform,
                is_rehearsal=False,
                review_mode=True,
                target_job_id=target_job_id
            )
    elif not args.command:
        parser.print_help()

if __name__ == "__main__":
    main()
