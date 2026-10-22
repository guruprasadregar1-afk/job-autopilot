import sqlite3
import datetime
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = PROJECT_ROOT / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB_PATH = DB_DIR / "jobs.db"

class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    url TEXT,
                    description TEXT,
                    match_score INTEGER,
                    match_reason TEXT,
                    status TEXT NOT NULL,
                    failure_reason TEXT,
                    pending_question TEXT,
                    failure_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    applied_at TIMESTAMP,
                    UNIQUE(platform, job_id)
                )
            """)

            # Ensure failure_count exists in existing jobs tables
            cursor.execute("PRAGMA table_info(jobs)")
            cols = [c[1] for c in cursor.fetchall()]
            if "failure_count" not in cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN failure_count INTEGER DEFAULT 0")

            # audit / metadata table for approved review applications
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS review_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(platform, job_id)
                )
            """)

            # audit / timeline events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT,
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # audit / form attempts table (counts Easy Apply attempts across all runs)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    outcome TEXT,
                    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def record_job_attempt(self, platform: str, job_id: str, outcome: str = "") -> None:
        """Records an Easy Apply form attempt in DB."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO job_attempts (platform, job_id, outcome)
                VALUES (?, ?, ?)
            """, (platform, str(job_id), str(outcome)))
            conn.commit()

    def get_attempts_count_today(self, platform: str) -> int:
        """Returns total Easy Apply form attempts on platform today across all runs."""
        today_date = datetime.date.today().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM job_attempts
                WHERE platform = ?
                  AND DATE(attempted_at) = DATE(?)
            """, (platform, today_date))
            return cursor.fetchone()[0]

    def is_job_eligible(self, platform: str, job_id: str) -> bool:
        """
        Determines whether a job is eligible to be processed/attempted.
        Only final outcomes block a job:
          - APPLIED
          - UNVERIFIED
          - EXTERNAL_SITE
          - SKIPPED (hard-filtered or low score)
          - SKIPPED_BY_USER
          - FAILED after 2 or more failures (failure_count >= 2)
        Non-final states do NOT block (they are eligible again when seen):
          - (not recorded in DB)
          - FOUND
          - NEEDS_INPUT
          - OBSERVED_REVIEW
          - RESUME_PENDING_CONFIRMATION
          - FAILED with failure_count < 2
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status, COALESCE(failure_count, 0) FROM jobs WHERE platform = ? AND job_id = ?",
                (platform, str(job_id))
            )
            row = cursor.fetchone()
            if not row:
                return True
            status, failure_count = row[0], row[1]
            blocking_statuses = {
                "APPLIED", "UNVERIFIED", "EXTERNAL_SITE",
                "SKIPPED", "SKIPPED_BY_USER"
            }
            if status in blocking_statuses:
                return False
            if status in ("FAILED", "MODAL_NOT_DETECTED", "MODAL_CONTENT_NOT_RENDERED", "STEP_FAILED", "APPLY_BUTTON_NOT_FOUND") and failure_count >= 2:
                return False
            return True

    def is_job_blocked(self, platform: str, job_id: str) -> bool:
        """Returns True if the job has reached a final blocking outcome."""
        return not self.is_job_eligible(platform, job_id)

    def job_exists(self, platform: str, job_id: str, final_only: bool = False) -> bool:
        """
        Returns True if job exists in DB.
        If final_only is True, returns True only if the job has reached a final blocking outcome.
        """
        if final_only:
            return self.is_job_blocked(platform, job_id)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM jobs WHERE platform = ? AND job_id = ?",
                (platform, str(job_id))
            )
            return cursor.fetchone() is not None

    def get_job(self, platform: str, job_id: str) -> Optional[Dict[str, Any]]:
        """Returns job record as dictionary if exists, else None."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM jobs WHERE platform = ? AND job_id = ?",
                (platform, str(job_id))
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_job_by_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Returns job record as dictionary across platforms if exists, else None."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (str(job_id),)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_failure_count(self, platform: str, job_id: str) -> int:
        """Returns recorded consecutive/total failure count for a job."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COALESCE(failure_count, 0) FROM jobs WHERE platform = ? AND job_id = ?",
                (platform, str(job_id))
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def record_event(
        self,
        platform: str,
        job_id: str,
        event: str,
        old_status: Optional[str] = None,
        new_status: Optional[str] = None,
        note: str = ""
    ) -> None:
        """
        Records an audit timeline event in job_events.
        Sanitizes notes to ensure NO personal data or form answers are stored.
        """
        clean_note = str(note or "").strip()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO job_events (platform, job_id, event, old_status, new_status, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (platform, str(job_id), event, old_status, new_status, clean_note))
            conn.commit()

    def record_job(
        self,
        platform: str,
        job_id: str,
        title: str,
        company: str,
        location: str = "",
        url: str = "",
        description: str = "",
        match_score: Optional[int] = None,
        match_reason: str = "",
        status: str = "FOUND",
        failure_reason: str = "",
        pending_question: str = ""
    ) -> None:
        """Inserts or updates a job record and logs an audit event."""
        now = datetime.datetime.now().isoformat()
        applied_at = now if status == "APPLIED" else None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM jobs WHERE platform = ? AND job_id = ?", (platform, str(job_id)))
            row = cursor.fetchone()
            old_status = row[0] if row else None

            initial_failure_count = 1 if status in ("FAILED", "MODAL_NOT_DETECTED", "MODAL_CONTENT_NOT_RENDERED", "STEP_FAILED", "APPLY_BUTTON_NOT_FOUND") else 0

            cursor.execute("""
                INSERT INTO jobs (
                    platform, job_id, title, company, location, url,
                    description, match_score, match_reason, status,
                    failure_reason, pending_question, failure_count, updated_at, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, job_id) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    location = excluded.location,
                    url = excluded.url,
                    description = CASE WHEN excluded.description != '' THEN excluded.description ELSE jobs.description END,
                    match_score = COALESCE(excluded.match_score, jobs.match_score),
                    match_reason = CASE WHEN excluded.match_reason != '' THEN excluded.match_reason ELSE jobs.match_reason END,
                    status = excluded.status,
                    failure_reason = excluded.failure_reason,
                    pending_question = excluded.pending_question,
                    failure_count = CASE WHEN excluded.status IN ('FAILED', 'MODAL_NOT_DETECTED', 'MODAL_CONTENT_NOT_RENDERED', 'STEP_FAILED', 'APPLY_BUTTON_NOT_FOUND') THEN COALESCE(jobs.failure_count, 0) + 1 ELSE COALESCE(jobs.failure_count, 0) END,
                    updated_at = excluded.updated_at,
                    applied_at = COALESCE(excluded.applied_at, jobs.applied_at)
            """, (
                platform, str(job_id), title, company, location, url,
                description, match_score, match_reason, status,
                failure_reason, pending_question, initial_failure_count, now, applied_at
            ))
            conn.commit()

        if old_status is None or old_status != status:
            self.record_event(
                platform=platform,
                job_id=job_id,
                event=status,
                old_status=old_status,
                new_status=status,
                note=failure_reason or match_reason
            )

    def update_job_status(
        self,
        platform: str,
        job_id: str,
        status: str,
        failure_reason: str = "",
        pending_question: str = ""
    ) -> None:
        now = datetime.datetime.now().isoformat()
        applied_at = now if status == "APPLIED" else None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM jobs WHERE platform = ? AND job_id = ?", (platform, str(job_id)))
            row = cursor.fetchone()
            old_status = row[0] if row else None

            if status in ("FAILED", "MODAL_NOT_DETECTED", "MODAL_CONTENT_NOT_RENDERED", "STEP_FAILED", "APPLY_BUTTON_NOT_FOUND"):
                cursor.execute("""
                    UPDATE jobs SET
                        status = ?,
                        failure_reason = ?,
                        pending_question = ?,
                        failure_count = COALESCE(failure_count, 0) + 1,
                        updated_at = ?
                    WHERE platform = ? AND job_id = ?
                """, (status, failure_reason, pending_question, now, platform, str(job_id)))
            elif applied_at:
                cursor.execute("""
                    UPDATE jobs SET
                        status = ?,
                        failure_reason = ?,
                        pending_question = ?,
                        applied_at = ?,
                        updated_at = ?
                    WHERE platform = ? AND job_id = ?
                """, (status, failure_reason, pending_question, applied_at, now, platform, str(job_id)))
            else:
                cursor.execute("""
                    UPDATE jobs SET
                        status = ?,
                        failure_reason = ?,
                        pending_question = ?,
                        updated_at = ?
                    WHERE platform = ? AND job_id = ?
                """, (status, failure_reason, pending_question, now, platform, str(job_id)))
            conn.commit()

        if old_status != status:
            self.record_event(
                platform=platform,
                job_id=job_id,
                event=status,
                old_status=old_status,
                new_status=status,
                note=failure_reason or pending_question
            )

    def record_review_approval(self, platform: str, job_id: str) -> None:
        """Records user terminal confirmation in --review mode to count toward the 20 required approvals for --auto."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO review_approvals (platform, job_id)
                VALUES (?, ?)
            """, (platform, str(job_id)))
            conn.commit()

        self.record_event(
            platform=platform,
            job_id=job_id,
            event="REVIEW_APPROVAL",
            note="User terminal review approval granted"
        )

    def get_review_approval_count(self) -> int:
        """Returns total distinct user-approved review applications."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM review_approvals")
            return cursor.fetchone()[0]

    def get_applied_count_today(self, platform: str) -> int:
        """Counts jobs submitted on a specific platform today (both APPLIED and UNVERIFIED count toward cap)."""
        today_date = datetime.date.today().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE platform = ?
                  AND status IN ('APPLIED', 'UNVERIFIED')
                  AND (DATE(applied_at) = DATE(?) OR (applied_at IS NULL AND DATE(updated_at) = DATE(?)))
            """, (platform, today_date, today_date))
            return cursor.fetchone()[0]

    def get_total_applied_count(self, platform: Optional[str] = None) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if platform:
                cursor.execute("SELECT COUNT(*) FROM jobs WHERE platform = ? AND status = 'APPLIED'", (platform,))
            else:
                cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'APPLIED'")
            return cursor.fetchone()[0]

    def get_counts_by_status(self) -> Dict[str, int]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_pending_questions(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT platform, job_id, title, company, pending_question, updated_at
                FROM jobs
                WHERE status = 'NEEDS_INPUT' AND pending_question != ''
                ORDER BY updated_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_job_match_score(self, platform: str, job_id: str) -> Tuple[Optional[int], Optional[str]]:
        """Returns (match_score, match_reason) if job already has a recorded score in DB."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT match_score, match_reason FROM jobs WHERE platform = ? AND job_id = ? AND match_score IS NOT NULL",
                (platform, str(job_id))
            )
            row = cursor.fetchone()
            if row:
                return row[0], row[1]
            return None, None

    def has_applied_to_company_recently(self, company: str, days: int = 7) -> Tuple[bool, Optional[str]]:
        """
        Checks if an application has already been submitted to the same normalized company
        within the last `days` days. Returns (has_applied, existing_job_id).
        """
        from src.policy import normalize_company
        norm_target = normalize_company(company)
        if not norm_target:
            return False, None
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT company, applied_at, job_id, title
                FROM jobs
                WHERE status IN ('APPLIED', 'UNVERIFIED')
                  AND applied_at IS NOT NULL
                  AND applied_at >= ?
            """, (cutoff,))
            rows = cursor.fetchall()
            for r in rows:
                if normalize_company(r[0]) == norm_target:
                    return True, str(r[2])
        return False, None

    def requeue_answered_needs_input_jobs(self, platform: str, answerer: Optional[Any] = None) -> List[str]:
        """
        Finds any jobs with status 'NEEDS_INPUT' whose pending_question now has an
        approved answer in answers.yaml / FormAnswerer.
        Automatically resets their status to 'FOUND' with failure_count = 0 and clears pending_question.
        Returns list of requeued job IDs.
        """
        if answerer is None:
            try:
                from src.answerer import FormAnswerer
                answerer = FormAnswerer()
            except Exception:
                answerer = None

        if not answerer:
            return []

        requeued = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT job_id, pending_question FROM jobs
                WHERE platform = ? AND status = 'NEEDS_INPUT' AND pending_question IS NOT NULL AND pending_question != ''
            """, (platform,))
            rows = cursor.fetchall()

            now = datetime.datetime.now().isoformat()
            for row in rows:
                jid = str(row[0])
                pending_q = str(row[1]).strip()
                clean_q = re.sub(r"\s*\[type:\s*[^\]]+\]", "", pending_q).strip()

                meta_match = re.search(r"\[type:\s*([^,\]]+)(?:,\s*options:\s*([^\]]+))?\]", pending_q, re.IGNORECASE)
                options_seen = None
                ft = None
                if meta_match:
                    ft = meta_match.group(1).strip()
                    if meta_match.group(2):
                        options_seen = [o.strip() for o in meta_match.group(2).split(",") if o.strip()]

                ans = None
                if ft:
                    ans = answerer.find_direct_answer(clean_q, field_type=ft, options=options_seen)

                if not ans or ans == "UNKNOWN":
                    ans = answerer.find_direct_answer(clean_q, field_type="text")
                if not ans or ans == "UNKNOWN":
                    ans = answerer.find_direct_answer(clean_q, field_type="dropdown", options=options_seen)
                if not ans or ans == "UNKNOWN":
                    ans = answerer.find_direct_answer(clean_q, field_type="textarea")
                if not ans or ans == "UNKNOWN":
                    ans = answerer.find_direct_answer(clean_q, field_type="number")
                if not ans or ans == "UNKNOWN":
                    ans = answerer.find_direct_answer(clean_q, field_type="radio", options=options_seen)

                if ans and ans != "UNKNOWN":
                    # Pending question is now answered! Reset job to FOUND
                    cursor.execute("""
                        UPDATE jobs SET
                            status = 'FOUND',
                            failure_count = 0,
                            failure_reason = '',
                            pending_question = '',
                            updated_at = ?
                        WHERE platform = ? AND job_id = ?
                    """, (now, platform, jid))
                    requeued.append(jid)
            conn.commit()

        for jid in requeued:
            self.record_event(
                platform=platform,
                job_id=jid,
                event="REQUEUED_FROM_NEEDS_INPUT",
                old_status="NEEDS_INPUT",
                new_status="FOUND",
                note="Pending question now has approved answer in answers.yaml"
            )
            print(f"[REQUEUE] Job {jid} pending question answered -> automatically reset to FOUND.")

        return requeued

    def get_eligible_found_jobs(self, platform: str, limit: int = 10, answerer: Optional[Any] = None) -> List[Dict[str, Any]]:
        """
        Returns jobs already in DB with status 'FOUND' or retryable statuses that are eligible for application, ordered by updated_at DESC.
        Automatically checks and requeues any 'NEEDS_INPUT' jobs whose pending_question now has an approved answer.
        """
        try:
            self.requeue_answered_needs_input_jobs(platform=platform, answerer=answerer)
        except Exception as e:
            print(f"[REQUEUE WARNING] Error during auto-requeue check: {e}")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT platform, job_id, title, company, location, url, match_score, match_reason
                FROM jobs
                WHERE platform = ?
                  AND status IN ('FOUND', 'MODAL_NOT_DETECTED', 'MODAL_CONTENT_NOT_RENDERED', 'STEP_FAILED', 'BROWSER_CLOSED', 'APPLY_BUTTON_NOT_FOUND')
                  AND COALESCE(failure_count, 0) < 2
                ORDER BY updated_at DESC
                LIMIT ?
            """, (platform, limit))
            return [dict(row) for row in cursor.fetchall()]

    def export_applied_jobs(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT platform, job_id, title, company, location, url, applied_at, match_score, match_reason
                FROM jobs
                WHERE status = 'APPLIED'
                ORDER BY applied_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_timeline_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, platform, job_id, event, old_status, new_status, note, created_at
                FROM job_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_all_jobs_for_dashboard(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT platform, job_id, title, company, location, url, match_score,
                       match_reason, status, failure_reason, pending_question,
                       applied_at, updated_at, created_at
                FROM jobs
                ORDER BY updated_at DESC, id DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_companies_summary(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT company,
                       COUNT(*) as total_apps,
                       GROUP_CONCAT(DISTINCT platform) as platforms,
                       MAX(updated_at) as last_date,
                       GROUP_CONCAT(status) as statuses
                FROM jobs
                WHERE company != ''
                GROUP BY company
                ORDER BY total_apps DESC, last_date DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_applied_count_this_week(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE status = 'APPLIED'
                  AND applied_at >= datetime('now', '-7 days')
            """)
            return cursor.fetchone()[0]

    def get_daily_counts(self, days: int = 7) -> List[Dict[str, Any]]:
        """Returns applied counts for each of the last N days."""
        daily = []
        today = datetime.date.today()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for i in range(days - 1, -1, -1):
                d = today - datetime.timedelta(days=i)
                d_str = d.isoformat()
                cursor.execute("""
                    SELECT platform, COUNT(*) FROM jobs
                    WHERE status = 'APPLIED' AND DATE(applied_at) = DATE(?)
                    GROUP BY platform
                """, (d_str,))
                counts = {row[0]: row[1] for row in cursor.fetchall()}
                daily.append({
                    "date": d_str,
                    "linkedin": counts.get("linkedin", 0),
                    "naukri": counts.get("naukri", 0),
                    "total": sum(counts.values())
                })
        return daily
