import pytest
from unittest.mock import MagicMock, patch
from src.main import print_run_banner

def test_print_run_banner_confirmed_with_start(capsys):
    guards = MagicMock()
    guards.settings = {
        "caps": {
            "linkedin_daily_cap": 25,
            "naukri_daily_cap": 40,
            "attempts_per_day": 25
        },
        "search": {
            "max_jobs_per_platform": 10
        }
    }
    guards.max_apply = 5
    guards.max_attempts = 10

    active_searches = [
        {"platform": "linkedin", "keywords": "Senior Full Stack Developer", "location": "India"}
    ]

    with patch("builtins.input", return_value="START"):
        print_run_banner(
            platform="linkedin",
            mode="rehearsal (dry-run)",
            guards=guards,
            resume_name="Candidate_Resume.pdf",
            active_searches=active_searches
        )

    captured = capsys.readouterr().out
    assert "JOB AUTOPILOT RUN BANNER" in captured
    assert "Target Platform       : LINKEDIN" in captured
    assert "Execution Mode        : REHEARSAL (DRY-RUN)" in captured
    assert "OBSERVE_ONLY State    : True (Submit strictly blocked)" in captured
    assert "Configured Resume Name: Candidate_Resume.pdf" in captured
    assert "Daily App Cap     : LinkedIn = 25, Naukri = 40" in captured
    assert "Daily Attempts Cap: 25" in captured
    assert "Per-Run Attempts  : 10" in captured
    assert "Per-Run Max Apply : 5" in captured
    assert "Jobs Per Platform : 10" in captured
    assert "[LINKEDIN] 'Senior Full Stack Developer' in India" in captured
    assert "[CONFIRMED] 'START' accepted" in captured

def test_print_run_banner_aborted_without_start(capsys):
    guards = MagicMock()
    guards.settings = {"caps": {}, "search": {}}
    guards.max_apply = None
    guards.max_attempts = 10

    with patch("builtins.input", return_value="NO"):
        with pytest.raises(SystemExit) as exc_info:
            print_run_banner(
                platform="linkedin",
                mode="live",
                guards=guards,
                resume_name="Candidate_Resume.pdf",
                active_searches=[]
            )
        assert exc_info.value.code == 0

    captured = capsys.readouterr().out
    assert "[ABORTED] Run cancelled by user" in captured


def test_print_run_banner_rehearsal_line(capsys):
    guards = MagicMock()
    guards.settings = {"caps": {}, "search": {}}
    guards.max_apply = None
    guards.max_attempts = 10

    with patch("builtins.input", return_value="START"):
        print_run_banner(
            platform="linkedin",
            mode="rehearsal (dry-run)",
            guards=guards,
            resume_name="Candidate_Resume.pdf",
            active_searches=[],
            is_rehearsal=True
        )

    captured = capsys.readouterr().out
    assert "REHEARSAL: submit impossible" in captured
    assert "OBSERVE_ONLY State    : True (Submit strictly blocked)" in captured


def test_rehearse_cannot_combine_with_live_mode_auto(capsys):
    from src.main import main
    import sys
    test_args = ["main.py", "run", "--rehearse", "--auto"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    captured = capsys.readouterr().out
    assert "--rehearse cannot be combined with live mode (--auto)" in captured


def test_rehearsal_attempts_recorded_in_job_attempts(tmp_path):
    from src.db import Database
    from src.guards import GuardsManager
    db_file = tmp_path / "rehearse_test.db"
    db = Database(db_path=db_file)
    guards = GuardsManager(db)

    # In rehearsal, record_form_opened is called with job_id
    guards.record_form_opened(platform="linkedin", job_id="li-999999")
    assert db.get_attempts_count_today("linkedin") == 1

    # Verify directly in SQLite table job_attempts
    with db.get_connection() as conn:
        row = conn.execute("SELECT platform, job_id FROM job_attempts WHERE job_id = 'li-999999'").fetchone()
        assert row is not None
        assert row[0] == "linkedin"
        assert row[1] == "li-999999"


def test_show_needs_input_workflow(tmp_path, capsys):
    from src.db import Database
    from src.main import show_needs_input

    db_file = tmp_path / "needs_input_test.db"
    db = Database(db_path=db_file)

    # 1. Empty state
    show_needs_input(db)
    captured = capsys.readouterr().out
    assert "No pending questions found" in captured

    # 2. Record pending questions of various types
    db.record_job("linkedin", "li-job-1", "Full Stack Engineer", "Acme Corp", status="NEEDS_INPUT", pending_question="Are you authorized to work in Canada?")
    db.record_job("naukri", "nk-job-2", "Backend Dev", "Beta Tech", status="NEEDS_INPUT", pending_question="How many years of microservices experience do you have?")

    show_needs_input(db)
    out = capsys.readouterr().out

    # Check job 1
    assert "Platform    : LINKEDIN | Job ID: li-job-1" in out
    assert "Job         : Full Stack Engineer @ Acme Corp" in out
    assert "Question    : Are you authorized to work in Canada?" in out
    assert "Field Type  : radio / dropdown" in out
    assert "Options Seen: Yes, No" in out
    assert 'value: ""' in out
    assert 'exact_match: true' in out

    # Check job 2
    assert "Platform    : NAUKRI | Job ID: nk-job-2" in out
    assert "Field Type  : numeric / text" in out

