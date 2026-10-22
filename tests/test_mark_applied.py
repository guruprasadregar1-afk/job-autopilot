import pytest
import sys
from unittest.mock import MagicMock
from src.db import Database
from src.main import main, mark_applied_cmd

def test_mark_applied_success_on_unverified_job(tmp_path, capsys):
    db_file = tmp_path / "test_mark.db"
    db = Database(str(db_file))
    db.record_job(
        platform="linkedin",
        job_id="test-unverified-1",
        title="Full Stack Developer",
        company="Particle41",
        status="UNVERIFIED",
        failure_reason="Confirmation not detected"
    )

    mark_applied_cmd(db, "test-unverified-1")

    # Status must be APPLIED
    job = db.get_job_by_id("test-unverified-1")
    assert job["status"] == "APPLIED"
    assert job["applied_at"] is not None

    # Must log event MANUALLY_CONFIRMED in job_events
    with db.get_connection() as conn:
        events = conn.execute(
            "SELECT event, old_status, new_status, note FROM job_events WHERE job_id = ? ORDER BY id DESC",
            ("test-unverified-1",)
        ).fetchall()
        assert len(events) >= 1
        latest_event = events[0]
        assert latest_event[0] == "MANUALLY_CONFIRMED"
        assert latest_event[1] == "UNVERIFIED"
        assert latest_event[2] == "APPLIED"

    captured = capsys.readouterr().out
    assert "[SUCCESS] Job test-unverified-1 ('Full Stack Developer' @ 'Particle41') marked as APPLIED" in captured

def test_mark_applied_refuses_non_unverified_job(tmp_path, capsys):
    db_file = tmp_path / "test_mark.db"
    db = Database(str(db_file))
    db.record_job(
        platform="linkedin",
        job_id="test-found-1",
        title="Backend Engineer",
        company="Acme Corp",
        status="FOUND"
    )

    with pytest.raises(SystemExit) as exc:
        mark_applied_cmd(db, "test-found-1")

    assert exc.value.code == 1
    # Status must remain FOUND
    job = db.get_job_by_id("test-found-1")
    assert job["status"] == "FOUND"

    captured = capsys.readouterr().out
    assert "[REFUSAL] Job 'test-found-1' status is 'FOUND'" in captured
    assert "mark-applied only accepts jobs in 'UNVERIFIED' status" in captured

def test_mark_applied_refuses_observed_review_job(tmp_path, capsys):
    db_file = tmp_path / "test_mark.db"
    db = Database(str(db_file))
    db.record_job(
        platform="linkedin",
        job_id="test-rev-1",
        title="Frontend Engineer",
        company="Beta Inc",
        status="OBSERVED_REVIEW"
    )

    with pytest.raises(SystemExit) as exc:
        mark_applied_cmd(db, "test-rev-1")

    assert exc.value.code == 1
    job = db.get_job_by_id("test-rev-1")
    assert job["status"] == "OBSERVED_REVIEW"

def test_mark_applied_nonexistent_job_exits_with_error(tmp_path, capsys):
    db_file = tmp_path / "test_mark.db"
    db = Database(str(db_file))

    with pytest.raises(SystemExit) as exc:
        mark_applied_cmd(db, "nonexistent-999")

    assert exc.value.code == 1
    captured = capsys.readouterr().out
    assert "Job ID 'nonexistent-999' not found in database" in captured

def test_mark_applied_cli_integration(monkeypatch, tmp_path, capsys):
    db_file = tmp_path / "test_cli.db"
    db = Database(str(db_file))
    db.record_job(
        platform="linkedin",
        job_id="4467464995",
        title="Full Stack Javascript Developer",
        company="Particle41",
        status="UNVERIFIED"
    )

    monkeypatch.setattr(sys, "argv", ["main.py", "mark-applied", "--job-id", "4467464995"])
    monkeypatch.setattr("src.main.Database", lambda: db)

    main()

    job = db.get_job_by_id("4467464995")
    assert job["status"] == "APPLIED"

    captured = capsys.readouterr().out
    assert "[SUCCESS] Job 4467464995 ('Full Stack Javascript Developer' @ 'Particle41') marked as APPLIED" in captured

def test_unverified_halt_prints_clean_message_without_traceback(capsys, monkeypatch):
    from src.main import run_pipeline
    from src.policy import UnverifiedApplicationHaltError

    db_mock = MagicMock()
    guards_mock = MagicMock()
    guards_mock.max_attempts = 10
    guards_mock.session_attempts_count = 0
    guards_mock.settings = {"search": {"max_jobs_per_platform": 10}}
    matcher_mock = MagicMock()
    mgr_mock = MagicMock()
    ctx_mock = MagicMock()
    page_mock = MagicMock()
    ctx_mock.pages = [page_mock]
    mgr_mock.start.return_value = ctx_mock

    def failing_pipeline(*args, **kwargs):
        raise UnverifiedApplicationHaltError("Post-submit confirmation missing")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.platforms.linkedin.LinkedInCollector.process_eligible_found_jobs", failing_pipeline)
        # Should not raise exception
        run_pipeline(
            db=db_mock,
            guards=guards_mock,
            matcher=matcher_mock,
            platform="linkedin",
            browser_manager=mgr_mock,
            target_job_id="4467464995"
        )

    captured = capsys.readouterr().out
    assert "Application submitted, success not confirmed: UNVERIFIED. Check LinkedIn My Jobs -> Applied." in captured
