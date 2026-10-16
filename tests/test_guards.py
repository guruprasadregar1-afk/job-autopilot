import pytest
import datetime
from unittest.mock import MagicMock, patch
from src.guards import (
    GuardsManager,
    SafetyStopError,
    DailyCapReachedError,
    OutsideWorkingHoursError,
    SessionLimitExceededError
)

class FakeDB:
    def __init__(self, count=0):
        self.count = count

    def get_applied_count_today(self, platform):
        return self.count

def test_daily_cap_reached():
    db = FakeDB(count=25)
    mgr = GuardsManager(db)
    mgr.settings["timing"]["working_hours"]["enabled"] = False
    with pytest.raises(DailyCapReachedError):
        mgr.check_pre_job_guards("linkedin")

def test_consecutive_failures_safety_stop():
    db = FakeDB(count=0)
    mgr = GuardsManager(db)
    mgr.record_failure("error 1")
    mgr.record_failure("error 2")
    assert mgr.consecutive_failures == 2
    with pytest.raises(SafetyStopError):
        mgr.record_failure("error 3")

def test_captcha_detection():
    db = FakeDB(count=0)
    mgr = GuardsManager(db)
    page = MagicMock()
    page.content.return_value = "<html><body>Please complete this captcha to continue</body></html>"
    page.url = "https://www.linkedin.com/jobs/view/123"

    with pytest.raises(SafetyStopError) as exc_info:
        mgr.check_page_safety(page, "linkedin")
    assert "CAPTCHA" in str(exc_info.value)

def test_login_wall_detection():
    db = FakeDB(count=0)
    mgr = GuardsManager(db)
    page = MagicMock()
    page.content.return_value = "<html><body>Login Form</body></html>"
    page.url = "https://www.linkedin.com/uas/login?session_redirect=..."

    with pytest.raises(SafetyStopError) as exc_info:
        mgr.check_page_safety(page, "linkedin")
    assert "login wall" in str(exc_info.value)

def test_unusual_activity_warning():
    db = FakeDB(count=0)
    mgr = GuardsManager(db)
    page = MagicMock()
    page.content.return_value = "<html><body>We noticed unusual activity on your account.</body></html>"
    page.url = "https://www.naukri.com/mnjuser/homepage"

    with pytest.raises(SafetyStopError) as exc_info:
        mgr.check_page_safety(page, "naukri")
    assert "unusual activity" in str(exc_info.value)

def test_working_hours_outside():
    db = FakeDB(count=0)
    mgr = GuardsManager(db)
    night_time = datetime.datetime.now().replace(hour=23, minute=0, second=0)
    mgr.session_start_time = night_time
    with patch("src.guards.datetime.datetime") as mock_dt:
        mock_dt.now.return_value = night_time
        with pytest.raises(OutsideWorkingHoursError):
            mgr.check_pre_job_guards("linkedin")

def test_session_limit_exceeded():
    db = FakeDB(count=0)
    mgr = GuardsManager(db)
    midday = datetime.datetime.now().replace(hour=12, minute=0, second=0)
    mgr.session_start_time = midday - datetime.timedelta(minutes=130)
    with patch("src.guards.datetime.datetime") as mock_dt:
        mock_dt.now.return_value = midday
        with pytest.raises(SessionLimitExceededError):
            mgr.check_pre_job_guards("linkedin")

def test_max_apply_can_only_lower_daily_cap():
    # 1. Lowering cap from 25 to 5
    db = FakeDB(count=5)
    mgr = GuardsManager(db, max_apply=5)
    mgr.settings["timing"]["working_hours"]["enabled"] = False
    with pytest.raises(DailyCapReachedError) as exc:
        mgr.check_pre_job_guards("linkedin")
    assert "applied 5/5" in str(exc.value)

    # 2. Specifying higher value than config cap (100 vs 25) can NEVER raise the cap
    db25 = FakeDB(count=25)
    mgr_high = GuardsManager(db25, max_apply=100)
    mgr_high.settings["timing"]["working_hours"]["enabled"] = False
    with pytest.raises(DailyCapReachedError) as exc_high:
        mgr_high.check_pre_job_guards("linkedin")
    # Cap remains 25
    assert "applied 25/25" in str(exc_high.value)

def test_max_apply_session_limit_stops_run():
    db = FakeDB(count=0)
    mgr = GuardsManager(db, max_apply=2)
    mgr.settings["timing"]["working_hours"]["enabled"] = False
    # Apply 2 jobs during session
    mgr.record_application_success("linkedin")
    mgr.record_application_success("linkedin")
    assert mgr.session_applied_count == 2
    with pytest.raises(DailyCapReachedError) as exc:
        mgr.check_pre_job_guards("linkedin")
    assert "Session application limit reached" in str(exc.value)

def test_max_attempts_cap_and_summary():
    from src.guards import AttemptsLimitReachedError
    db = FakeDB(count=0)
    # Default is 10
    mgr = GuardsManager(db)
    mgr.settings["timing"]["working_hours"]["enabled"] = False
    assert mgr.max_attempts == 10

    # Custom limit set to 3
    mgr.set_max_attempts(3)
    assert mgr.max_attempts == 3

    # Attempt 1: Applied
    mgr.record_form_opened()
    mgr.record_attempt_outcome("APPLIED")

    # Attempt 2: Needs Input
    mgr.record_form_opened()
    mgr.record_attempt_outcome("NEEDS_INPUT")

    # Attempt 3: Failed
    mgr.record_form_opened()
    mgr.record_attempt_outcome("FAILED")

    # Check summary counts
    assert mgr.attempts_summary["opened"] == 3
    assert mgr.attempts_summary["applied"] == 1
    assert mgr.attempts_summary["needs_input"] == 1
    assert mgr.attempts_summary["failed"] == 1
    assert mgr.attempts_summary["skipped"] == 0

    # Guard triggers AttemptsLimitReachedError cleanly at 3
    with pytest.raises(AttemptsLimitReachedError) as exc:
        mgr.check_attempts_guard()
    assert "Session attempts limit reached (3/3" in str(exc.value)

    with pytest.raises(AttemptsLimitReachedError):
        mgr.check_pre_job_guards("linkedin")


def test_max_attempts_cannot_exceed_hard_limit():
    db = FakeDB(count=0)
    mgr = GuardsManager(db)
    # Hard limit is 50
    mgr.set_max_attempts(100)
    assert mgr.max_attempts == 50

    # Can lower it
    mgr.set_max_attempts(5)
    assert mgr.max_attempts == 5

def test_daily_attempts_cap_stored_in_db_across_runs(tmp_path):
    from src.db import Database
    db_file = tmp_path / "test_attempts.db"
    db = Database(db_path=db_file)

    # Run 1: 15 attempts recorded in DB
    guards_run1 = GuardsManager(db)
    guards_run1.settings["timing"]["working_hours"]["enabled"] = False
    for i in range(15):
        guards_run1.record_form_opened(platform="linkedin", job_id=f"li-{i}")
    assert db.get_attempts_count_today("linkedin") == 15

    # Run 2 (new session, new GuardsManager instance): 9 more attempts
    guards_run2 = GuardsManager(db)
    guards_run2.settings["timing"]["working_hours"]["enabled"] = False
    for i in range(15, 24):
        guards_run2.record_form_opened(platform="linkedin", job_id=f"li-{i}")
    assert db.get_attempts_count_today("linkedin") == 24

    # 24/25 attempts: pre-job guards still pass
    guards_run2.check_pre_job_guards("linkedin")

    # Record 25th attempt
    guards_run2.record_form_opened(platform="linkedin", job_id="li-24")
    assert db.get_attempts_count_today("linkedin") == 25

    # Run 3 (another new session): daily cap reached (25/25) -> DailyCapReachedError halts run
    guards_run3 = GuardsManager(db)
    guards_run3.settings["timing"]["working_hours"]["enabled"] = False
    with pytest.raises(DailyCapReachedError) as exc_info:
        guards_run3.check_pre_job_guards("linkedin")
    assert "Daily attempts cap reached for linkedin: opened 25/25 Easy Apply forms today across all runs" in str(exc_info.value)


def test_end_of_run_summary_details(capsys):
    db = FakeDB(count=0)
    mgr = GuardsManager(db)

    mgr.record_form_opened(platform="linkedin", job_id="li-101")
    mgr.record_attempt_outcome("NEEDS_INPUT")
    mgr.record_needs_input("li-101", "What is your notice period in days?")

    mgr.record_form_opened(platform="linkedin", job_id="li-102")
    mgr.record_attempt_outcome("FAILED")
    mgr.record_failure_reason("li-102", "STUCK_STEP: Modal form step did not advance after click")

    mgr.record_form_opened(platform="linkedin", job_id="li-103")
    mgr.record_attempt_outcome("SKIPPED")
    mgr.record_review_reached("li-103", "unchecked and verified")

    mgr.print_attempts_summary()
    captured = capsys.readouterr().out

    assert "SESSION ATTEMPTS SUMMARY" in captured
    assert "Opened      : 3" in captured
    assert "Needs Input : 1" in captured
    assert "Failed      : 1" in captured
    assert "NEEDS_INPUT Questions:" in captured
    assert "[Job ID: li-101] Question: What is your notice period in days?" in captured
    assert "Failure Reasons:" in captured
    assert "[Job ID: li-102] Reason: STUCK_STEP: Modal form step did not advance after click" in captured
    assert "Follow-Company State per Review Reached:" in captured
    assert "[Job ID: li-103] Follow Company: unchecked and verified" in captured


